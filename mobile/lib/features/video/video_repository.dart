import '../../core/network/api_client.dart';
import 'video_session.dart';

/// `POST /video/live` / `/video/playback` / `/video/sessions/{id}/stop` (API Contracts §4.5,
/// ADR-0026 §3/§5). A 403 (`VIDEO_FORBIDDEN`) here means the caller's own `has_video_live_access`/
/// `has_video_playback_access` flag is not actually set server-side — this repository never
/// second-guesses that; `ApiException` propagates to the caller unchanged (`.claude/rules/
/// flutter.md` #6: degrade visibly, never hide the real reason). A 404 means this parent does
/// not own the requested device/child at all (`interfaces/http/policy_guards.
/// resolve_d5_decision`'s own 404-over-403 distinction).
class VideoRepository {
  final ApiClient _client;

  const VideoRepository(this._client);

  Future<VideoSession> requestLive({
    required String deviceId,
    required String cameraId,
  }) async {
    final json = await _client.post(
      '/video/live',
      body: {'device_id': deviceId, 'camera_id': cameraId},
    );
    return VideoSession.fromJson(json);
  }

  Future<VideoSession> requestPlayback({
    required String deviceId,
    required String cameraId,
    required DateTime windowStart,
    required DateTime windowEnd,
  }) async {
    final json = await _client.post(
      '/video/playback',
      body: {
        'device_id': deviceId,
        'camera_id': cameraId,
        'window_start': windowStart.toUtc().toIso8601String(),
        'window_end': windowEnd.toUtc().toIso8601String(),
      },
    );
    return VideoSession.fromJson(json);
  }

  Future<VideoSession> stop(String videoSessionId) async {
    final json = await _client.post('/video/sessions/$videoSessionId/stop');
    return VideoSession.fromJson(json);
  }
}
