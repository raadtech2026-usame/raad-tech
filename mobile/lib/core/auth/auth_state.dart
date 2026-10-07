import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/api_client.dart';
import '../network/api_exception.dart';
import '../push/push_service.dart';
import '../storage/secure_token_storage.dart';
import 'auth_repository.dart';
import 'auth_session.dart';
import 'principal.dart';

sealed class AuthState {
  const AuthState();
}

/// Startup: checking secure storage for a refresh token before deciding where to go.
class AuthInitial extends AuthState {
  const AuthInitial();
}

class AuthUnauthenticated extends AuthState {
  /// True when the app signed the person out because the session could not be renewed.
  final bool sessionExpired;
  const AuthUnauthenticated({this.sessionExpired = false});
}

class AuthAuthenticated extends AuthState {
  final AuthSession session;
  const AuthAuthenticated(this.session);
}

class AuthController extends StateNotifier<AuthState> {
  final AuthRepository _authRepository;
  final SecureTokenStorage _tokenStorage;
  final ApiClient _apiClient;
  final PushService _push;

  AuthController(
      this._authRepository, this._tokenStorage, this._apiClient, this._push)
      : super(const AuthInitial()) {
    _apiClient.onUnauthorized = _renewSession;
    _restoreSession();
  }

  Future<void> _restoreSession() async {
    final refreshToken = await _tokenStorage.readRefreshToken();
    if (refreshToken == null) {
      state = const AuthUnauthenticated();
      return;
    }
    try {
      await _applySession(await _authRepository.refresh(refreshToken));
    } on ApiException catch (e) {
      if (e.isNetwork) {
        // Offline at startup: keep the token and let the person retry from the login screen
        // rather than throwing away a session that is probably still good.
        state = const AuthUnauthenticated();
        return;
      }
      await _tokenStorage.clear();
      state = const AuthUnauthenticated();
    } catch (_) {
      await _tokenStorage.clear();
      state = const AuthUnauthenticated();
    }
  }

  /// Called by [ApiClient] when a request answers 401. The refresh token rotates on every
  /// use, so the new one replaces the stored one before anything else happens.
  Future<bool> _renewSession() async {
    final current = state;
    if (current is! AuthAuthenticated) return false;
    try {
      final session =
          await _authRepository.refresh(current.session.refreshToken);
      await _applySession(session);
      return true;
    } on ApiException catch (e) {
      if (e.isNetwork) return false;
      await _signOutLocally(sessionExpired: true);
      return false;
    } catch (_) {
      return false;
    }
  }

  Future<void> login(
      {required String identifier, required String password}) async {
    final session =
        await _authRepository.login(identifier: identifier, password: password);
    await _applySession(session);
  }

  /// Replaces the temporary password. The server clears its flag; the session in hand is
  /// updated to match so the app moves on without a second login.
  Future<void> changePassword(String newPassword) async {
    await _authRepository.changePassword(newPassword);
    final current = state;
    if (current is AuthAuthenticated) {
      final old = current.session;
      state = AuthAuthenticated(
        AuthSession(
          accessToken: old.accessToken,
          refreshToken: old.refreshToken,
          principal: Principal(
            userId: old.principal.userId,
            role: old.principal.role,
            organizationId: old.principal.organizationId,
          ),
        ),
      );
    }
  }

  Future<void> logout() async {
    final current = state;
    if (current is AuthAuthenticated) {
      await _push.unregister().catchError((_) {});
      try {
        await _authRepository.logout(current.session.refreshToken);
      } catch (_) {
        // Best effort: a failed server-side revoke must never block the local sign-out.
      }
    }
    await _signOutLocally();
  }

  Future<void> _signOutLocally({bool sessionExpired = false}) async {
    await _tokenStorage.clear();
    _apiClient.clearAccessToken();
    state = AuthUnauthenticated(sessionExpired: sessionExpired);
  }

  Future<void> _applySession(AuthSession session) async {
    await _tokenStorage.saveRefreshToken(session.refreshToken);
    _apiClient.setAccessToken(session.accessToken);
    final wasSignedIn = state is AuthAuthenticated;
    state = AuthAuthenticated(session);
    if (!wasSignedIn) {
      _push.register().catchError((_) {});
    }
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
    ref.watch(pushServiceProvider),
  );
});

/// The signed-in principal, or null.
final principalProvider = Provider<Principal?>((ref) {
  final state = ref.watch(authControllerProvider);
  return state is AuthAuthenticated ? state.session.principal : null;
});

final userProfileProvider = FutureProvider.autoDispose<UserProfile>((ref) {
  ref.watch(principalProvider);
  return ref.watch(authRepositoryProvider).profile();
});
