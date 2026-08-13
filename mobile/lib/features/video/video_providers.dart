import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state.dart';
import '../../core/auth/me_identity.dart';
import '../../core/auth/me_repository.dart';
import 'video_repository.dart';

final videoRepositoryProvider = Provider<VideoRepository>((ref) {
  return VideoRepository(ref.watch(apiClientProvider));
});

final meRepositoryProvider = Provider<MeRepository>((ref) {
  return MeRepository(ref.watch(apiClientProvider));
});

/// `GET /me`, re-fetched on every read (`FutureProvider`, not cached across the whole app
/// session) — ADR-0026 §5's own flags can change at any time (an org_admin revoking access
/// mid-session), and this is presentation only anyway (the real gate is server-side), so a
/// short-lived, per-screen-visit fetch is correct, not a missed-caching optimization.
final myIdentityProvider = FutureProvider<MeIdentity>((ref) async {
  return ref.watch(meRepositoryProvider).getMyIdentity();
});
