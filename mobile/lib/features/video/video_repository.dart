import '../../core/network/api_client.dart';
import 'video_session.dart';

/// `POST /video/live` / `/video/playback` / `/video/intercom` / `/video/sessions/{id}/stop`
/// (API Contracts §4.5, ADR-0026 §3/§5, ADR-0036, ADR-0043).
class VideoRepository {
  final ApiClient _client;

  const VideoRepository(this._client);

  Future<VideoSession> requestLive({
    required String deviceId,
    required String cameraId,
    String streamType = 'sub',
  }) async {
    final json = await _client.post(
      '/video/live',
      body: {
        'device_id': deviceId,
        'camera_id': cameraId,
        'stream_type': streamType,
      },
    );
    return VideoSession.fromJson(json);
  }

  Future<VideoSession> requestIntercom({
    required String deviceId,
    required String cameraId,
  }) async {
    final json = await _client.post(
      '/video/intercom',
      body: {
        'device_id': deviceId,
        'camera_id': cameraId,
      },
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
