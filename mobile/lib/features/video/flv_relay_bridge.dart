import 'dart:async';
import 'dart:io';

import 'package:web_socket_channel/web_socket_channel.dart';

/// Bridges the JT1078 relay's own bespoke WS-FLV protocol (binary WebSocket frames, each one
/// already a complete, ready-to-forward chunk of a valid, incrementally-built FLV byte stream —
/// `services/jt1078/src/repackager/flv_muxer.py`'s own design) to an ordinary
/// `http://127.0.0.1:<port>/stream.flv` URL a native video player can open directly — no
/// Flutter media package understands the relay's own WS protocol, but every one of them
/// understands "an HTTP URL streaming FLV bytes" (the same bridging trick many production
/// http-flv/WS-FLV players use server-side, done client-side here instead).
///
/// **Single-listener only, by design.** `media_kit` opens exactly one persistent connection to
/// consume a live stream (the same shape a plain `<video>`/http-flv player already uses) — a
/// second concurrent request against the same bridge instance would miss the FLV file header
/// (already sent once, to the first request, the instant the WebSocket connected) and could
/// never parse, so it is rejected outright (503) rather than silently served a broken stream.
///
/// **Not verified against a real Flutter/media_kit runtime** — no Flutter SDK in this sandbox
/// (the same disclosed limitation every other mobile-app phase carries). The WebSocket framing
/// this class relies on (`services/jt1078/src/viewer/websocket_server.py`'s hand-rolled RFC 6455
/// server, `send_binary`) and `dart:io.HttpServer`'s own chunked-transfer behavior for a
/// no-`Content-Length` response are each independently well-established, but the two have not
/// been exercised together end to end, and never against a real device's own media bytes.
class FlvRelayBridge {
  HttpServer? _httpServer;
  WebSocketChannel? _wsChannel;
  StreamController<List<int>>? _byteController;
  StreamSubscription<dynamic>? _wsSubscription;
  bool _servedFirstRequest = false;

  /// The local URL to hand to the video player once [start] completes.
  String? get localStreamUrl =>
      _httpServer == null ? null : 'http://127.0.0.1:${_httpServer!.port}/stream.flv';

  /// Connects to the relay's own `ws://.../viewer?token=...` URL and starts the local HTTP
  /// bridge server. Returns [localStreamUrl]. A rejected token (expired/already-used/invalid —
  /// `ViewerServer._authorize`) or a session that isn't active yet (`session_not_active`) closes
  /// the WebSocket immediately with a close code the relay itself has already assigned (4001 /
  /// 4004) — surfaced here only as the underlying stream ending with no bytes ever received,
  /// not a distinguishable error, since `web_socket_channel` does not expose close codes any
  /// more granularly than that on this platform.
  Future<String> start(String relayWebSocketUrl) async {
    await stop();

    _byteController = StreamController<List<int>>.broadcast();
    _servedFirstRequest = false;
    final channel = WebSocketChannel.connect(Uri.parse(relayWebSocketUrl));
    _wsChannel = channel;
    _wsSubscription = channel.stream.listen(
      (frame) {
        if (frame is List<int>) {
          _byteController?.add(frame);
        }
        // A non-binary frame is never expected from this relay (it only ever sends FLV bytes
        // over binary WS frames, `ViewerServer`'s own module docstring) — silently ignored
        // rather than crashing the stream over an unexpected control message.
      },
      onDone: () => _byteController?.close(),
      onError: (_) => _byteController?.close(),
      cancelOnError: true,
    );

    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    _httpServer = server;
    _serveRequests(server);
    return localStreamUrl!;
  }

  void _serveRequests(HttpServer server) {
    server.listen((request) async {
      if (_servedFirstRequest) {
        request.response.statusCode = HttpStatus.serviceUnavailable;
        await request.response.close();
        return;
      }
      _servedFirstRequest = true;

      final response = request.response;
      response.headers.contentType = ContentType('video', 'x-flv');
      // No Content-Length set — `dart:io.HttpServer` switches to chunked transfer encoding
      // automatically for an HTTP/1.1 response with an unknown length, the correct shape for a
      // live, unbounded byte stream (matches ADR-0024 §4's own "no growing cache": this bridge
      // holds no buffer beyond whatever `dart:io` itself queues for one in-flight `add` call).
      response.bufferOutput = false;
      final stream = _byteController?.stream;
      if (stream == null) {
        await response.close();
        return;
      }
      try {
        await for (final chunk in stream) {
          response.add(chunk);
          await response.flush();
        }
      } catch (_) {
        // The player disconnected (stopped watching) — not an error worth surfacing, the same
        // "one bad viewer must not break anything else" posture the relay's own
        // `SessionBroadcastHub` already applies server-side.
      } finally {
        await response.close();
      }
    });
  }

  Future<void> stop() async {
    await _wsSubscription?.cancel();
    await _wsChannel?.sink.close();
    await _byteController?.close();
    await _httpServer?.close(force: true);
    _wsSubscription = null;
    _wsChannel = null;
    _byteController = null;
    _httpServer = null;
    _servedFirstRequest = false;
  }
}
