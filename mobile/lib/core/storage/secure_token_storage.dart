import 'dart:convert';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../auth/auth_session.dart';

/// Secure storage for tokens and session state.
/// Holds the refresh token and cached session so that offline launches retain
/// user identity and assigned rosters without booting the user out to LoginScreen.
class SecureTokenStorage {
  static const _refreshTokenKey = 'raad_refresh_token';
  static const _sessionKey = 'raad_cached_session';

  final FlutterSecureStorage _storage;

  const SecureTokenStorage({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  Future<void> saveRefreshToken(String token) {
    return _storage.write(key: _refreshTokenKey, value: token);
  }

  Future<String?> readRefreshToken() {
    return _storage.read(key: _refreshTokenKey);
  }

  Future<void> saveSession(AuthSession session) {
    return _storage.write(
      key: _sessionKey,
      value: jsonEncode(session.toJson()),
    );
  }

  Future<AuthSession?> readSession() async {
    final raw = await _storage.read(key: _sessionKey);
    if (raw == null) return null;
    try {
      final json = jsonDecode(raw) as Map<String, dynamic>;
      return AuthSession.fromJson(json);
    } catch (_) {
      return null;
    }
  }

  Future<void> clearSession() {
    return _storage.delete(key: _sessionKey);
  }

  Future<void> clear() async {
    await _storage.delete(key: _refreshTokenKey);
    await _storage.delete(key: _sessionKey);
  }

  Future<void> saveCustom(String key, String value) =>
      _storage.write(key: key, value: value);

  Future<String?> readCustom(String key) => _storage.read(key: key);

  Future<void> deleteCustom(String key) => _storage.delete(key: key);
}
