/// Mirrors `VideoSessionResponse` (backend `video/api/schemas.py`) — parsed fields include
/// `id`, `status`, `streamUrl`, and optional `uplinkUrl` (ADR-0036).
class VideoSession {
  final String id;
  final String status;
  final String? streamUrl;
  final String? uplinkUrl;

  const VideoSession({
    required this.id,
    required this.status,
    required this.streamUrl,
    this.uplinkUrl,
  });

  factory VideoSession.fromJson(Map<String, dynamic> json) {
    return VideoSession(
      id: json['id'] as String,
      status: json['status'] as String,
      streamUrl: json['stream_url'] as String?,
      uplinkUrl: json['uplink_url'] as String?,
    );
  }
}
