import '../network/api_client.dart';
import 'me_identity.dart';

/// `GET /me` (ADR-0023, extended by ADR-0026 §5). Self-scoped from the caller's own bearer
/// token — never accepts or needs any id from the caller, mirroring the backend route's own
/// "no client-supplied parent_id/driver_id" structural guarantee.
class MeRepository {
  final ApiClient _client;

  const MeRepository(this._client);

  Future<MeIdentity> getMyIdentity() async {
    final json = await _client.get('/me');
    return MeIdentity.fromJson(json);
  }
}
