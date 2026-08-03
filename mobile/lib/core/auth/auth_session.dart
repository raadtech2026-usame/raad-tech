import 'principal.dart';

/// The result of a successful login/refresh — mirrors `TokenResponse` (backend
/// `iam/api/schemas.py`). `accessToken` is handed to `ApiClient`/`TrackingWebSocketClient` by
/// whoever holds this session; it is never itself persisted (`SecureTokenStorage` only ever
/// sees `refreshToken`).
class AuthSession {
  final String accessToken;
  final String refreshToken;
  final Principal principal;

  const AuthSession({
    required this.accessToken,
    required this.refreshToken,
    required this.principal,
  });

  factory AuthSession.fromJson(Map<String, dynamic> json) {
    return AuthSession(
      accessToken: json['access_token'] as String,
      refreshToken: json['refresh_token'] as String,
      principal: Principal.fromJson(json['principal'] as Map<String, dynamic>),
    );
  }
}
