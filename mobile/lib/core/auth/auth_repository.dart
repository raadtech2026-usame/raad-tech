import '../network/api_client.dart';
import 'auth_session.dart';

/// `POST /auth/login` / `POST /auth/refresh` — mirrors `iam.api.routers.login`/`refresh`
/// exactly (`identifier` is an email or E.164 phone number, matching `LoginRequest`; refresh
/// rotates the token, matching the backend's own refresh-token-rotation design, so the caller
/// must always persist the *new* `refreshToken` this returns, never reuse the one just spent).
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

  Future<void> logout(String refreshToken) async {
    // Unlike login/refresh, /auth/logout requires a valid bearer access token
    // (`Depends(get_current_user)`, `iam/api/routers.py`) in *addition* to the refresh token
    // in the body — `auth: true` (the default) so `ApiClient`'s currently-set access token is
    // sent. Must be called before `ApiClient.clearAccessToken()`, or this 401s.
    await _client.post(
      '/auth/logout',
      body: {'refresh_token': refreshToken},
    );
  }
}
