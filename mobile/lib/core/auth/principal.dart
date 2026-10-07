/// Mirrors `PrincipalResponse` (backend `iam/api/schemas.py`) exactly. `role` stays the raw
/// lower-case string the backend sends. The app has three experiences: parent, driver, and a
/// read-only operations view for the organization admin (ADR-0062). RAAD's own staff roles
/// have none and are told to use the web dashboard.
class Principal {
  final String userId;
  final String role;
  final String? organizationId;

  /// True while the account still holds the one-time password the school handed over.
  final bool isPasswordChangeRequired;

  const Principal({
    required this.userId,
    required this.role,
    required this.organizationId,
    this.isPasswordChangeRequired = false,
  });

  factory Principal.fromJson(Map<String, dynamic> json) {
    return Principal(
      userId: json['user_id'] as String,
      role: json['role'] as String,
      organizationId: json['organization_id'] as String?,
      isPasswordChangeRequired:
          json['is_password_change_required'] as bool? ?? false,
    );
  }

  bool get isParent => role == 'parent';
  bool get isDriver => role == 'driver';
  bool get isOrgAdmin => role == 'org_admin';
}
