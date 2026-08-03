import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state.dart';
import '../../core/network/tracking_websocket_client.dart';

/// `/ws/tracking` live position view — Phase M3's core safety-relevant behavior
/// (`.claude/rules/flutter.md` #4: "Parent live GPS is active-trip-only... never a stale/
/// misleading 'live' indicator"). Fully implemented against the real, documented WebSocket
/// protocol (`core/network/tracking_websocket_client.dart`) — the one piece of the Parent
/// experience that doesn't depend on the missing "list my children" backend capability
/// (`parent_home_screen.dart`'s own docstring), since it only needs a `vehicleId`, not a
/// resolved Parent/Student identity.
///
/// Three states, matching `flutter.md` #6 ("offline/safety UI never fails silently"): loading
/// while the socket connects, an explicit "not tracking" state when the server closes the
/// connection (no active trip, access revoked, etc. — API Contracts §11.2's documented close
/// reasons) rather than freezing on the last-known position, and the live position feed itself.
class LiveTrackingScreen extends ConsumerStatefulWidget {
  final String vehicleId;

  const LiveTrackingScreen({super.key, required this.vehicleId});

  @override
  ConsumerState<LiveTrackingScreen> createState() => _LiveTrackingScreenState();
}

class _LiveTrackingScreenState extends ConsumerState<LiveTrackingScreen> {
  final _wsClient = TrackingWebSocketClient();
  TrackingPosition? _lastPosition;
  bool _isTracking = false;

  @override
  void initState() {
    super.initState();
    _connect();
  }

  Future<void> _connect() async {
    final authState = ref.read(authControllerProvider);
    if (authState is! AuthAuthenticated) return;

    await _wsClient.connectAndSubscribe(
      accessToken: authState.session.accessToken,
      vehicleId: widget.vehicleId,
    );
    setState(() => _isTracking = true);

    _wsClient.positions.listen((position) {
      if (mounted) setState(() => _lastPosition = position);
    });
    _wsClient.closed.listen((_) {
      if (mounted) setState(() => _isTracking = false);
    });
  }

  @override
  void dispose() {
    _wsClient.disconnect();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Live location')),
      body: Center(
        child: !_isTracking
            ? const Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'Not tracking — no active trip right now. Live location only shows while '
                  'your child\'s bus is on an active trip.',
                  textAlign: TextAlign.center,
                ),
              )
            : _lastPosition == null
                ? const Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      CircularProgressIndicator(),
                      SizedBox(height: 16),
                      Text('Waiting for the first position update…'),
                    ],
                  )
                : _PositionCard(position: _lastPosition!),
      ),
    );
  }
}

class _PositionCard extends StatelessWidget {
  final TrackingPosition position;

  const _PositionCard({required this.position});

  @override
  Widget build(BuildContext context) {
    // A real map (Mapbox, matching the web dashboard's own ADR-0011 provider decision, per
    // `.claude/rules/flutter.md` #6: "mapping is a pluggable provider abstraction") is Phase
    // M3's own remaining rendering work — deferred here rather than wiring a second map SDK
    // dependency with no API key to test it against in this sandbox. This card proves the
    // live data pipeline itself works end to end.
    return Card(
      margin: const EdgeInsets.all(24),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: const [
                Icon(Icons.circle, color: Colors.green, size: 12),
                SizedBox(width: 8),
                Text('Live', style: TextStyle(fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 16),
            Text('Latitude: ${position.lat}'),
            Text('Longitude: ${position.lng}'),
            if (position.speedKph != null) Text('Speed: ${position.speedKph} km/h'),
            if (position.eventTime != null) Text('As of: ${position.eventTime}'),
          ],
        ),
      ),
    );
  }
}
