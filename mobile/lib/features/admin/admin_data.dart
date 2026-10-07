import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';

/// What the Organization Admin's mobile view reads (ADR-0062). Every call is an endpoint the web
/// dashboard already uses; the server scopes each to the caller's own organization and checks
/// the Org Admin's existing permission. Nothing here writes.

class AdminVehicle {
  final String id;
  final String plateNo;
  final String? label;
  final String status;
  const AdminVehicle(
      {required this.id,
      required this.plateNo,
      required this.label,
      required this.status});

  String get displayName =>
      label == null || label!.isEmpty ? plateNo : '$label · $plateNo';

  factory AdminVehicle.fromJson(Map<String, dynamic> json) => AdminVehicle(
        id: json['id'] as String,
        plateNo: json['plate_no'] as String? ?? '',
        label: json['label'] as String?,
        status: json['status'] as String? ?? '',
      );
}

class BoardTrip {
  final String id;
  final String tripType;
  final String? routeName;
  final String? plannedDeparture;
  final String? driverName;
  final String status;
  final String? cancelledReason;

  /// Why nobody can drive this trip (`driver_inactive`, `driver_unavailable`,
  /// `driver_not_compliant`), or null when it is covered.
  final String? uncoveredReason;

  const BoardTrip({
    required this.id,
    required this.tripType,
    required this.routeName,
    required this.plannedDeparture,
    required this.driverName,
    required this.status,
    required this.cancelledReason,
    required this.uncoveredReason,
  });

  factory BoardTrip.fromJson(Map<String, dynamic> json) => BoardTrip(
        id: json['id'] as String,
        tripType: json['trip_type'] as String? ?? '',
        routeName: json['route_name'] as String?,
        plannedDeparture: json['planned_departure'] as String?,
        driverName: json['driver_name'] as String?,
        status: json['status'] as String? ?? '',
        cancelledReason: json['cancelled_reason'] as String?,
        uncoveredReason: json['uncovered_reason'] as String?,
      );
}

class BoardCrewMember {
  final String name;
  final String? roleName;
  final bool isSubstitute;
  final bool isUnavailable;
  const BoardCrewMember({
    required this.name,
    required this.roleName,
    required this.isSubstitute,
    required this.isUnavailable,
  });

  factory BoardCrewMember.fromJson(Map<String, dynamic> json) =>
      BoardCrewMember(
        name: json['staff_name'] as String? ?? '',
        roleName: json['role_name'] as String?,
        isSubstitute: json['is_substitute'] as bool? ?? false,
        isUnavailable: json['is_unavailable'] as bool? ?? false,
      );
}

class BoardVehicle {
  final String vehicleId;
  final List<BoardTrip> trips;
  final List<BoardCrewMember> crew;
  const BoardVehicle(
      {required this.vehicleId, required this.trips, required this.crew});

  factory BoardVehicle.fromJson(Map<String, dynamic> json) => BoardVehicle(
        vehicleId: json['vehicle_id'] as String,
        trips: _list(json['trips']).map(BoardTrip.fromJson).toList(),
        crew: _list(json['crew']).map(BoardCrewMember.fromJson).toList(),
      );
}

class DailyBoard {
  final List<String> closures;
  final List<BoardVehicle> vehicles;
  final int uncoveredTrips;
  const DailyBoard(
      {required this.closures,
      required this.vehicles,
      required this.uncoveredTrips});

  int get tripCount => vehicles.fold(0, (sum, v) => sum + v.trips.length);

  factory DailyBoard.fromJson(Map<String, dynamic> json) => DailyBoard(
        closures: (json['closures'] as List<dynamic>? ?? const [])
            .map((e) => '$e')
            .toList(),
        vehicles: _list(json['vehicles']).map(BoardVehicle.fromJson).toList(),
        uncoveredTrips: json['uncovered_trips'] as int? ?? 0,
      );
}

class SafetyAlert {
  final String id;
  final String vehicleId;
  final String alarmType;
  final bool isCritical;
  final String status;
  final DateTime? lastRaisedAt;
  final bool isLate;
  final int occurrences;
  const SafetyAlert({
    required this.id,
    required this.vehicleId,
    required this.alarmType,
    required this.isCritical,
    required this.status,
    required this.lastRaisedAt,
    required this.isLate,
    required this.occurrences,
  });

  factory SafetyAlert.fromJson(Map<String, dynamic> json) => SafetyAlert(
        id: json['id'] as String,
        vehicleId: json['vehicle_id'] as String? ?? '',
        alarmType: json['alarm_type'] as String? ?? '',
        isCritical: json['is_critical'] as bool? ?? false,
        status: json['status'] as String? ?? '',
        lastRaisedAt: parseServerTime(json['last_raised_at']),
        isLate: json['is_late'] as bool? ?? false,
        occurrences: json['occurrences'] as int? ?? 1,
      );
}

class OnlineVehicle {
  final String vehicleId;
  final String plateNo;
  final String? label;
  const OnlineVehicle(
      {required this.vehicleId, required this.plateNo, required this.label});

  String get displayName =>
      label == null || label!.isEmpty ? plateNo : '$label · $plateNo';

  factory OnlineVehicle.fromJson(Map<String, dynamic> json) => OnlineVehicle(
        vehicleId: json['vehicle_id'] as String,
        plateNo: json['plate_no'] as String? ?? '',
        label: json['label'] as String?,
      );
}

class FleetOnline {
  final List<OnlineVehicle> vehicles;

  /// Every bus whose terminal is connected now, including any beyond the list's cap.
  final int totalOnline;
  const FleetOnline({required this.vehicles, required this.totalOnline});

  factory FleetOnline.fromJson(Map<String, dynamic> json) => FleetOnline(
        vehicles: _list(json['vehicles']).map(OnlineVehicle.fromJson).toList(),
        totalOnline: json['total_online'] as int? ?? 0,
      );
}

/// The numbers on the overview. A figure that could not be read is null and is shown as a
/// dash, never as zero.
class AdminOverview {
  final int? vehicles;
  final int? onlineNow;
  final int? tripsInProgress;
  final int? students;
  final int? drivers;
  final int? routes;
  const AdminOverview({
    required this.vehicles,
    required this.onlineNow,
    required this.tripsInProgress,
    required this.students,
    required this.drivers,
    required this.routes,
  });
}

List<Map<String, dynamic>> _list(Object? value) =>
    (value as List<dynamic>? ?? const []).cast<Map<String, dynamic>>();

class AdminRepository {
  final ApiClient _client;
  const AdminRepository(this._client);

  /// The total of a paginated list, read the way the web dashboard reads it: one row asked
  /// for, the count taken from the page envelope.
  Future<int> count(String resource, {String? status}) async {
    final filter = status == null ? '' : '&filter[status]=$status';
    final json = await _client.get('/$resource?page=1&page_size=1$filter');
    return (json['page'] as Map<String, dynamic>?)?['total'] as int? ?? 0;
  }

  Future<FleetOnline> fleetOnline() async =>
      FleetOnline.fromJson(await _client.get('/tracking/vehicles/online'));

  /// The first figure is read on its own: if the server refuses it (signed out, offline, the
  /// organization's subscription has lapsed) the whole overview shows that reason. After that,
  /// one figure failing leaves a dash in its place and the rest still show.
  Future<AdminOverview> overview() async {
    Future<int?> safe(Future<int> request) async {
      try {
        return await request;
      } catch (_) {
        return null;
      }
    }

    final vehicles = await count('vehicles');
    final results = await Future.wait([
      safe(fleetOnline().then((f) => f.totalOnline)),
      safe(count('trips', status: 'in_progress')),
      safe(count('students')),
      safe(count('drivers')),
      safe(count('routes')),
    ]);
    return AdminOverview(
      vehicles: vehicles,
      onlineNow: results[0],
      tripsInProgress: results[1],
      students: results[2],
      drivers: results[3],
      routes: results[4],
    );
  }

  Future<List<AdminVehicle>> vehicles() async {
    final json = await _client.get('/vehicles?page=1&page_size=100');
    return _list(json['data']).map(AdminVehicle.fromJson).toList();
  }

  Future<DailyBoard> dailyBoard(DateTime day) async => DailyBoard.fromJson(
      await _client.get('/daily-operations?date=${isoDate(day)}'));

  /// Alerts still needing attention: open and acknowledged.
  Future<List<SafetyAlert>> activeAlerts() async {
    return (await _client
            .getList('/safety-alerts?status=open&status=acknowledged'))
        .map(SafetyAlert.fromJson)
        .toList();
  }
}

final adminRepositoryProvider = Provider<AdminRepository>(
    (ref) => AdminRepository(ref.watch(apiClientProvider)));

final adminOverviewProvider = FutureProvider.autoDispose<AdminOverview>(
    (ref) => ref.watch(adminRepositoryProvider).overview());

final adminBoardProvider = FutureProvider.autoDispose<DailyBoard>(
    (ref) => ref.watch(adminRepositoryProvider).dailyBoard(DateTime.now()));

final adminAlertsProvider = FutureProvider.autoDispose<List<SafetyAlert>>(
    (ref) => ref.watch(adminRepositoryProvider).activeAlerts());

/// Bus names by id, so a board row or an alert shows "Bus A · plate" instead of an id.
final adminVehicleNamesProvider =
    FutureProvider.autoDispose<Map<String, String>>((ref) async {
  final vehicles = await ref.watch(adminRepositoryProvider).vehicles();
  return {for (final v in vehicles) v.id: v.displayName};
});

final adminFleetOnlineProvider = FutureProvider.autoDispose<FleetOnline>(
    (ref) => ref.watch(adminRepositoryProvider).fleetOnline());
