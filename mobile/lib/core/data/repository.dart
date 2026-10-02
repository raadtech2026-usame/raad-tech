import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_state.dart';
import '../network/api_client.dart';
import '../network/realtime_clients.dart';
import '../util/format.dart';
import 'models.dart';

/// Every call the Parent and Driver screens make. All of them are self-scoped on the server:
/// none sends an id that says who the caller is.
class RaadRepository {
  final ApiClient _client;
  const RaadRepository(this._client);

  // ---- parent
  Future<List<ChildTransport>> myTransport() async {
    return (await _client.getList('/me/transport'))
        .map(ChildTransport.fromJson)
        .toList();
  }

  /// Latest known position of a bus the caller may see. The server answers 403/404 unless the
  /// caller's child rides it and it is on a trip; `null` means "no position yet".
  Future<TrackingPosition?> latestPosition(String vehicleId) async {
    final json = await _client.get('/tracking/vehicles/$vehicleId/latest');
    return json.isEmpty ? null : TrackingPosition.fromJson(json);
  }

  // ---- trips (both roles)
  Future<List<Trip>> myTrips(
      {required DateTime from, required DateTime to}) async {
    final path = '/me/trips?from=${isoDate(from)}&to=${isoDate(to)}';
    return (await _client.getList(path)).map(Trip.fromJson).toList();
  }

  // ---- driver
  Future<TripDetail> myTrip(String tripId) async {
    return TripDetail.fromJson(await _client.get('/me/trips/$tripId'));
  }

  Future<void> startTrip(String tripId) => _client.post('/trips/$tripId/start');

  Future<void> endTrip(String tripId) => _client.post('/trips/$tripId/end');

  Future<List<BusCrew>> myCrew() async {
    return (await _client.getList('/me/crew')).map(BusCrew.fromJson).toList();
  }

  Future<MyDocuments> myDocuments() async {
    return MyDocuments.fromJson(await _client.get('/me/documents'));
  }

  Future<List<Unavailability>> myUnavailability() async {
    return (await _client.getList('/me/unavailability'))
        .map(Unavailability.fromJson)
        .toList();
  }

  Future<void> reportUnavailability({
    required DateTime startsOn,
    required DateTime endsOn,
    required String reason,
    String? note,
  }) {
    return _client.post('/me/unavailability', body: {
      'starts_on': isoDate(startsOn),
      'ends_on': isoDate(endsOn),
      'reason': reason,
      if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
    });
  }

  Future<void> withdrawUnavailability(String id) =>
      _client.delete('/me/unavailability/$id');

  Future<List<IncidentReport>> myIncidents() async {
    return (await _client.getList('/me/incidents'))
        .map(IncidentReport.fromJson)
        .toList();
  }

  Future<void> reportIncident({
    required String category,
    required String severity,
    required String title,
    String? description,
    String? tripId,
  }) {
    return _client.post('/me/incidents', body: {
      'category': category,
      'severity': severity,
      'title': title.trim(),
      if (description != null && description.trim().isNotEmpty)
        'description': description.trim(),
      if (tripId != null) 'trip_id': tripId,
    });
  }

  // ---- notifications (both roles; the server returns only the caller's own)
  Future<List<AppNotification>> notifications() async {
    final json = await _client.get('/notifications?limit=50');
    return [
      for (final item in (json['data'] as List? ?? const []))
        if (item is Map<String, dynamic>) AppNotification.fromJson(item),
    ];
  }

  Future<void> markRead(String id) => _client.post('/notifications/$id/read');
}

final repositoryProvider = Provider<RaadRepository>((ref) {
  return RaadRepository(ref.watch(apiClientProvider));
});

// ---- parent state

final myTransportProvider =
    FutureProvider.autoDispose<List<ChildTransport>>((ref) {
  ref.watch(principalProvider);
  return ref.watch(repositoryProvider).myTransport();
});

/// The child whose transport the Parent home shows. Null means "the first one".
final selectedChildProvider = StateProvider<String?>((ref) => null);

/// Trips of the parent's children: 30 days back to 7 days ahead.
final parentTripsProvider = FutureProvider.autoDispose<List<Trip>>((ref) {
  ref.watch(principalProvider);
  final today = dateOnly(DateTime.now());
  return ref.watch(repositoryProvider).myTrips(
        from: today.subtract(const Duration(days: 30)),
        to: today.add(const Duration(days: 7)),
      );
});

// ---- driver state

/// The driver's trips: 30 days back to 14 days ahead.
final driverTripsProvider = FutureProvider.autoDispose<List<Trip>>((ref) {
  ref.watch(principalProvider);
  final today = dateOnly(DateTime.now());
  return ref.watch(repositoryProvider).myTrips(
        from: today.subtract(const Duration(days: 30)),
        to: today.add(const Duration(days: 14)),
      );
});

final tripDetailProvider =
    FutureProvider.autoDispose.family<TripDetail, String>((ref, id) {
  return ref.watch(repositoryProvider).myTrip(id);
});

final myCrewProvider = FutureProvider.autoDispose<List<BusCrew>>((ref) {
  return ref.watch(repositoryProvider).myCrew();
});

final myDocumentsProvider = FutureProvider.autoDispose<MyDocuments>((ref) {
  return ref.watch(repositoryProvider).myDocuments();
});

final myUnavailabilityProvider =
    FutureProvider.autoDispose<List<Unavailability>>((ref) {
  return ref.watch(repositoryProvider).myUnavailability();
});

final myIncidentsProvider =
    FutureProvider.autoDispose<List<IncidentReport>>((ref) {
  return ref.watch(repositoryProvider).myIncidents();
});

// ---- notifications

final notificationsProvider = FutureProvider<List<AppNotification>>((ref) {
  ref.watch(principalProvider);
  return ref.watch(repositoryProvider).notifications();
});

final unreadCountProvider = Provider<int>((ref) {
  final list =
      ref.watch(notificationsProvider).valueOrNull ?? const <AppNotification>[];
  return list.where((n) => !n.isRead).length;
});

/// Keeps `/ws/notifications` open while someone is signed in and re-reads the list when the
/// server signals a new notification. Watch it from the signed-in shell.
final notificationsLiveProvider = Provider.autoDispose<void>((ref) {
  final token = ref.watch(apiClientProvider).accessToken;
  if (ref.watch(principalProvider) == null || token == null) return;
  final socket = NotificationsSocket()..connect(token);
  final subscription =
      socket.arrivals.listen((_) => ref.invalidate(notificationsProvider));
  ref.onDispose(() {
    subscription.cancel();
    socket.dispose();
  });
});
