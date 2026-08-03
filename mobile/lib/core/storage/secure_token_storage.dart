import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Refresh-token-only secure storage (Phase M0's own exit criteria: "refresh token in secure
/// storage, access token in memory, mirroring the web's own in-memory-access-token posture as
/// closely as a mobile app's different security model allows" — `.claude/rules/flutter.md` #5:
/// "Tokens live in secure storage"). The access token deliberately never touches this class —
/// it lives only in `AuthController`'s own in-memory state (`core/auth/auth_state.dart`), so a
/// stolen/backed-up keychain entry alone can never yield a currently-valid access token, only a
/// refresh token that still has to pass through `/auth/refresh` (itself rotated on every use,
/// per the backend's own refresh-token-rotation design).
class SecureTokenStorage {
  static const _refreshTokenKey = 'raad_refresh_token';

  final FlutterSecureStorage _storage;

  const SecureTokenStorage({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  Future<void> saveRefreshToken(String token) {
    return _storage.write(key: _refreshTokenKey, value: token);
  }

  Future<String?> readRefreshToken() {
    return _storage.read(key: _refreshTokenKey);
  }

  Future<void> clear() {
    return _storage.delete(key: _refreshTokenKey);
  }
}
