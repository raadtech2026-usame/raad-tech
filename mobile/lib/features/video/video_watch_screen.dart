import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'video_player_screen.dart';
import 'video_providers.dart';

/// Requests a live video session for a device/camera and, on success, opens
/// [VideoPlayerScreen]. **Manual device/camera id entry, the same disclosed stand-in pattern
/// `ParentHomeScreen`'s own docstring already established for "list my children"** — no
/// endpoint reachable by the `parent` role resolves "which devices/cameras belong to my own
/// children's buses" (the closest capability, `GET /me/students`, stops at student/route
/// identity and does not descend to vehicle/device/camera — a real, undocumented-until-now gap
/// this screen surfaces honestly rather than fabricating a picker). **Safety is not weakened by
/// this**: `POST /video/live` independently, server-side, re-verifies this parent owns a child
/// currently assigned to whatever device id is submitted (`interfaces/http/policy_guards.
/// resolve_d5_decision`, ADR-0026 §3) — a wrong or someone-else's device id 404s, never
/// silently streams the wrong bus.
class VideoWatchScreen extends ConsumerStatefulWidget {
  const VideoWatchScreen({super.key});

  @override
  ConsumerState<VideoWatchScreen> createState() => _VideoWatchScreenState();
}

class _VideoWatchScreenState extends ConsumerState<VideoWatchScreen> {
  final _deviceIdController = TextEditingController();
  final _cameraIdController = TextEditingController();
  bool _isRequesting = false;
  String? _error;

  @override
  void dispose() {
    _deviceIdController.dispose();
    _cameraIdController.dispose();
    super.dispose();
  }

  Future<void> _watchLive() async {
    final deviceId = _deviceIdController.text.trim();
    final cameraId = _cameraIdController.text.trim();
    if (deviceId.isEmpty || cameraId.isEmpty) return;

    setState(() {
      _isRequesting = true;
      _error = null;
    });
    try {
      final session = await ref
          .read(videoRepositoryProvider)
          .requestLive(deviceId: deviceId, cameraId: cameraId);
      if (!mounted) return;
      if (session.streamUrl == null) {
        setState(() {
          _isRequesting = false;
          _error = 'No stream URL was returned — the video relay may not be configured.';
        });
        return;
      }
      setState(() => _isRequesting = false);
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => VideoPlayerScreen(
            videoSessionId: session.id,
            relayStreamUrl: session.streamUrl!,
          ),
        ),
      );
    } catch (error) {
      // `.claude/rules/flutter.md` #6: surface the real server error verbatim (e.g.
      // "Video access denied" / a 404 for a device this parent does not own) rather than a
      // generic failure message that hides *why*.
      if (mounted) {
        setState(() {
          _isRequesting = false;
          _error = error.toString();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Watch live video')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Card(
              child: Padding(
                padding: EdgeInsets.all(16),
                child: Text(
                  'Enter your child\'s bus device and camera id to start a live video stream. '
                  'This only works if the school has granted you live video access.',
                ),
              ),
            ),
            const SizedBox(height: 24),
            TextField(
              controller: _deviceIdController,
              decoration: const InputDecoration(
                labelText: 'Device ID',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _cameraIdController,
              decoration: const InputDecoration(
                labelText: 'Camera ID',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 16),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ),
            FilledButton.icon(
              onPressed: _isRequesting ? null : _watchLive,
              icon: _isRequesting
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.videocam),
              label: Text(_isRequesting ? 'Connecting…' : 'Watch live'),
            ),
          ],
        ),
      ),
    );
  }
}
