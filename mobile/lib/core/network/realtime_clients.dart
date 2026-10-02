import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import '../config/env.dart';

/// A bus position pushed by `/ws/tracking` (API Contracts §11.2).
class TrackingPosition {
  final String vehicleId;
  final double? lat;
  final double? lng;
  final num? speedKph;
  final num? headingDeg;
  final DateTime? eventTime;
  final bool isGpsValid;

  const TrackingPosition({
    required this.vehicleId,
    this.lat,
    this.lng,
    this.speedKph,
    this.headingDeg,
    this.eventTime,
    this.isGpsValid = true,
  });

  bool get hasFix => isGpsValid && lat != null && lng != null;

  factory TrackingPosition.fromJson(Map<String, dynamic> json) {
    return TrackingPosition(
      vehicleId: json['vehicle_id'] as String? ?? '',
      lat: ((json['lat'] ?? json['latitude']) as num?)?.toDouble(),
      lng: ((json['lng'] ?? json['longitude']) as num?)?.toDouble(),
      speedKph: json['speed_kph'] as num?,
      headingDeg: json['heading_deg'] as num?,
      eventTime:
          DateTime.tryParse(json['event_time'] as String? ?? '')?.toLocal(),
      isGpsValid: json['is_gps_valid'] as bool? ?? true,
    );
  }
}

/// Why a tracking socket closed. The server's close codes are in
/// `interfaces/http/realtime.WsCloseCode`.
enum TrackingClosed { tripEnded, denied, unauthenticated, lost }

/// One live subscription to one bus.
///
/// Protocol: first frame `{"type":"auth","token":...}`, then
/// `{"type":"subscribe","channel":"vehicle","vehicle_id":...}`. The server re-checks the
/// caller's right to see the bus on every position it forwards, and closes the socket when
/// that right ends.
class TrackingSocket {
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  final _positions = StreamController<TrackingPosition>.broadcast();
  final _closed = StreamController<TrackingClosed>.broadcast();
  bool _tripEnded = false;

  Stream<TrackingPosition> get positions => _positions.stream;
  Stream<TrackingClosed> get closed => _closed.stream;

  void connect({required String accessToken, required String vehicleId}) {
    disconnect();
    _tripEnded = false;
    final channel =
        WebSocketChannel.connect(Uri.parse('${Env.wsBaseUrl}/ws/tracking'));
    _channel = channel;
    channel.sink.add(jsonEncode({'type': 'auth', 'token': accessToken}));
    channel.sink.add(
      jsonEncode(
          {'type': 'subscribe', 'channel': 'vehicle', 'vehicle_id': vehicleId}),
    );
    _subscription = channel.stream.listen(
      (raw) {
        if (raw is! String) return;
        final dynamic decoded;
        try {
          decoded = jsonDecode(raw);
        } on FormatException {
          return;
        }
        if (decoded is! Map<String, dynamic>) return;
        if (decoded['type'] == 'position') {
          _positions.add(TrackingPosition.fromJson(decoded));
        } else if (decoded['type'] == 'subscription_closed') {
          _tripEnded = true;
        }
      },
      onDone: () => _emitClosed(channel.closeCode),
      onError: (_) => _emitClosed(null),
      cancelOnError: true,
    );
  }

  void _emitClosed(int? code) {
    if (_closed.isClosed) return;
    if (_tripEnded) {
      _closed.add(TrackingClosed.tripEnded);
    } else if (code == 4403) {
      _closed.add(TrackingClosed.denied);
    } else if (code == 4401) {
      _closed.add(TrackingClosed.unauthenticated);
    } else {
      _closed.add(TrackingClosed.lost);
    }
  }

  void disconnect() {
    _subscription?.cancel();
    _subscription = null;
    _channel?.sink.close();
    _channel = null;
  }

  void dispose() {
    disconnect();
    _positions.close();
    _closed.close();
  }
}

/// `/ws/notifications`: the server pushes a frame when a notification is created for the
/// signed-in person. The frame is only a signal; the list is re-read over REST.
class NotificationsSocket {
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  final _arrivals = StreamController<void>.broadcast();
  Timer? _reconnect;
  String? _token;
  bool _disposed = false;

  Stream<void> get arrivals => _arrivals.stream;

  void connect(String accessToken) {
    _token = accessToken;
    _open();
  }

  void _open() {
    if (_disposed || _token == null) return;
    _subscription?.cancel();
    _channel?.sink.close();
    final channel = WebSocketChannel.connect(
        Uri.parse('${Env.wsBaseUrl}/ws/notifications'));
    _channel = channel;
    channel.sink.add(jsonEncode({'type': 'auth', 'token': _token}));
    _subscription = channel.stream.listen(
      (raw) {
        if (raw is String && raw.contains('"notification"'))
          _arrivals.add(null);
      },
      onDone: _scheduleReconnect,
      onError: (_) => _scheduleReconnect(),
      cancelOnError: true,
    );
  }

  void _scheduleReconnect() {
    if (_disposed) return;
    _reconnect?.cancel();
    _reconnect = Timer(const Duration(seconds: 15), _open);
  }

  void dispose() {
    _disposed = true;
    _reconnect?.cancel();
    _subscription?.cancel();
    _channel?.sink.close();
    _arrivals.close();
  }
}
