import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:raad_mobile/core/auth/auth_repository.dart';
import 'package:raad_mobile/core/auth/auth_state.dart';
import 'package:raad_mobile/core/auth/me_identity.dart';
import 'package:raad_mobile/core/auth/principal.dart';
import 'package:raad_mobile/core/data/models.dart';
import 'package:raad_mobile/core/data/repository.dart';
import 'package:raad_mobile/core/l10n/strings.dart';
import 'package:raad_mobile/core/network/api_client.dart';
import 'package:raad_mobile/core/network/api_exception.dart';
import 'package:raad_mobile/features/video/video_providers.dart';

/// A repository that answers from memory and records what the screens asked it to do.
class FakeRepository extends RaadRepository {
  FakeRepository() : super(ApiClient());

  List<ChildTransport> children = [];
  List<Trip> trips = [];
  List<AppNotification> notificationList = [];
  List<Unavailability> unavailability = [];
  List<IncidentReport> incidents = [];
  Object? failWith;
  final started = <String>[];
  final ended = <String>[];
  final markedRead = <String>[];
  final reportedIncidents = <Map<String, Object?>>[];

  Future<T> _answer<T>(T value) async {
    if (failWith != null) throw failWith!;
    return value;
  }

  @override
  Future<List<ChildTransport>> myTransport() => _answer(children);

  @override
  Future<List<Trip>> myTrips({required DateTime from, required DateTime to}) =>
      _answer(trips);

  @override
  Future<List<AppNotification>> notifications() => _answer(notificationList);

  @override
  Future<void> markRead(String id) async => markedRead.add(id);

  @override
  Future<void> startTrip(String tripId) async {
    if (failWith != null) throw failWith!;
    started.add(tripId);
  }

  @override
  Future<void> endTrip(String tripId) async {
    if (failWith != null) throw failWith!;
    ended.add(tripId);
  }

  @override
  Future<List<Unavailability>> myUnavailability() => _answer(unavailability);

  @override
  Future<List<IncidentReport>> myIncidents() => _answer(incidents);

  @override
  Future<void> reportIncident({
    required String category,
    required String severity,
    required String title,
    String? description,
    String? tripId,
  }) async {
    if (failWith != null) throw failWith!;
    reportedIncidents
        .add({'category': category, 'severity': severity, 'title': title});
  }
}

class _FakeAuthRepository extends AuthRepository {
  _FakeAuthRepository() : super(ApiClient());

  @override
  Future<UserProfile> profile() async {
    return const UserProfile(
        fullName: 'Test Person',
        email: null,
        phone: '+252610000000',
        role: 'parent');
  }
}

const offline = ApiException.network();

/// Pumps [home] signed in as [role], in English unless [somali], on top of [repository].
Widget testApp(
  Widget home, {
  required FakeRepository repository,
  String role = 'parent',
  bool somali = false,
  bool videoAccess = false,
}) {
  return ProviderScope(
    overrides: [
      repositoryProvider.overrideWithValue(repository),
      authRepositoryProvider.overrideWithValue(_FakeAuthRepository()),
      languageProvider.overrideWith((ref) => somali ? 'so' : 'en'),
      principalProvider.overrideWithValue(
        Principal(userId: 'user-1', role: role, organizationId: 'org-1'),
      ),
      myIdentityProvider.overrideWith(
        (ref) async => MeIdentity(
          userId: 'user-1',
          role: role,
          organizationId: 'org-1',
          parentId: null,
          driverId: null,
          hasVideoLiveAccess: videoAccess,
          hasVideoPlaybackAccess: false,
        ),
      ),
    ],
    child: MaterialApp(home: home),
  );
}

DateTime get today {
  final now = DateTime.now();
  return DateTime(now.year, now.month, now.day);
}

Trip trip({
  String id = 'trip-1',
  String status = 'scheduled',
  String type = 'morning',
  DateTime? day,
  String? cancelledReason,
  bool isCover = false,
  List<String> students = const ['s1'],
}) {
  return Trip(
    id: id,
    tripType: type,
    status: status,
    scheduledDate: day ?? today,
    plannedDeparture: '06:30:00',
    cancelledReason: cancelledReason,
    routeId: 'route-1',
    routeName: 'North',
    vehicle: const Vehicle(id: 'veh-1', plateNo: 'AB-1234', label: 'Bus 1'),
    isCover: isCover,
    studentIds: students,
  );
}

ChildTransport child({
  String id = 's1',
  String name = 'Amina',
  bool assigned = true,
  bool onTrip = false,
}) {
  return ChildTransport(
    studentId: id,
    fullName: name,
    status: 'active',
    hasAssignment: assigned,
    routeName: assigned ? 'North' : null,
    pickupStop: assigned
        ? const Stop(
            id: 'stop-1', name: 'Bakaaraha', latitude: 2.04, longitude: 45.31)
        : null,
    dropoffStop: assigned
        ? const Stop(
            id: 'stop-9', name: 'School gate', latitude: 2.05, longitude: 45.33)
        : null,
    vehicle: assigned
        ? const Vehicle(id: 'veh-1', plateNo: 'AB-1234', label: 'Bus 1')
        : null,
    currentTripId: onTrip ? 'trip-1' : null,
    currentTripType: onTrip ? 'morning' : null,
  );
}
