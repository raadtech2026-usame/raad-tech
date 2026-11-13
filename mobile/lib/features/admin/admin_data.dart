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

class DeviceCamera {
  final String id;
  final int channelNo;
  final String? position;
  final String? label;
  final String? videoSignal;

  const DeviceCamera({
    required this.id,
    required this.channelNo,
    this.position,
    this.label,
    this.videoSignal,
  });

  factory DeviceCamera.fromJson(Map<String, dynamic> json) => DeviceCamera(
    id: json['id'] as String,
    channelNo: json['channel_no'] as int? ?? 1,
    position: json['position'] as String?,
    label: json['label'] as String?,
    videoSignal: json['video_signal'] as String?,
  );
}

class AdminDevice {
  final String id;
  final String terminalId;
  final String? model;
  final String status;
  final String? vehicleId;
  final bool isOnline;
  final List<DeviceCamera> cameras;

  const AdminDevice({
    required this.id,
    required this.terminalId,
    this.model,
    required this.status,
    this.vehicleId,
    this.isOnline = false,
    this.cameras = const [],
  });

  factory AdminDevice.fromJson(Map<String, dynamic> json) => AdminDevice(
    id: json['id'] as String,
    terminalId: json['terminal_id'] as String? ?? '',
    model: json['model'] as String?,
    status: json['status'] as String? ?? '',
    vehicleId: json['vehicle_id'] as String?,
    isOnline: json['is_online'] as bool? ?? false,
    cameras: (json['cameras'] as List<dynamic>? ?? const [])
        .map((c) => DeviceCamera.fromJson(c as Map<String, dynamic>))
        .toList(),
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

class OnlineVehiclePosition {
  final double latitude;
  final double longitude;
  final double? headingDeg;
  final double? speedKph;
  final DateTime? eventTime;

  const OnlineVehiclePosition({
    required this.latitude,
    required this.longitude,
    this.headingDeg,
    this.speedKph,
    this.eventTime,
  });

  factory OnlineVehiclePosition.fromJson(Map<String, dynamic> json) =>
      OnlineVehiclePosition(
        latitude: (json['latitude'] as num).toDouble(),
        longitude: (json['longitude'] as num).toDouble(),
        headingDeg: (json['heading_deg'] as num?)?.toDouble(),
        speedKph: (json['speed_kph'] as num?)?.toDouble(),
        eventTime: parseServerTime(json['event_time']),
      );
}

class OnlineVehicle {
  final String vehicleId;
  final String plateNo;
  final String? label;
  final String? deviceId;
  final bool isOnline;
  final OnlineVehiclePosition? position;

  const OnlineVehicle({
    required this.vehicleId,
    required this.plateNo,
    required this.label,
    this.deviceId,
    this.isOnline = true,
    this.position,
  });

  String get displayName =>
      label == null || label!.isEmpty ? plateNo : '$label · $plateNo';

  factory OnlineVehicle.fromJson(Map<String, dynamic> json) => OnlineVehicle(
    vehicleId: json['vehicle_id'] as String,
    plateNo: json['plate_no'] as String? ?? '',
    label: json['label'] as String?,
    deviceId: json['device_id'] as String?,
    isOnline: json['is_online'] as bool? ?? true,
    position: json['position'] != null
        ? OnlineVehiclePosition.fromJson(json['position'] as Map<String, dynamic>)
        : null,
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

class AdminFinanceSummary {
  final String billedAmount;
  final String collectedAmount;
  final String outstandingAmount;
  final int invoiceCount;
  final int paidInvoiceCount;
  final int overdueInvoiceCount;
  final String currency;

  const AdminFinanceSummary({
    required this.billedAmount,
    required this.collectedAmount,
    required this.outstandingAmount,
    required this.invoiceCount,
    required this.paidInvoiceCount,
    required this.overdueInvoiceCount,
    required this.currency,
  });

  factory AdminFinanceSummary.fromJson(Map<String, dynamic> json) => AdminFinanceSummary(
    billedAmount: json['billed_amount'] as String? ?? '0.00',
    collectedAmount: json['collected_amount'] as String? ?? '0.00',
    outstandingAmount: json['outstanding_amount'] as String? ?? '0.00',
    invoiceCount: json['invoice_count'] as int? ?? 0,
    paidInvoiceCount: json['paid_invoice_count'] as int? ?? 0,
    overdueInvoiceCount: json['overdue_invoice_count'] as int? ?? 0,
    currency: json['currency'] as String? ?? 'USD',
  );
}

class AdminInvoice {
  final String id;
  final String studentId;
  final String? studentName;
  final String period;
  final String amount;
  final String amountPaid;
  final String balanceDue;
  final String currency;
  final String status;
  final String? dueDate;
  final String? notes;

  const AdminInvoice({
    required this.id,
    required this.studentId,
    this.studentName,
    required this.period,
    required this.amount,
    required this.amountPaid,
    required this.balanceDue,
    required this.currency,
    required this.status,
    this.dueDate,
    this.notes,
  });

  bool get isPaid => status == 'paid';
  bool get isOverdue => status == 'overdue';

  factory AdminInvoice.fromJson(Map<String, dynamic> json) => AdminInvoice(
    id: json['id'] as String,
    studentId: json['student_id'] as String? ?? '',
    studentName: json['student_name'] as String?,
    period: json['period'] as String? ?? '',
    amount: json['amount']?.toString() ?? '0.00',
    amountPaid: json['amount_paid']?.toString() ?? '0.00',
    balanceDue: json['balance_due']?.toString() ?? '0.00',
    currency: json['currency'] as String? ?? 'USD',
    status: json['status'] as String? ?? 'pending',
    dueDate: json['due_date'] as String?,
    notes: json['notes'] as String?,
  );
}

class AdminParentInvoiceLine {
  final String studentId;
  final String studentName;
  final String amount;
  final String amountPaid;
  final String balanceDue;
  final String? feePlanName;

  const AdminParentInvoiceLine({
    required this.studentId,
    required this.studentName,
    required this.amount,
    required this.amountPaid,
    required this.balanceDue,
    this.feePlanName,
  });

  factory AdminParentInvoiceLine.fromJson(Map<String, dynamic> json) =>
      AdminParentInvoiceLine(
        studentId: json['student_id'] as String? ?? '',
        studentName: json['student_name'] as String? ?? '',
        amount: json['amount']?.toString() ?? '0.00',
        amountPaid: json['amount_paid']?.toString() ?? '0.00',
        balanceDue: json['balance_due']?.toString() ?? '0.00',
        feePlanName: json['fee_plan_name'] as String?,
      );
}

class AdminParentInvoice {
  final String id;
  final String parentId;
  final String parentName;
  final String? parentPhone;
  final String invoiceNumber;
  final String period;
  final String currency;
  final String totalAmount;
  final String amountPaid;
  final String balanceDue;
  final String status;
  final int childrenCount;
  final String? dueDate;
  final DateTime? createdAt;
  final List<AdminParentInvoiceLine> lines;

  const AdminParentInvoice({
    required this.id,
    required this.parentId,
    required this.parentName,
    this.parentPhone,
    required this.invoiceNumber,
    required this.period,
    required this.currency,
    required this.totalAmount,
    required this.amountPaid,
    required this.balanceDue,
    required this.status,
    required this.childrenCount,
    this.dueDate,
    this.createdAt,
    this.lines = const [],
  });

  bool get isPaid => status == 'paid';
  bool get isPartiallyPaid =>
      status == 'partially_paid' ||
      status == 'partial' ||
      ((double.tryParse(amountPaid) ?? 0) > 0 &&
          (double.tryParse(balanceDue) ?? 0) > 0);
  bool get isUnpaid =>
      status == 'unpaid' ||
      (!isPaid &&
          !isPartiallyPaid &&
          (double.tryParse(balanceDue) ?? 0) > 0);
  bool get isOverdue => status == 'overdue';

  factory AdminParentInvoice.fromJson(Map<String, dynamic> json) =>
      AdminParentInvoice(
        id: json['id'] as String,
        parentId: json['parent_id'] as String? ?? '',
        parentName: json['parent_name'] as String? ?? '',
        parentPhone: json['parent_phone'] as String?,
        invoiceNumber: json['invoice_number'] as String? ?? '',
        period: json['period'] as String? ?? '',
        currency: json['currency'] as String? ?? 'USD',
        totalAmount: json['total_amount']?.toString() ??
            json['amount']?.toString() ??
            '0.00',
        amountPaid: json['amount_paid']?.toString() ?? '0.00',
        balanceDue: json['balance_due']?.toString() ?? '0.00',
        status: json['status'] as String? ?? 'pending',
        childrenCount: json['children_count'] as int? ??
            (json['lines'] as List<dynamic>? ?? const []).length,
        dueDate: json['due_date'] as String?,
        createdAt: parseServerTime(json['created_at']),
        lines: (json['lines'] as List<dynamic>? ?? const [])
            .map((l) =>
                AdminParentInvoiceLine.fromJson(l as Map<String, dynamic>))
            .toList(),
      );
}

class AdminTripItem {
  final String id;
  final String scheduledDate;
  final String tripType;
  final String? routeId;
  final String? routeName;
  final String? vehicleId;
  final String? vehiclePlate;
  final String? driverId;
  final String? driverName;
  final String status;
  final String? plannedDeparture;
  final String? cancelledReason;

  const AdminTripItem({
    required this.id,
    required this.scheduledDate,
    required this.tripType,
    this.routeId,
    this.routeName,
    this.vehicleId,
    this.vehiclePlate,
    this.driverId,
    this.driverName,
    required this.status,
    this.plannedDeparture,
    this.cancelledReason,
  });

  bool get isInProgress => status == 'in_progress';
  bool get isScheduled => status == 'scheduled';
  bool get isCompleted => status == 'completed';

  factory AdminTripItem.fromJson(Map<String, dynamic> json) => AdminTripItem(
    id: json['id'] as String,
    scheduledDate: json['scheduled_date'] as String? ?? '',
    tripType: json['trip_type'] as String? ?? '',
    routeId: json['route_id'] as String?,
    routeName: json['route_name'] as String?,
    vehicleId: json['vehicle_id'] as String?,
    vehiclePlate: json['vehicle_plate'] as String?,
    driverId: json['driver_id'] as String?,
    driverName: json['driver_name'] as String?,
    status: json['status'] as String? ?? '',
    plannedDeparture: json['planned_departure'] as String?,
    cancelledReason: json['cancelled_reason'] as String?,
  );
}

class AdminStaff {
  final String id;
  final String fullName;
  final String phone;
  final String role;
  final String? licenseNo;
  final String status;

  const AdminStaff({
    required this.id,
    required this.fullName,
    required this.phone,
    required this.role,
    this.licenseNo,
    required this.status,
  });

  bool get isActive => status == 'active';

  factory AdminStaff.fromJson(Map<String, dynamic> json) => AdminStaff(
    id: json['id'] as String,
    fullName: json['full_name'] as String? ?? '',
    phone: json['phone'] as String? ?? '',
    role: json['role'] as String? ?? 'driver',
    licenseNo: json['license_no'] as String?,
    status: json['status'] as String? ?? 'active',
  );
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

  Future<OnlineVehiclePosition?> getLatestVehiclePosition(String vehicleId) async {
    try {
      final json = await _client.get('/tracking/vehicles/$vehicleId/latest');
      return OnlineVehiclePosition.fromJson(json);
    } catch (_) {
      return null;
    }
  }

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

  Future<AdminDevice?> getVehicleActiveDevice(String vehicleId) async {
    try {
      final assignment =
          await _client.get('/vehicles/$vehicleId/device-assignment');
      final deviceId = assignment['device_id'] as String?;
      if (deviceId == null || deviceId.isEmpty) return null;
      final devJson = await _client.get('/devices/$deviceId');
      return AdminDevice.fromJson(devJson);
    } catch (_) {
      return null;
    }
  }

  Future<void> assignDevice(String deviceId, String vehicleId) async {
    await _client.post(
      '/devices/$deviceId/assign',
      body: {'vehicle_id': vehicleId},
    );
  }

  // --- Trips & Dispatch -----------------------------------------------------

  Future<DailyBoard> dailyBoard(DateTime day) async => DailyBoard.fromJson(
    await _client.get('/daily-operations?date=${isoDate(day)}'),
  );

  Future<List<AdminRoute>> routes() async {
    final json = await _client.get('/routes?page=1&page_size=100');
    return _list(json['data']).map(AdminRoute.fromJson).toList();
  }

  Future<void> createRoute({
    required String name,
    String? code,
    String? description,
  }) async {
    final body = {
      'organization_id': orgId,
      'name': name,
      if (code != null && code.isNotEmpty) 'code': code,
      if (description != null && description.isNotEmpty)
        'description': description,
    };
    await _client.post('/routes', body: body);
  }

  Future<void> addStopToRoute({
    required String routeId,
    required String name,
    required double latitude,
    required double longitude,
    int sequence = 1,
    int? geofenceRadiusM = 100,
  }) async {
    final body = {
      'name': name,
      'latitude': latitude,
      'longitude': longitude,
      'sequence_no': sequence,
      if (geofenceRadiusM != null) 'geofence_radius_m': geofenceRadiusM,
    };
    await _client.post('/routes/$routeId/stops', body: body);
  }

  Future<void> scheduleTrip({
    required String vehicleId,
    required String driverId,
    required String routeId,
    required String tripType,
    required String scheduledDate,
  }) async {
    final body = {
      'organization_id': orgId,
      'vehicle_id': vehicleId,
      'driver_id': driverId,
      'route_id': routeId,
      'trip_type': tripType,
      'scheduled_date': scheduledDate,
    };
    await _client.post('/trips', body: body);
  }

  Future<List<AdminTripItem>> listTrips({String? status, String? search}) async {
    final statusFilter = status != null && status != 'all' ? '&filter[status]=$status' : '';
    final searchFilter = search != null && search.isNotEmpty ? '&search=$search' : '';
    final json = await _client.get('/trips?page=1&page_size=100$statusFilter$searchFilter');
    return _list(json['data']).map(AdminTripItem.fromJson).toList();
  }

  Future<void> startTrip(String tripId) async {
    await _client.post('/trips/$tripId/start', body: {});
  }

  Future<void> endTrip(String tripId) async {
    await _client.post('/trips/$tripId/end', body: {});
  }

  Future<List<BoardTrip>> trips() async {
    final json = await _client.get('/trips?page=1&page_size=100');
    return _list(json['data']).map(BoardTrip.fromJson).toList();
  }

  Future<List<SafetyAlert>> activeAlerts() async {
    return (await _client.getList(
      '/safety-alerts?status=open&status=acknowledged',
    )).map(SafetyAlert.fromJson).toList();
  }

  // --- ERP Finance ----------------------------------------------------------

  Future<AdminFinanceSummary> financeSummary() async {
    try {
      final json = await _client.get('/school-finance/summary');
      return AdminFinanceSummary.fromJson(json);
    } catch (_) {
      return const AdminFinanceSummary(
        billedAmount: '0.00',
        collectedAmount: '0.00',
        outstandingAmount: '0.00',
        invoiceCount: 0,
        paidInvoiceCount: 0,
        overdueInvoiceCount: 0,
        currency: 'USD',
      );
    }
  }

  Future<List<AdminInvoice>> invoices({String? status}) async {
    try {
      final statusParam = status != null && status.isNotEmpty ? '&filter[status]=$status' : '';
      final json = await _client.get('/school-finance/student-invoices?page=1&page_size=100$statusParam');
      return _list(json['data']).map(AdminInvoice.fromJson).toList();
    } catch (_) {
      return const [];
    }
  }

  Future<void> issueInvoice({
    required String studentId,
    required String period,
    required double amount,
    String? dueDate,
    String? notes,
  }) async {
    final body = {
      'organization_id': orgId,
      'student_id': studentId,
      'period': period,
      'amount': amount.toStringAsFixed(2),
      'currency': 'USD',
      if (dueDate != null && dueDate.isNotEmpty) 'due_date': dueDate,
      if (notes != null && notes.isNotEmpty) 'notes': notes,
    };
    await _client.post('/school-finance/student-invoices', body: body);
  }

  Future<List<AdminParentInvoice>> parentInvoices({
    String? period,
    String? status,
    String? vehicleId,
  }) async {
    try {
      final periodParam =
          period != null && period.isNotEmpty ? '&period=$period' : '';
      final statusParam =
          status != null && status.isNotEmpty && status != 'all'
              ? '&status=$status'
              : '';
      final vehicleParam =
          vehicleId != null && vehicleId.isNotEmpty && vehicleId != 'all'
              ? '&vehicle_id=$vehicleId'
              : '';
      final json = await _client.get(
        '/school-finance/parent-invoices?page=1&page_size=100$periodParam$statusParam$vehicleParam',
      );
      return _list(json['data']).map(AdminParentInvoice.fromJson).toList();
    } catch (_) {
      return const [];
    }
  }

  Future<List<AdminParentInvoice>> generateMonthlyParentInvoices(
    String period,
  ) async {
    await _client.post(
      '/school-finance/parent-invoices/generate',
      body: {'period': period},
    );
    return parentInvoices(period: period);
  }

  Future<void> recordParentPayment({
    required String invoiceId,
    required double amount,
    required String method,
    String? reference,
    String? notes,
  }) async {
    final backendMethod = switch (method.toLowerCase()) {
      'evc plus' || 'zaad' || 'sahal' || 'mobile money' => 'mobile_money',
      'kaash (cash)' || 'cash' || 'kaash' => 'cash',
      'bank' || 'bank_transfer' => 'bank_transfer',
      'card' => 'card',
      'cheque' => 'cheque',
      _ => 'mobile_money',
    };

    final effectiveNotes = (method == 'EVC Plus' || method == 'Zaad' || method == 'Sahal')
        ? (notes != null && notes.isNotEmpty ? '$method - $notes' : method)
        : notes;

    final body = {
      'amount': amount.toStringAsFixed(2),
      'currency': 'USD',
      'method': backendMethod,
      'received_on': isoDate(DateTime.now()),
      if (reference != null && reference.trim().isNotEmpty)
        'reference': reference.trim(),
      if (effectiveNotes != null && effectiveNotes.trim().isNotEmpty)
        'notes': effectiveNotes.trim(),
    };
    await _client.post(
      '/school-finance/parent-invoices/$invoiceId/payments',
      body: body,
    );
  }

  Future<void> recordPayment({
    required String invoiceId,
    required double amount,
    required String method,
    String? reference,
    String? notes,
  }) async {
    final body = {
      'amount': amount.toStringAsFixed(2),
      'currency': 'USD',
      'method': method,
      'received_on': isoDate(DateTime.now()),
      if (reference != null && reference.isNotEmpty) 'reference': reference,
      if (notes != null && notes.isNotEmpty) 'notes': notes,
    };
    await _client.post('/school-finance/student-invoices/$invoiceId/payments', body: body);
  }

  // --- Live Video & Two-Way Intercom ----------------------------------------

  Future<Map<String, dynamic>> requestLiveVideo({
    required String deviceId,
    required String cameraId,
    String streamType = 'sub',
  }) async {
    return await _client.post('/video/live', body: {
      'device_id': deviceId,
      'camera_id': cameraId,
      'stream_type': streamType,
    });
  }

  Future<Map<String, dynamic>> requestIntercom({
    required String deviceId,
    required String cameraId,
  }) async {
    return await _client.post('/video/intercom', body: {
      'device_id': deviceId,
      'camera_id': cameraId,
    });
  }

  Future<void> stopVideoSession(String sessionId) async {
    await _client.post('/video/sessions/$sessionId/stop', body: {});
  }

  // --- Staff & Bus Crew -----------------------------------------------------

  Future<List<AdminStaff>> staffList() async {
    try {
      final json = await _client.get('/drivers?page=1&page_size=100');
      return _list(json['data']).map(AdminStaff.fromJson).toList();
    } catch (_) {
      return const [];
    }
  }

  Future<void> createStaff({
    required String fullName,
    required String phone,
    required String role,
    String? licenseNo,
  }) async {
    final body = {
      'organization_id': orgId,
      'full_name': fullName,
      'phone': phone,
      if (licenseNo != null && licenseNo.isNotEmpty) 'license_no': licenseNo,
    };
    await _client.post('/drivers', body: body);
  }

  Future<void> assignBusCrew({
    required String vehicleId,
    required String driverId,
    String? attendantId,
  }) async {
    final body = {
      'vehicle_id': vehicleId,
      'driver_id': driverId,
      if (attendantId != null && attendantId.isNotEmpty) 'attendant_id': attendantId,
    };
    await _client.post('/vehicles/$vehicleId/crew', body: body);
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
  (ref) => ref.watch(adminRepositoryProvider).overview(),
);

final adminBoardProvider = FutureProvider.autoDispose<DailyBoard>(
  (ref) => ref.watch(adminRepositoryProvider).dailyBoard(DateTime.now()),
);

final adminAlertsProvider = FutureProvider.autoDispose<List<SafetyAlert>>(
  (ref) => ref.watch(adminRepositoryProvider).activeAlerts(),
);

final adminFleetOnlineProvider = FutureProvider.autoDispose<FleetOnline>(
  (ref) => ref.watch(adminRepositoryProvider).fleetOnline(),
);

final adminDriversProvider = FutureProvider.autoDispose<List<AdminDriver>>(
  (ref) => ref.watch(adminRepositoryProvider).drivers(),
);

final adminParentsProvider = FutureProvider.autoDispose<List<AdminParent>>(
  (ref) => ref.watch(adminRepositoryProvider).parents(),
);

final adminStudentsProvider = FutureProvider.autoDispose<List<AdminStudent>>(
  (ref) => ref.watch(adminRepositoryProvider).students(),
);

final adminVehiclesListProvider =
    FutureProvider.autoDispose<List<AdminVehicle>>(
      (ref) => ref.watch(adminRepositoryProvider).vehicles(),
    );

final adminDevicesProvider = FutureProvider.autoDispose<List<AdminDevice>>(
  (ref) => ref.watch(adminRepositoryProvider).devices(),
);

final adminRoutesProvider = FutureProvider.autoDispose<List<AdminRoute>>(
  (ref) => ref.watch(adminRepositoryProvider).routes(),
);

final adminTripsProvider = FutureProvider.autoDispose<List<BoardTrip>>(
  (ref) => ref.watch(adminRepositoryProvider).trips(),
);

final adminVehicleNamesProvider =
    FutureProvider.autoDispose<Map<String, String>>((ref) async {
      final vehicles = await ref.watch(adminRepositoryProvider).vehicles();
      return {for (final v in vehicles) v.id: v.displayName};
    });

// --- 5-Pillar Providers -----------------------------------------------------

final adminFinanceSummaryProvider = FutureProvider.autoDispose<AdminFinanceSummary>(
  (ref) => ref.watch(adminRepositoryProvider).financeSummary(),
);

final adminInvoicesListProvider = FutureProvider.autoDispose<List<AdminInvoice>>(
  (ref) => ref.watch(adminRepositoryProvider).invoices(),
);

final adminParentInvoicesProvider =
    FutureProvider.autoDispose<List<AdminParentInvoice>>(
  (ref) => ref.watch(adminRepositoryProvider).parentInvoices(),
);

final adminParentInvoicesByBusProvider =
    FutureProvider.autoDispose.family<List<AdminParentInvoice>, String?>(
  (ref, vehicleId) =>
      ref.watch(adminRepositoryProvider).parentInvoices(vehicleId: vehicleId),
);

final adminTripsItemsProvider = FutureProvider.autoDispose<List<AdminTripItem>>(
  (ref) => ref.watch(adminRepositoryProvider).listTrips(),
);

final adminStaffMembersProvider = FutureProvider.autoDispose<List<AdminStaff>>(
  (ref) => ref.watch(adminRepositoryProvider).staffList(),
);
