import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/services.dart';
import 'package:media_kit/media_kit.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'flv_relay_bridge.dart';
import 'g711a.dart';

enum IntercomPhase {
  idle,
  connecting,
  connected,
  transmitting,
  disconnected,
  error,
}

/// Controller for two-way audio intercom (ADR-0036).
///
/// Downlink: Bus microphone audio streamed via [streamUrl] (WS-FLV audio),
/// bridged to local HTTP and played through device speaker with `media_kit`.
///
/// Uplink: Operator microphone captured at 8000 Hz 16-bit PCM, encoded to
/// ITU-T G.711A (320-byte chunks = 40ms) and streamed via WebSocket to [uplinkUrl].
class IntercomController {
  static const _audioMethodChannel = MethodChannel('so.raad.raad_mobile/audio');
  static const _micEventChannel = EventChannel('so.raad.raad_mobile/mic_stream');

  final FlvRelayBridge _bridge = FlvRelayBridge();
  Player? _audioPlayer;
  WebSocketChannel? _uplinkSocket;
  StreamSubscription<dynamic>? _micSubscription;

  IntercomPhase _phase = IntercomPhase.idle;
  IntercomPhase get phase => _phase;

  bool get isConnected =>
      _phase == IntercomPhase.connected || _phase == IntercomPhase.transmitting;
  bool get isTransmitting => _phase == IntercomPhase.transmitting;

  final void Function(IntercomPhase phase)? onPhaseChanged;
  final void Function(String error)? onError;

  IntercomController({this.onPhaseChanged, this.onError});

  void _setPhase(IntercomPhase newPhase) {
    _phase = newPhase;
    onPhaseChanged?.call(newPhase);
  }

  /// Connects downlink and uplink audio streams.
  Future<void> connect({
    required String? streamUrl,
    required String? uplinkUrl,
  }) async {
    _setPhase(IntercomPhase.connecting);

    // 1. Setup downlink audio player
    if (streamUrl != null && streamUrl.isNotEmpty) {
      try {
        final localUrl = await _bridge.start(streamUrl);
        _audioPlayer = Player();
        await _audioPlayer!.open(Media(localUrl));
      } catch (e) {
        // Continue even if downlink fails so uplink can still connect
      }
    }

    // 2. Setup uplink WebSocket
    if (uplinkUrl != null && uplinkUrl.isNotEmpty) {
      try {
        final uri = Uri.parse(uplinkUrl);
        _uplinkSocket = WebSocketChannel.connect(uri);
      } catch (e) {
        onError?.call('Could not connect uplink: $e');
      }
    }

    _setPhase(IntercomPhase.connected);
  }

  /// Starts transmitting microphone audio to the driver.
  Future<void> startTalking() async {
    if (!isConnected || isTransmitting) return;

    try {
      // Start native recording
      final started = await _audioMethodChannel.invokeMethod<bool>('startRecording');
      if (started == true) {
        _setPhase(IntercomPhase.transmitting);

        _micSubscription?.cancel();
        _micSubscription = _micEventChannel.receiveBroadcastStream().listen(
          (dynamic data) {
            if (_phase != IntercomPhase.transmitting) return;
            if (data is Uint8List && data.isNotEmpty) {
              final aLawBytes = encodePcm16ToALaw(data);
              // Send 320-byte chunks to relay
              _uplinkSocket?.sink.add(aLawBytes);
            }
          },
          onError: (Object error) {
            stopTalking();
            onError?.call('Mic error: $error');
          },
        );
      } else {
        onError?.call('Could not start microphone');
      }
    } on PlatformException catch (e) {
      onError?.call(e.message ?? 'Mic permission denied');
    } catch (e) {
      onError?.call('Failed to start talking: $e');
    }
  }

  /// Stops transmitting microphone audio. Downlink stays connected so operator hears driver.
  Future<void> stopTalking() async {
    if (_phase != IntercomPhase.transmitting) return;

    try {
      _micSubscription?.cancel();
      _micSubscription = null;
      await _audioMethodChannel.invokeMethod<bool>('stopRecording');
    } catch (_) {}

    _setPhase(IntercomPhase.connected);
  }

  /// Completely disconnects and tears down audio sockets and players.
  Future<void> disconnect() async {
    await stopTalking();
    try {
      _uplinkSocket?.sink.close();
      _uplinkSocket = null;
    } catch (_) {}

    try {
      await _bridge.stop();
      _audioPlayer?.dispose();
      _audioPlayer = null;
    } catch (_) {}

    _setPhase(IntercomPhase.disconnected);
  }
}
