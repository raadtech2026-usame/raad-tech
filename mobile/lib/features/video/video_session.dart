/// Mirrors `VideoSessionResponse` (backend `video/api/schemas.py`) — only the fields this app
/// actually uses are parsed (`id`, `status`, `streamUrl`); the rest of the wire response is
/// simply ignored, not modeled, since nothing here needs them.
class VideoSession {
  final String id;
  final String status;
  final String? streamUrl;

  const VideoSession({required this.id, required this.status, required this.streamUrl});

  factory VideoSession.fromJson(Map<String, dynamic> json) {
    return VideoSession(
      id: json['id'] as String,
      status: json['status'] as String,
      streamUrl: json['stream_url'] as String?,
    );
  }
}
