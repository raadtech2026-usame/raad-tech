/// Mirrors `TripSummaryResponse` (backend `transport_ops/api/schemas.py`) — the shape
/// `GET /trips` actually returns per row.
class Trip {
  final String id;
  final String vehicleId;
  final String driverId;
  final String routeId;
  final String tripType;
  final String status;
  final String scheduledDate;

  const Trip({
    required this.id,
    required this.vehicleId,
    required this.driverId,
    required this.routeId,
    required this.tripType,
    required this.status,
    required this.scheduledDate,
  });

  factory Trip.fromJson(Map<String, dynamic> json) {
    return Trip(
      id: json['id'] as String,
      vehicleId: json['vehicle_id'] as String,
      driverId: json['driver_id'] as String,
      routeId: json['route_id'] as String,
      tripType: json['trip_type'] as String,
      status: json['status'] as String,
      scheduledDate: json['scheduled_date'] as String,
    );
  }

  bool get canStart => status == 'scheduled';
  bool get canEnd => status == 'in_progress' || status == 'interrupted';
}
