import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import '../config/env.dart';

/// `/ws/tracking` client (API Contracts §11.1/§11.2), matching the documented protocol exactly:
/// connect, send `{"type":"auth","token":"<jwt>"}` as the very first frame (not a subprotocol —
/// the backend's own `resolve_principal_from_access_token` handshake), then one
/// `{"channel":"vehicle","vehicle_id":"<id>"}` subscribe frame per vehicle of interest (the
/// backend replaces any prior subscription on the same connection — no unsubscribe frame
/// needed to switch vehicles). Server pushes `{"type":"position", vehicle_id, trip_id, lat,
/// lng, speed_kph, heading_deg, event_time}` frames — decoded into [TrackingPosition] below.
///
/// Deliberately one subscription per connection (mirrors the backend's own documented
/// simplification, `tracking/api/ws.py`) — this client is not a general-purpose multi-vehicle
/// fan-out, matching the web dashboard's own F7 "one vehicle, one live map" scope exactly.
class TrackingPosition {
  final String vehicleId;
  final String? tripId;
  final double? lat;
  final double? lng;
  final num? speedKph;
  final num? headingDeg;
  final String? eventTime;

  const TrackingPosition({
    required this.vehicleId,
    this.tripId,
    this.lat,
    this.lng,
    this.speedKph,
    this.headingDeg,
    this.eventTime,
  });

  factory TrackingPosition.fromJson(Map<String, dynamic> json) {
    return TrackingPosition(
      vehicleId: json['vehicle_id'] as String,
      tripId: json['trip_id'] as String?,
      lat: (json['lat'] as num?)?.toDouble(),
      lng: (json['lng'] as num?)?.toDouble(),
      speedKph: json['speed_kph'] as num?,
      headingDeg: json['heading_deg'] as num?,
      eventTime: json['event_time'] as String?,
    );
  }
}

class TrackingWebSocketClient {
  WebSocketChannel? _channel;
  StreamController<TrackingPosition>? _positionController;
  StreamController<void>? _closedController;

  Stream<TrackingPosition> get positions =>
      _positionController?.stream ?? const Stream.empty();

  /// Fires once if the server closes the connection (e.g. `subscription_closed` per API
  /// Contracts §11.2, or a CR-1 access revocation re-check failing on the next push) — the
  /// screen consuming this must treat it as "no longer tracking," never leave a stale marker
  /// on screen (`.claude/rules/flutter.md` #6).
  Stream<void> get closed => _closedController?.stream ?? const Stream.empty();

  Future<void> connectAndSubscribe({
    required String accessToken,
    required String vehicleId,
  }) async {
    await disconnect();
    final channel = WebSocketChannel.connect(Uri.parse('${Env.wsBaseUrl}/ws/tracking'));
    _channel = channel;
    _positionController = StreamController<TrackingPosition>.broadcast();
    _closedController = StreamController<void>.broadcast();

    channel.sink.add(jsonEncode({'type': 'auth', 'token': accessToken}));
    channel.sink.add(jsonEncode({'channel': 'vehicle', 'vehicle_id': vehicleId}));

    channel.stream.listen(
      (raw) {
        final decoded = jsonDecode(raw as String) as Map<String, dynamic>;
        if (decoded['type'] == 'position') {
          _positionController?.add(TrackingPosition.fromJson(decoded));
        }
      },
      onDone: () => _closedController?.add(null),
      onError: (_) => _closedController?.add(null),
      cancelOnError: true,
    );
  }

  Future<void> disconnect() async {
    await _channel?.sink.close();
    await _positionController?.close();
    await _closedController?.close();
    _channel = null;
    _positionController = null;
    _closedController = null;
  }
}
