/// Wire models for the `/me/*` self-service API (ADR-0060, ADR-0061) and notifications.
/// Plain classes with `fromJson`; nothing here talks to the network.
library;

import '../util/format.dart';

DateTime? _dateTime(Object? value) => parseServerTime(value);

DateTime _day(Object? value) => DateTime.parse(value as String);

class Vehicle {
  final String id;
  final String plateNo;
  final String? label;
  const Vehicle({required this.id, required this.plateNo, this.label});

  String get displayName =>
      (label == null || label!.isEmpty) ? plateNo : '$label · $plateNo';

  static Vehicle? fromJson(Object? json) {
    if (json is! Map<String, dynamic>) return null;
    return Vehicle(
      id: json['id'] as String,
      plateNo: json['plate_no'] as String? ?? '',
      label: json['label'] as String?,
    );
  }
}

class Stop {
  final String id;
  final String name;
  final double latitude;
  final double longitude;
  final int? sequenceNo;
  const Stop({
    required this.id,
    required this.name,
    required this.latitude,
    required this.longitude,
    this.sequenceNo,
  });

  static Stop? fromJson(Object? json) {
    if (json is! Map<String, dynamic>) return null;
    return Stop(
      id: json['id'] as String,
      name: json['name'] as String? ?? '',
      latitude: (json['latitude'] as num).toDouble(),
      longitude: (json['longitude'] as num).toDouble(),
      sequenceNo: json['sequence_no'] as int?,
    );
  }
}

/// A trip as its driver or a parent sees it (`GET /me/trips`).
class Trip {
  final String id;
  final String tripType;
  final String status;
  final DateTime scheduledDate;
  final String? plannedDeparture;
  final DateTime? startedAt;
  final DateTime? endedAt;
  final String? cancelledReason;
  final String routeId;
  final String? routeName;
  final Vehicle? vehicle;
  final bool isCover;
  final List<String> studentIds;

  const Trip({
    required this.id,
    required this.tripType,
    required this.status,
    required this.scheduledDate,
    required this.routeId,
    this.plannedDeparture,
    this.startedAt,
    this.endedAt,
    this.cancelledReason,
    this.routeName,
    this.vehicle,
    this.isCover = false,
    this.studentIds = const [],
  });

  bool get isScheduled => status == 'scheduled';
  bool get isInProgress => status == 'in_progress';
  bool get isCancelled => status == 'cancelled';
  bool get isFinished => status == 'completed' || status == 'cancelled';

  factory Trip.fromJson(Map<String, dynamic> json) {
    return Trip(
      id: json['id'] as String,
      tripType: json['trip_type'] as String? ?? 'morning',
      status: json['status'] as String? ?? 'scheduled',
      scheduledDate: _day(json['scheduled_date']),
      plannedDeparture: json['planned_departure'] as String?,
      startedAt: _dateTime(json['started_at']),
      endedAt: _dateTime(json['ended_at']),
      cancelledReason: json['cancelled_reason'] as String?,
      routeId: json['route_id'] as String? ?? '',
      routeName: json['route_name'] as String?,
      vehicle: Vehicle.fromJson(json['vehicle']),
      isCover: json['is_cover'] as bool? ?? false,
      studentIds: [
        for (final s in (json['students'] as List? ?? const []))
          if (s is Map<String, dynamic>) s['student_id'] as String,
      ],
    );
  }
}

/// One of the signed-in parent's children with their bus (`GET /me/transport`).
class ChildTransport {
  final String studentId;
  final String fullName;
  final String status;
  final bool hasAssignment;
  final String? routeName;
  final Stop? pickupStop;
  final Stop? dropoffStop;
  final Vehicle? vehicle;
  final String? currentTripId;
  final String? currentTripType;

  const ChildTransport({
    required this.studentId,
    required this.fullName,
    required this.status,
    required this.hasAssignment,
    this.routeName,
    this.pickupStop,
    this.dropoffStop,
    this.vehicle,
    this.currentTripId,
    this.currentTripType,
  });

  bool get isOnTrip => currentTripId != null;

  /// The stop that matters now: dropoff on an afternoon trip, pickup otherwise.
  Stop? get relevantStop =>
      currentTripType == 'afternoon' ? dropoffStop : pickupStop;

  factory ChildTransport.fromJson(Map<String, dynamic> json) {
    final assignment = json['assignment'];
    final a = assignment is Map<String, dynamic> ? assignment : null;
    final trip = json['current_trip'];
    final t = trip is Map<String, dynamic> ? trip : null;
    final route = a?['route'];
    return ChildTransport(
      studentId: json['student_id'] as String,
      fullName: json['full_name'] as String? ?? '',
      status: json['status'] as String? ?? '',
      hasAssignment: a != null,
      routeName: route is Map<String, dynamic>
          ? route['name'] as String?
          : null,
      pickupStop: Stop.fromJson(a?['pickup_stop']),
      dropoffStop: Stop.fromJson(a?['dropoff_stop']),
      vehicle: Vehicle.fromJson(a?['vehicle']),
      currentTripId: t?['id'] as String?,
      currentTripType: t?['trip_type'] as String?,
    );
  }
}

class CrewMember {
  final String fullName;
  final String? roleName;
  final bool isMe;
  final bool isSubstitute;
  const CrewMember({
    required this.fullName,
    this.roleName,
    this.isMe = false,
    this.isSubstitute = false,
  });

  factory CrewMember.fromJson(Map<String, dynamic> json) {
    return CrewMember(
      fullName: json['full_name'] as String? ?? '',
      roleName: json['role_name'] as String?,
      isMe: json['is_me'] as bool? ?? false,
      isSubstitute: json['is_substitute'] as bool? ?? false,
    );
  }
}

class Passenger {
  final String studentId;
  final String fullName;
  final String? pickupStopName;
  final String? dropoffStopName;
  const Passenger({
    this.studentId = '',
    required this.fullName,
    this.pickupStopName,
    this.dropoffStopName,
  });

  factory Passenger.fromJson(Map<String, dynamic> json) {
    return Passenger(
      studentId: json['student_id'] as String? ?? '',
      fullName: json['full_name'] as String? ?? '',
      pickupStopName: json['pickup_stop_name'] as String?,
      dropoffStopName: json['dropoff_stop_name'] as String?,
    );
  }
}

class AttendanceRecord {
  final String id;
  final String tripId;
  final String studentId;
  final String? vehicleId;
  final String? routeId;
  final String attendanceDate;
  final String status;
  final String markedAt;
  final String? notes;

  const AttendanceRecord({
    required this.id,
    required this.tripId,
    required this.studentId,
    this.vehicleId,
    this.routeId,
    required this.attendanceDate,
    required this.status,
    required this.markedAt,
    this.notes,
  });

  bool get isPresent => status == 'present' || status == 'boarded';
  bool get isAbsent => status == 'absent';

  factory AttendanceRecord.fromJson(Map<String, dynamic> json) {
    return AttendanceRecord(
      id: json['id'] as String? ?? '',
      tripId: json['trip_id'] as String? ?? '',
      studentId: json['student_id'] as String? ?? '',
      vehicleId: json['vehicle_id'] as String?,
      routeId: json['route_id'] as String?,
      attendanceDate: json['attendance_date'] as String? ?? '',
      status: json['status'] as String? ?? 'present',
      markedAt: json['marked_at'] as String? ?? '',
      notes: json['notes'] as String?,
    );
  }
}

class DriverRouteOption {
  final String id;
  final String name;
  final int stopCount;

  const DriverRouteOption({
    required this.id,
    required this.name,
    this.stopCount = 0,
  });

  factory DriverRouteOption.fromJson(Map<String, dynamic> json) {
    return DriverRouteOption(
      id: json['id'] as String? ?? '',
      name: json['name'] as String? ?? '',
      stopCount: (json['stop_count'] as num?)?.toInt() ?? 0,
    );
  }
}

class DriverStudentOption {
  final String id;
  final String fullName;
  final String? currentRouteName;
  final String? currentStopName;

  const DriverStudentOption({
    required this.id,
    required this.fullName,
    this.currentRouteName,
    this.currentStopName,
  });

  factory DriverStudentOption.fromJson(Map<String, dynamic> json) {
    return DriverStudentOption(
      id: json['id'] as String? ?? '',
      fullName: json['full_name'] as String? ?? '',
      currentRouteName: json['current_route_name'] as String?,
      currentStopName: json['current_stop_name'] as String?,
    );
  }
}

List<T> _list<T>(Object? json, T Function(Map<String, dynamic>) convert) {
  return [
    for (final item in (json as List? ?? const []))
      if (item is Map<String, dynamic>) convert(item),
  ];
}

class TripDetail {
  final Trip trip;
  final List<Stop> stops;
  final List<CrewMember> crew;
  final List<Passenger> passengers;
  const TripDetail({
    required this.trip,
    required this.stops,
    required this.crew,
    required this.passengers,
  });

  factory TripDetail.fromJson(Map<String, dynamic> json) {
    return TripDetail(
      trip: Trip.fromJson(json['trip'] as Map<String, dynamic>),
      stops: _list(json['stops'], (j) => Stop.fromJson(j)!),
      crew: _list(json['crew'], CrewMember.fromJson),
      passengers: _list(json['passengers'], Passenger.fromJson),
    );
  }
}

class BusCrew {
  final Vehicle vehicle;
  final List<CrewMember> members;
  const BusCrew({required this.vehicle, required this.members});

  factory BusCrew.fromJson(Map<String, dynamic> json) {
    return BusCrew(
      vehicle: Vehicle.fromJson(json['vehicle'])!,
      members: _list(json['members'], CrewMember.fromJson),
    );
  }
}

class StaffDocument {
  final String typeName;
  final String? number;
  final DateTime? expiresOn;
  final String status;
  final int? daysLeft;
  const StaffDocument({
    required this.typeName,
    required this.status,
    this.number,
    this.expiresOn,
    this.daysLeft,
  });

  factory StaffDocument.fromJson(Map<String, dynamic> json) {
    return StaffDocument(
      typeName: json['type_name'] as String? ?? '',
      number: json['number'] as String?,
      expiresOn: json['expires_on'] is String ? _day(json['expires_on']) : null,
      status: json['status'] as String? ?? '',
      daysLeft: json['days_left'] as int?,
    );
  }
}

class MyDocuments {
  final List<StaffDocument> documents;

  /// Null when the organization requires no documents.
  final bool? isCompliant;
  final List<String> gaps;
  const MyDocuments({
    required this.documents,
    this.isCompliant,
    this.gaps = const [],
  });

  factory MyDocuments.fromJson(Map<String, dynamic> json) {
    final compliance = json['compliance'];
    final c = compliance is Map<String, dynamic> ? compliance : null;
    final gaps = _list(c?['gaps'], (j) => j['type_name'] as String? ?? '');
    return MyDocuments(
      documents: _list(json['documents'], StaffDocument.fromJson),
      isCompliant: c == null ? null : gaps.isEmpty,
      gaps: gaps,
    );
  }
}

class Unavailability {
  final String id;
  final DateTime startsOn;
  final DateTime endsOn;
  final String reason;
  final String? note;
  final bool isWithdrawn;
  final bool isCovered;
  const Unavailability({
    required this.id,
    required this.startsOn,
    required this.endsOn,
    required this.reason,
    this.note,
    this.isWithdrawn = false,
    this.isCovered = false,
  });

  factory Unavailability.fromJson(Map<String, dynamic> json) {
    return Unavailability(
      id: json['id'] as String,
      startsOn: _day(json['starts_on']),
      endsOn: _day(json['ends_on']),
      reason: json['reason'] as String? ?? 'other',
      note: json['note'] as String?,
      isWithdrawn: json['is_withdrawn'] as bool? ?? false,
      isCovered: json['is_covered'] as bool? ?? false,
    );
  }
}

class IncidentReport {
  final String id;
  final String category;
  final String severity;
  final String status;
  final DateTime occurredAt;
  final String title;
  final String? description;
  const IncidentReport({
    required this.id,
    required this.category,
    required this.severity,
    required this.status,
    required this.occurredAt,
    required this.title,
    this.description,
  });

  factory IncidentReport.fromJson(Map<String, dynamic> json) {
    return IncidentReport(
      id: json['id'] as String,
      category: json['category'] as String? ?? 'other',
      severity: json['severity'] as String? ?? 'medium',
      status: json['status'] as String? ?? 'open',
      occurredAt: _dateTime(json['occurred_at']) ?? DateTime.now(),
      title: json['title'] as String? ?? '',
      description: json['description'] as String?,
    );
  }
}

/// A stored notification (`GET /notifications`).
class AppNotification {
  final String id;
  final String type;
  final String title;
  final String body;
  final String? kind;
  final String? tripId;
  final String? vehicleId;
  final String? plateNumber;
  final String? vehicleLabel;
  final String? alarmType;
  final String? alertId;
  final DateTime createdAt;
  final bool isRead;

  const AppNotification({
    required this.id,
    required this.type,
    required this.title,
    required this.body,
    required this.createdAt,
    this.kind,
    this.tripId,
    this.vehicleId,
    this.plateNumber,
    this.vehicleLabel,
    this.alarmType,
    this.alertId,
    this.isRead = false,
  });

  static const _transportTypes = {
    'trip_started',
    'trip_completed',
    'approaching_stop',
    'arrived_org',
  };
  static const _transportKinds = {'trip_cancelled', 'cover_assigned'};
  static const _safetyKinds = {'safety_alert'};

  /// About a bus or a trip, as opposed to a message from the school's office.
  bool get isTransport =>
      _transportTypes.contains(type) || _transportKinds.contains(kind);

  /// Critical safety, SOS, or ADAS camera alert
  bool get isSafety =>
      _safetyKinds.contains(kind) || type == 'safety_alert';

  factory AppNotification.fromJson(Map<String, dynamic> json) {
    final data = json['data'];
    final d = data is Map<String, dynamic> ? data : const <String, dynamic>{};
    return AppNotification(
      id: json['id'] as String,
      type: json['type'] as String? ?? 'system',
      title: json['title'] as String? ?? '',
      body: json['body'] as String? ?? '',
      kind: d['kind'] as String?,
      tripId: json['trip_id'] as String?,
      vehicleId: d['vehicle_id'] as String?,
      plateNumber: d['plate_number'] as String?,
      vehicleLabel: d['vehicle_label'] as String?,
      alarmType: d['alarm_type'] as String?,
      alertId: d['alert_id'] as String?,
      createdAt: _dateTime(json['created_at']) ?? DateTime.now(),
      isRead: json['status'] == 'read' || json['read_at'] != null,
    );
  }
}

class ParentFinanceSummary {
  final String parentId;
  final String currency;
  final String totalDue;
  final String totalPaid;
  final String balanceDue;
  final List<ParentInvoice> invoices;
  final List<ParentPaymentReceipt> payments;

  const ParentFinanceSummary({
    required this.parentId,
    required this.currency,
    required this.totalDue,
    required this.totalPaid,
    required this.balanceDue,
    required this.invoices,
    required this.payments,
  });

  bool get hasOutstanding => (double.tryParse(balanceDue) ?? 0) > 0;

  factory ParentFinanceSummary.fromJson(Map<String, dynamic> json) {
    return ParentFinanceSummary(
      parentId: json['parent_id'] as String? ?? '',
      currency: json['currency'] as String? ?? 'USD',
      totalDue: json['total_due'] as String? ?? '0.00',
      totalPaid: json['total_paid'] as String? ?? '0.00',
      balanceDue: json['balance_due'] as String? ?? '0.00',
      invoices: (json['invoices'] as List? ?? const [])
          .map((i) => ParentInvoice.fromJson(i as Map<String, dynamic>))
          .toList(),
      payments: (json['payments'] as List? ?? const [])
          .map((p) => ParentPaymentReceipt.fromJson(p as Map<String, dynamic>))
          .toList(),
    );
  }
}

class ParentInvoice {
  final String id;
  final String invoiceNumber;
  final String period;
  final String amount;
  final String amountPaid;
  final String balanceDue;
  final String status;
  final String currency;
  final String invoiceDate;
  final String dueDate;
  final String? notes;
  final List<ParentInvoiceLine> lines;

  const ParentInvoice({
    required this.id,
    required this.invoiceNumber,
    required this.period,
    required this.amount,
    required this.amountPaid,
    required this.balanceDue,
    required this.status,
    required this.currency,
    required this.invoiceDate,
    required this.dueDate,
    this.notes,
    required this.lines,
  });

  bool get isPaid => status == 'paid' || (double.tryParse(balanceDue) ?? 0) <= 0;
  bool get isOverdue => status == 'overdue';

  factory ParentInvoice.fromJson(Map<String, dynamic> json) {
    return ParentInvoice(
      id: json['id'] as String? ?? '',
      invoiceNumber: json['invoice_number'] as String? ?? '',
      period: json['period'] as String? ?? '',
      amount: json['amount'] as String? ?? '0.00',
      amountPaid: json['amount_paid'] as String? ?? '0.00',
      balanceDue: json['balance_due'] as String? ?? '0.00',
      status: json['status'] as String? ?? 'unpaid',
      currency: json['currency'] as String? ?? 'USD',
      invoiceDate: json['invoice_date'] as String? ?? '',
      dueDate: json['due_date'] as String? ?? '',
      notes: json['notes'] as String?,
      lines: (json['lines'] as List? ?? const [])
          .map((l) => ParentInvoiceLine.fromJson(l as Map<String, dynamic>))
          .toList(),
    );
  }
}

class ParentInvoiceLine {
  final String studentId;
  final String fullName;
  final String amount;
  final String amountPaid;
  final String balanceDue;
  final String lineId;

  const ParentInvoiceLine({
    required this.studentId,
    required this.fullName,
    required this.amount,
    required this.amountPaid,
    required this.balanceDue,
    required this.lineId,
  });

  bool get isPaid => (double.tryParse(balanceDue) ?? 0) <= 0;

  factory ParentInvoiceLine.fromJson(Map<String, dynamic> json) {
    return ParentInvoiceLine(
      studentId: json['student_id'] as String? ?? '',
      fullName: json['full_name'] as String? ?? '',
      amount: json['amount'] as String? ?? '0.00',
      amountPaid: json['amount_paid'] as String? ?? '0.00',
      balanceDue: json['balance_due'] as String? ?? '0.00',
      lineId: json['line_id'] as String? ?? '',
    );
  }
}

class ParentPaymentReceipt {
  final String id;
  final String receiptNumber;
  final String invoiceId;
  final String amount;
  final String currency;
  final String paymentMethod;
  final String paymentDate;
  final String? notes;

  const ParentPaymentReceipt({
    required this.id,
    required this.receiptNumber,
    required this.invoiceId,
    required this.amount,
    required this.currency,
    required this.paymentMethod,
    required this.paymentDate,
    this.notes,
  });

  factory ParentPaymentReceipt.fromJson(Map<String, dynamic> json) {
    return ParentPaymentReceipt(
      id: json['id'] as String? ?? '',
      receiptNumber: json['receipt_number'] as String? ?? '',
      invoiceId: json['invoice_id'] as String? ?? '',
      amount: json['amount'] as String? ?? '0.00',
      currency: json['currency'] as String? ?? 'USD',
      paymentMethod: json['payment_method'] as String? ?? '',
      paymentDate: json['payment_date'] as String? ?? '',
      notes: json['notes'] as String?,
    );
  }
}
