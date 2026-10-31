import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';

/// Data models and API repository for the Organization Admin's mobile view.
/// Supports full management parity: Users (Drivers, Parents, Students),
/// Fleet (Vehicles, Device Linking, Tracking), and Dispatch (Trips, Routes).

class AdminVehicle {
  final String id;
  final String plateNo;
  final String? label;
  final String status;
  final int? capacity;
  final String? deviceId;
  final String? terminalId;
  final bool isOnline;

  const AdminVehicle({
    required this.id,
    required this.plateNo,
    required this.label,
    required this.status,
    this.capacity,
    this.deviceId,
    this.terminalId,
    this.isOnline = false,
  });

  String get displayName =>
      label == null || label!.isEmpty ? plateNo : '$label · $plateNo';

  bool get isActive => status == 'active';
  bool get isMaintenance => status == 'maintenance';

  factory AdminVehicle.fromJson(Map<String, dynamic> json) => AdminVehicle(
        id: json['id'] as String,
        plateNo: json['plate_no'] as String? ?? '',
        label: json['label'] as String?,
        status: json['status'] as String? ?? 'active',
        capacity: json['capacity'] as int?,
        deviceId: json['device_id'] as String?,
        terminalId: json['terminal_id'] as String?,
        isOnline: json['is_online'] as bool? ?? false,
      );
}

class AdminDriver {
  final String id;
  final String fullName;
  final String phone;
  final String? email;
  final String? licenseNo;
  final String status;

  const AdminDriver({
    required this.id,
    required this.fullName,
    required this.phone,
    this.email,
    this.licenseNo,
    required this.status,
  });

  bool get isActive => status == 'active';

  factory AdminDriver.fromJson(Map<String, dynamic> json) => AdminDriver(
        id: json['id'] as String,
        fullName: json['full_name'] as String? ?? '',
        phone: json['phone'] as String? ?? '',
        email: json['email'] as String?,
        licenseNo: json['license_no'] as String?,
        status: json['status'] as String? ?? 'active',
      );
}

class AdminParent {
  final String id;
  final String fullName;
  final String phone;
  final String? email;
  final String? address;

  const AdminParent({
    required this.id,
    required this.fullName,
    required this.phone,
    this.email,
    this.address,
  });

  factory AdminParent.fromJson(Map<String, dynamic> json) => AdminParent(
        id: json['id'] as String,
        fullName: json['full_name'] as String? ?? '',
        phone: json['phone'] as String? ?? '',
        email: json['email'] as String?,
        address: json['address'] as String?,
      );
}

class AdminStudent {
  final String id;
  final String fullName;
  final String? externalRef;
  final String? gender;
  final String status;

  const AdminStudent({
    required this.id,
    required this.fullName,
    this.externalRef,
    this.gender,
    required this.status,
  });

  bool get isActive => status == 'active';

  factory AdminStudent.fromJson(Map<String, dynamic> json) => AdminStudent(
        id: json['id'] as String,
        fullName: json['full_name'] as String? ?? '',
        externalRef: json['external_ref'] as String?,
        gender: json['gender'] as String?,
        status: json['status'] as String? ?? 'active',
      );
}

class AdminDevice {
  final String id;
  final String terminalId;
  final String? model;
  final String status;
  final String? vehicleId;

  const AdminDevice({
    required this.id,
    required this.terminalId,
    this.model,
    required this.status,
    this.vehicleId,
  });

  factory AdminDevice.fromJson(Map<String, dynamic> json) => AdminDevice(
        id: json['id'] as String,
        terminalId: json['terminal_id'] as String? ?? '',
        model: json['model'] as String?,
        status: json['status'] as String? ?? '',
        vehicleId: json['vehicle_id'] as String?,
      );
}

class AdminRoute {
  final String id;
  final String name;
  final String? code;
  final int stopCount;
  final String status;

  const AdminRoute({
    required this.id,
    required this.name,
    this.code,
    required this.stopCount,
    required this.status,
  });

  factory AdminRoute.fromJson(Map<String, dynamic> json) => AdminRoute(
        id: json['id'] as String,
        name: json['name'] as String? ?? '',
        code: json['code'] as String?,
        stopCount: (json['stops'] as List<dynamic>? ?? const []).length,
        status: json['status'] as String? ?? 'active',
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

  const BoardVehicle({
    required this.vehicleId,
    required this.trips,
    required this.crew,
  });

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

  const DailyBoard({
    required this.closures,
    required this.vehicles,
    required this.uncoveredTrips,
  });

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

  const OnlineVehicle({
    required this.vehicleId,
    required this.plateNo,
    required this.label,
  });

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
  final int totalOnline;

  const FleetOnline({required this.vehicles, required this.totalOnline});

  factory FleetOnline.fromJson(Map<String, dynamic> json) => FleetOnline(
        vehicles: _list(json['vehicles']).map(OnlineVehicle.fromJson).toList(),
        totalOnline: json['total_online'] as int? ?? 0,
      );
}

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
  final String orgId;

  const AdminRepository(this._client, {this.orgId = ''});

  Future<int> count(String resource, {String? status}) async {
    final filter = status == null ? '' : '&filter[status]=$status';
    final json = await _client.get('/$resource?page=1&page_size=1$filter');
    return (json['page'] as Map<String, dynamic>?)?['total'] as int? ?? 0;
  }

  Future<FleetOnline> fleetOnline() async =>
      FleetOnline.fromJson(await _client.get('/tracking/vehicles/online'));

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

  // --- Users & Roles --------------------------------------------------------

  Future<List<AdminDriver>> drivers() async {
    final json = await _client.get('/drivers?page=1&page_size=100');
    return _list(json['data']).map(AdminDriver.fromJson).toList();
  }

  Future<Map<String, dynamic>> createDriver({
    required String fullName,
    required String phone,
    String? email,
    String? licenseNo,
  }) async {
    final body = {
      'organization_id': orgId,
      'full_name': fullName,
      'phone': phone,
      if (email != null && email.isNotEmpty) 'email': email,
      if (licenseNo != null && licenseNo.isNotEmpty) 'license_no': licenseNo,
    };
    return await _client.post('/drivers', body: body);
  }

  Future<void> updateDriverStatus(String id, String status) async {
    await _client.patch('/drivers/$id', body: {'status': status});
  }

  Future<List<AdminParent>> parents() async {
    final json = await _client.get('/parents?page=1&page_size=100');
    return _list(json['data']).map(AdminParent.fromJson).toList();
  }

  Future<Map<String, dynamic>> createParent({
    required String fullName,
    required String phone,
    String? email,
  }) async {
    final body = {
      'organization_id': orgId,
      'full_name': fullName,
      'phone': phone,
      if (email != null && email.isNotEmpty) 'email': email,
    };
    return await _client.post('/parents', body: body);
  }

  Future<List<AdminStudent>> students() async {
    final json = await _client.get('/students?page=1&page_size=100');
    return _list(json['data']).map(AdminStudent.fromJson).toList();
  }

  Future<void> enrollStudent({
    required String fullName,
    String? externalRef,
    String? gender,
  }) async {
    final body = {
      'organization_id': orgId,
      'full_name': fullName,
      if (externalRef != null && externalRef.isNotEmpty)
        'external_ref': externalRef,
      if (gender != null && gender.isNotEmpty) 'gender': gender,
    };
    await _client.post('/students', body: body);
  }

  Future<void> updateStudentStatus(String id, String status) async {
    await _client.post('/students/$id/status', body: {'status': status});
  }

  // --- Fleet & Vehicles -----------------------------------------------------

  Future<List<AdminVehicle>> vehicles() async {
    final json = await _client.get('/vehicles?page=1&page_size=100');
    return _list(json['data']).map(AdminVehicle.fromJson).toList();
  }

  Future<void> createVehicle({
    required String plateNo,
    String? label,
    int? capacity,
  }) async {
    final body = {
      'organization_id': orgId,
      'plate_no': plateNo,
      if (label != null && label.isNotEmpty) 'label': label,
      if (capacity != null) 'capacity': capacity,
    };
    await _client.post('/vehicles', body: body);
  }

  Future<void> updateVehicleStatus(String id, String status) async {
    await _client.patch('/vehicles/$id', body: {'status': status});
  }

  Future<List<AdminDevice>> devices() async {
    final json = await _client.get('/devices?page=1&page_size=100');
    return _list(json['data']).map(AdminDevice.fromJson).toList();
  }

  Future<void> assignDevice(String deviceId, String vehicleId) async {
    await _client.post(
      '/devices/$deviceId/assign',
      body: {'vehicle_id': vehicleId},
    );
  }

  // --- Trips & Dispatch -----------------------------------------------------

  Future<DailyBoard> dailyBoard(DateTime day) async => DailyBoard.fromJson(
      await _client.get('/daily-operations?date=${isoDate(day)}'));

  Future<List<AdminRoute>> routes() async {
    final json = await _client.get('/routes?page=1&page_size=100');
    return _list(json['data']).map(AdminRoute.fromJson).toList();
  }

  Future<List<BoardTrip>> trips() async {
    final json = await _client.get('/trips?page=1&page_size=100');
    return _list(json['data']).map(BoardTrip.fromJson).toList();
  }

  Future<List<SafetyAlert>> activeAlerts() async {
    return (await _client
            .getList('/safety-alerts?status=open&status=acknowledged'))
        .map(SafetyAlert.fromJson)
        .toList();
  }
}

final adminRepositoryProvider = Provider<AdminRepository>((ref) {
  final client = ref.watch(apiClientProvider);
  final authState = ref.watch(authControllerProvider);
  final orgId = authState is AuthAuthenticated
      ? (authState.session.principal.organizationId ?? '')
      : '';
  return AdminRepository(client, orgId: orgId);
});

final adminOverviewProvider = FutureProvider.autoDispose<AdminOverview>(
    (ref) => ref.watch(adminRepositoryProvider).overview());

final adminBoardProvider = FutureProvider.autoDispose<DailyBoard>(
    (ref) => ref.watch(adminRepositoryProvider).dailyBoard(DateTime.now()));

final adminAlertsProvider = FutureProvider.autoDispose<List<SafetyAlert>>(
    (ref) => ref.watch(adminRepositoryProvider).activeAlerts());

final adminFleetOnlineProvider = FutureProvider.autoDispose<FleetOnline>(
    (ref) => ref.watch(adminRepositoryProvider).fleetOnline());

final adminDriversProvider = FutureProvider.autoDispose<List<AdminDriver>>(
    (ref) => ref.watch(adminRepositoryProvider).drivers());

final adminParentsProvider = FutureProvider.autoDispose<List<AdminParent>>(
    (ref) => ref.watch(adminRepositoryProvider).parents());

final adminStudentsProvider = FutureProvider.autoDispose<List<AdminStudent>>(
    (ref) => ref.watch(adminRepositoryProvider).students());

final adminVehiclesListProvider = FutureProvider.autoDispose<List<AdminVehicle>>(
    (ref) => ref.watch(adminRepositoryProvider).vehicles());

final adminDevicesProvider = FutureProvider.autoDispose<List<AdminDevice>>(
    (ref) => ref.watch(adminRepositoryProvider).devices());

final adminRoutesProvider = FutureProvider.autoDispose<List<AdminRoute>>(
    (ref) => ref.watch(adminRepositoryProvider).routes());

final adminTripsProvider = FutureProvider.autoDispose<List<BoardTrip>>(
    (ref) => ref.watch(adminRepositoryProvider).trips());

final adminVehicleNamesProvider =
    FutureProvider.autoDispose<Map<String, String>>((ref) async {
  final vehicles = await ref.watch(adminRepositoryProvider).vehicles();
  return {for (final v in vehicles) v.id: v.displayName};
});
