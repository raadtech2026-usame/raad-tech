/// Mirrors `MeIdentityResponse` (backend `iam/api/schemas.py`, ADR-0023, extended by ADR-0026
/// §5). `hasVideoLiveAccess`/`hasVideoPlaybackAccess` are presentation only — this app hides/
/// shows the video affordance based on them, but the real, independent gate is server-side
/// (`interfaces/http/policy_guards.resolve_d5_decision`); a stale or tampered client value here
/// can only ever hide a control that would still work, never grant a request the backend would
/// otherwise deny (`.claude/rules/frontend.md` #2, applied to mobile).
class MeIdentity {
  final String userId;
  final String role;
  final String? organizationId;
  final String? parentId;
  final String? driverId;
  final bool hasVideoLiveAccess;
  final bool hasVideoPlaybackAccess;

  const MeIdentity({
    required this.userId,
    required this.role,
    required this.organizationId,
    required this.parentId,
    required this.driverId,
    required this.hasVideoLiveAccess,
    required this.hasVideoPlaybackAccess,
  });

  factory MeIdentity.fromJson(Map<String, dynamic> json) {
    return MeIdentity(
      userId: json['user_id'] as String,
      role: json['role'] as String,
      organizationId: json['organization_id'] as String?,
      parentId: json['parent_id'] as String?,
      driverId: json['driver_id'] as String?,
      hasVideoLiveAccess: json['has_video_live_access'] as bool? ?? false,
      hasVideoPlaybackAccess: json['has_video_playback_access'] as bool? ?? false,
    );
  }

  /// Neither video permission granted — the default, off-by-default state every newly
  /// registered parent starts in (ADR-0026 §1) and every non-Parent role always has.
  bool get hasAnyVideoAccess => hasVideoLiveAccess || hasVideoPlaybackAccess;
}
