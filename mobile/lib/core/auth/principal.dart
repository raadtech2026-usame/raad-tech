/// Mirrors `PrincipalResponse` (backend `iam/api/schemas.py`) exactly. `role` stays the raw
/// lower-case string the backend sends (`"parent"`/`"driver"`) — this app only ever needs to
/// branch on those two values (`.claude/rules/flutter.md` #1: "no admin features on mobile"),
/// so a full enum mirroring every one of the backend's seven `Role` values would be unused
/// surface area.
class Principal {
  final String userId;
  final String role;
  final String? organizationId;

  const Principal({
    required this.userId,
    required this.role,
    required this.organizationId,
  });

  factory Principal.fromJson(Map<String, dynamic> json) {
    return Principal(
      userId: json['user_id'] as String,
      role: json['role'] as String,
      organizationId: json['organization_id'] as String?,
    );
  }

  bool get isParent => role == 'parent';
  bool get isDriver => role == 'driver';
}
