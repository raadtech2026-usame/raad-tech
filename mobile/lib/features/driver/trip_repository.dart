import '../../core/network/api_client.dart';
import 'trip.dart';

/// `GET /trips` / `POST /trips/{id}/start` / `POST /trips/{id}/end`.
///
/// **Known, disclosed limitation** (Priority 1 Item 9, `PROJECT_STATUS.md`): `GET /trips` has
/// no server-side "assigned to me" filter — `Trip.driver_id` references the `Driver` aggregate's
/// own id, and no endpoint reachable by the `driver` role resolves "which `Driver.id` is my own
/// `Principal.user_id`" (no `GET /drivers/me`, no `user_id` filter on `GET /drivers`, and the
/// `driver` role holds no `transport_ops.drivers.*` permission to call `GET /drivers/{id}`
/// directly either). This mirrors the exact class of gap already discovered for Parent (see
/// `features/parent/`'s own docstring) — this repository lists every trip in the driver's own
/// organization (already tenant-scoped server-side, ADR-0021) rather than fabricating a "mine"
/// filter that isn't actually possible today. **Safety is not weakened by this**: the server
/// itself still independently enforces "Driver (own)" on `start`/`end`
/// (`_ensure_driver_owns_trip`, `transport_ops/api/routers.py`) regardless of what this screen
/// displays — attempting to start/end a trip that isn't actually assigned to the caller
/// correctly 403s with "This trip is not assigned to you," surfaced verbatim to the driver.
class TripRepository {
  final ApiClient _client;

  const TripRepository(this._client);

  Future<List<Trip>> listOrganizationTrips() async {
    final json = await _client.get('/trips?page_size=50');
    final data = json['data'] as List<dynamic>;
    return data.map((e) => Trip.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Trip> startTrip(String tripId) async {
    final json = await _client.post('/trips/$tripId/start');
    return Trip.fromJson(json);
  }

  Future<Trip> endTrip(String tripId) async {
    final json = await _client.post('/trips/$tripId/end');
    return Trip.fromJson(json);
  }
}
