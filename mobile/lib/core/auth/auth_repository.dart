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
    await _client
        .post('/auth/change-password', body: {'new_password': newPassword});
  }

  Future<UserProfile> profile() async {
    return UserProfile.fromJson(await _client.get('/auth/me'));
  }
}
