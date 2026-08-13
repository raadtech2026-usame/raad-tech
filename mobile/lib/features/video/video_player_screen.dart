import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

import 'flv_relay_bridge.dart';
import 'video_providers.dart';

/// Renders one already-granted [VideoSession]'s live stream. **Reachability here already
/// implies the server-side chain in `interfaces/http/policy_guards.resolve_d5_decision`
/// (ADR-0026 §3) has already run and allowed the request** — this screen performs no
/// authorization of its own, the same "the API call either succeeded or this screen was never
/// reached" posture every other screen in this app already has.
///
/// `[FlvRelayBridge]` does the actual protocol bridging (WS-FLV -> a local `http://` URL
/// `media_kit` can open); this widget only owns the player/bridge lifecycle — start on
/// [initState], tear both down on [dispose] and call `POST /video/sessions/{id}/stop` so the
/// relay and device stop streaming the instant the viewer leaves (ADR-0024 §5 point 3/4 — no
/// "silently keep streaming after the screen closes").
///
/// **Not verified against a real Flutter/media_kit runtime or a physical MDVR** — see
/// `flv_relay_bridge.dart`'s own module docstring for the full disclosed-limitation detail.
class VideoPlayerScreen extends ConsumerStatefulWidget {
  final String videoSessionId;
  final String relayStreamUrl;

  const VideoPlayerScreen({
    super.key,
    required this.videoSessionId,
    required this.relayStreamUrl,
  });

  @override
  ConsumerState<VideoPlayerScreen> createState() => _VideoPlayerScreenState();
}

class _VideoPlayerScreenState extends ConsumerState<VideoPlayerScreen> {
  final _bridge = FlvRelayBridge();
  late final Player _player;
  late final VideoController _controller;
  bool _isConnecting = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _player = Player();
    _controller = VideoController(_player);
    _connect();
  }

  Future<void> _connect() async {
    try {
      final localUrl = await _bridge.start(widget.relayStreamUrl);
      await _player.open(Media(localUrl));
      if (mounted) setState(() => _isConnecting = false);
    } catch (error) {
      // `.claude/rules/flutter.md` #6: degrade visibly, never a silent stall - a connection
      // failure (bad/expired token, relay unreachable, session not active yet) must surface as
      // a clear, explicit state, not an indefinitely spinning loader.
      if (mounted) {
        setState(() {
          _isConnecting = false;
          _error = 'Could not connect to the live stream: $error';
        });
      }
    }
  }

  @override
  void dispose() {
    // Best-effort - a failed stop call must never block leaving the screen (mirrors
    // `AuthController.logout`'s identical "best-effort server call, local cleanup always
    // proceeds" posture).
    ref.read(videoRepositoryProvider).stop(widget.videoSessionId).catchError((_) {});
    _bridge.stop();
    _player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Live video')),
      backgroundColor: Colors.black,
      body: Center(
        child: _error != null
            ? Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  _error!,
                  style: const TextStyle(color: Colors.white),
                  textAlign: TextAlign.center,
                ),
              )
            : _isConnecting
                ? const Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      CircularProgressIndicator(),
                      SizedBox(height: 16),
                      Text('Connecting…', style: TextStyle(color: Colors.white)),
                    ],
                  )
                : Video(controller: _controller),
      ),
    );
  }
}
