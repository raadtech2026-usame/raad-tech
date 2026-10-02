import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Background push delivery (ADR-0061 §8).
///
/// RAAD's backend stores device tokens (`POST /notifications/tokens`) but has no sender, and
/// no Firebase project exists, so the only implementation today does nothing. Notifications
/// reach the app over `/ws/notifications` while it is open. A Firebase implementation
/// replaces [NoPushService] in [pushServiceProvider]; no screen needs to change.
abstract class PushService {
  /// Called after sign-in: obtain a device token and register it with the backend.
  Future<void> register();

  /// Called before sign-out: revoke this device's token.
  Future<void> unregister();
}

class NoPushService implements PushService {
  const NoPushService();

  @override
  Future<void> register() async {}

  @override
  Future<void> unregister() async {}
}

final pushServiceProvider =
    Provider<PushService>((ref) => const NoPushService());
