import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/api_client.dart';
import '../storage/secure_token_storage.dart';
import 'auth_repository.dart';
import 'auth_session.dart';

/// Hand-written `StateNotifier`-based Riverpod (not the `@riverpod` code-generation API) —
/// deliberate: code generation needs `build_runner`, an extra build step this app's own CI
/// (Phase M5, not yet built) would need to run before every build, and there is no reduction in
/// runtime behavior for an app this size, only a build-time dependency this phase doesn't need
/// to add.
sealed class AuthState {
  const AuthState();
}

/// Startup: checking secure storage for an existing refresh token before deciding where to
/// route (`app/app.dart`) — never flashes the login screen for an already-signed-in user.
class AuthInitial extends AuthState {
  const AuthInitial();
}

class AuthUnauthenticated extends AuthState {
  const AuthUnauthenticated();
}

class AuthAuthenticated extends AuthState {
  final AuthSession session;
  const AuthAuthenticated(this.session);
}

class AuthController extends StateNotifier<AuthState> {
  final AuthRepository _authRepository;
  final SecureTokenStorage _tokenStorage;
  final ApiClient _apiClient;

  AuthController(this._authRepository, this._tokenStorage, this._apiClient)
      : super(const AuthInitial()) {
    _restoreSession();
  }

  Future<void> _restoreSession() async {
    final refreshToken = await _tokenStorage.readRefreshToken();
    if (refreshToken == null) {
      state = const AuthUnauthenticated();
      return;
    }
    try {
      final session = await _authRepository.refresh(refreshToken);
      await _applySession(session);
    } catch (_) {
      // Stored refresh token is expired/revoked/invalid - fall back to a clean login prompt
      // rather than an error screen (`.claude/rules/flutter.md` #6: degrade visibly, never a
      // silent stall - a login screen IS the visible, correct degraded state here).
      await _tokenStorage.clear();
      state = const AuthUnauthenticated();
    }
  }

  Future<void> login({required String identifier, required String password}) async {
    final session = await _authRepository.login(
      identifier: identifier,
      password: password,
    );
    await _applySession(session);
  }

  Future<void> logout() async {
    final current = state;
    if (current is AuthAuthenticated) {
      try {
        await _authRepository.logout(current.session.refreshToken);
      } catch (_) {
        // Best-effort - the server-side revoke failing must never block the local sign-out.
      }
    }
    await _tokenStorage.clear();
    _apiClient.clearAccessToken();
    state = const AuthUnauthenticated();
  }

  Future<void> _applySession(AuthSession session) async {
    await _tokenStorage.saveRefreshToken(session.refreshToken);
    _apiClient.setAccessToken(session.accessToken);
    state = AuthAuthenticated(session);
  }
}

final apiClientProvider = Provider<ApiClient>((ref) => ApiClient());

final secureTokenStorageProvider =
    Provider<SecureTokenStorage>((ref) => const SecureTokenStorage());

final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return AuthRepository(ref.watch(apiClientProvider));
});

final authControllerProvider =
    StateNotifierProvider<AuthController, AuthState>((ref) {
  return AuthController(
    ref.watch(authRepositoryProvider),
    ref.watch(secureTokenStorageProvider),
    ref.watch(apiClientProvider),
  );
});
