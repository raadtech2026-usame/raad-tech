import '../network/api_client.dart';
import 'auth_session.dart';

/// The signed-in person's own account, from `GET /auth/me`.
class UserProfile {
  final String fullName;
  final String? email;
  final String? phone;
  final String role;

  const UserProfile({
    required this.fullName,
    required this.email,
    required this.phone,
    required this.role,
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) {
    return UserProfile(
      fullName: json['full_name'] as String? ?? '',
      email: json['email'] as String?,
      phone: json['phone'] as String?,
      role: json['role'] as String? ?? '',
    );
  }
}

/// One active refresh-token / session returned by `GET /auth/sessions` (ADR-0019).
class ActiveSession {
  final String id;
  final String? deviceLabel;
  final String? ipAddress;
  final DateTime issuedAt;
  final DateTime expiresAt;

  const ActiveSession({
    required this.id,
    this.deviceLabel,
    this.ipAddress,
    required this.issuedAt,
    required this.expiresAt,
  });

  factory ActiveSession.fromJson(Map<String, dynamic> json) {
    return ActiveSession(
      id: json['id'] as String,
      deviceLabel: json['device_label'] as String?,
      ipAddress: json['ip_address'] as String?,
      issuedAt: DateTime.parse(json['issued_at'] as String),
      expiresAt: DateTime.parse(json['expires_at'] as String),
    );
  }
}

class AuthRepository {
  final ApiClient _client;

  const AuthRepository(this._client);

  Future<AuthSession> login({
    required String identifier,
    required String password,
  }) async {
    final json = await _client.post(
      '/auth/login',
      auth: false,
      body: {'identifier': identifier, 'password': password},
    );
    return AuthSession.fromJson(json);
  }

  Future<AuthSession> refresh(String refreshToken) async {
    final json = await _client.post(
      '/auth/refresh',
      auth: false,
      body: {'refresh_token': refreshToken},
    );
    return AuthSession.fromJson(json);
  }

  /// `/auth/logout` needs the bearer access token as well as the refresh token in the body,
  /// so it must be called before the access token is cleared.
  Future<void> logout(String refreshToken) async {
    await _client.post('/auth/logout', body: {'refresh_token': refreshToken});
  }

  Future<void> changePassword(String newPassword) async {
    await _client.post(
      '/auth/change-password',
      body: {'new_password': newPassword},
    );
  }

  Future<UserProfile> profile() async {
    return UserProfile.fromJson(await _client.get('/auth/me'));
  }

  /// Lists the caller's own active sessions (ADR-0019). Newest-first.
  Future<List<ActiveSession>> listSessions() async {
    final raw = await _client.getList('/auth/sessions', cache: false);
    return raw.map(ActiveSession.fromJson).toList();
  }

  /// Revokes one of the caller's own sessions by id (ADR-0019).
  Future<void> revokeSession(String sessionId) async {
    await _client.delete('/auth/sessions/$sessionId');
  }
}
