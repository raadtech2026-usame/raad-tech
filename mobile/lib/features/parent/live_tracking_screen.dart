import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state.dart';
import '../../core/config/env.dart';
import '../../core/data/models.dart';
import '../../core/data/repository.dart';
import '../../core/l10n/strings.dart';
import '../../core/network/api_exception.dart';
import '../../core/network/realtime_clients.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import '../map/bus_map.dart';

/// Live position of one child's bus.
///
/// The position comes from the terminal on the bus, through RAAD's tracking service. The
/// server decides on every push whether this parent may see it (their child rides the bus and
/// it is on a trip) and closes the socket when that ends. Nothing here is estimated: with no
/// position the screen says so, and a position older than [staleAfter] is marked as old.
class LiveTrackingScreen extends ConsumerStatefulWidget {
  final ChildTransport child;
  const LiveTrackingScreen({super.key, required this.child});

  static const staleAfter = Duration(minutes: 2);

  @override
  ConsumerState<LiveTrackingScreen> createState() => _LiveTrackingScreenState();
}

enum _Phase { connecting, live, reconnecting, tripEnded, denied }

class _LiveTrackingScreenState extends ConsumerState<LiveTrackingScreen> {
  final _socket = TrackingSocket();
  StreamSubscription<TrackingPosition>? _positions;
  StreamSubscription<TrackingClosed>? _closed;
  Timer? _reconnect;
  Timer? _ticker;
  TrackingPosition? _position;
  _Phase _phase = _Phase.connecting;

  String get _vehicleId => widget.child.vehicle!.id;

  @override
  void initState() {
    super.initState();
    _positions = _socket.positions.listen((position) {
      if (!mounted) return;
      setState(() {
        if (position.hasFix || _position == null) _position = position;
        _phase = _Phase.live;
      });
    });
    _closed = _socket.closed.listen(_onClosed);
    // Redraws the "last updated" line and the stale marker as time passes.
    _ticker = Timer.periodic(const Duration(seconds: 15), (_) {
      if (mounted) setState(() {});
    });
    _start();
  }

  Future<void> _start() async {
    _loadLatest();
    final token = ref.read(apiClientProvider).accessToken;
    if (token == null) return;
    _socket.connect(accessToken: token, vehicleId: _vehicleId);
  }

  /// The last known position, so the map is not empty until the next push arrives.
  Future<void> _loadLatest() async {
    try {
      final latest =
          await ref.read(repositoryProvider).latestPosition(_vehicleId);
      if (mounted && latest != null && _position == null) {
        setState(() => _position = latest);
      }
    } on ApiException catch (e) {
      if (mounted && e.statusCode == 403) {
        setState(() => _phase = _Phase.denied);
      }
    } catch (_) {
      // No cached position yet, or offline: the socket state says what is going on.
    }
  }

  void _onClosed(TrackingClosed reason) {
    if (!mounted) return;
    switch (reason) {
      case TrackingClosed.tripEnded:
        setState(() => _phase = _Phase.tripEnded);
        ref.invalidate(myTransportProvider);
      case TrackingClosed.denied:
        setState(() => _phase = _Phase.denied);
        ref.invalidate(myTransportProvider);
      case TrackingClosed.unauthenticated:
      case TrackingClosed.lost:
        setState(() => _phase = _Phase.reconnecting);
        _reconnect?.cancel();
        _reconnect = Timer(const Duration(seconds: 5), _retry);
    }
  }

  /// A lost socket is retried. An expired access token is renewed first by making an ordinary
  /// request, which goes through the client's refresh.
  Future<void> _retry() async {
    if (!mounted) return;
    try {
      await ref.read(repositoryProvider).myTransport();
    } catch (_) {
      // Still offline: the next attempt will try again.
    }
    if (mounted) _start();
  }

  @override
  void dispose() {
    _reconnect?.cancel();
    _ticker?.cancel();
    _positions?.cancel();
    _closed?.cancel();
    _socket.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final child = widget.child;
    final position = _position;
    final stop = child.relevantStop;
    final hasFix = position != null && position.hasFix;
    final age = position?.eventTime == null
        ? null
        : DateTime.now().difference(position!.eventTime!);
    final isStale = age != null && age > LiveTrackingScreen.staleAfter;

    Widget banner(IconData icon, String text, Color color) {
      return Container(
        width: double.infinity,
        color: color.withValues(alpha: 0.12),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(
          children: [
            Icon(icon, color: color, size: 20),
            const SizedBox(width: 10),
            Expanded(
                child: Text(text,
                    style:
                        TextStyle(color: color, fontWeight: FontWeight.w600))),
          ],
        ),
      );
    }

    final Widget? status = switch (_phase) {
      _Phase.tripEnded =>
        banner(Icons.flag_rounded, s.tripEnded, RaadColors.grey),
      _Phase.denied =>
        banner(Icons.info_outline_rounded, s.trackingDenied, RaadColors.amber),
      _Phase.reconnecting =>
        banner(Icons.wifi_off_rounded, s.connectionLost, RaadColors.amber),
      _Phase.connecting when !hasFix => null,
      _ when isStale =>
        banner(Icons.schedule_rounded, s.staleLocation, RaadColors.amber),
      _ => null,
    };

    Widget body;
    if (!hasFix) {
      body = _phase == _Phase.denied || _phase == _Phase.tripEnded
          ? EmptyView(
              icon: Icons.directions_bus_outlined,
              message: s.trackingOnlyOnTrip)
          : Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const CircularProgressIndicator(),
                  const SizedBox(height: 16),
                  Text(position == null ? s.waitingForPosition : s.noGpsFix),
                ],
              ),
            );
    } else if (Env.hasMap) {
      body = BusMap(
        busLatitude: position.lat!,
        busLongitude: position.lng!,
        heading: position.headingDeg?.toDouble(),
        stopLatitude: stop?.latitude,
        stopLongitude: stop?.longitude,
        stopName: stop?.name,
        isStale: isStale || _phase != _Phase.live,
      );
    } else {
      body = EmptyView(icon: Icons.map_outlined, message: s.mapUnavailable);
    }

    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(s.liveLocation),
            Text(
              '${child.fullName} · ${child.vehicle!.displayName}',
              style: const TextStyle(fontSize: 12.5, color: RaadColors.grey),
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          if (status != null) status,
          Expanded(child: body),
          if (hasFix)
            _PositionPanel(
                position: position,
                stop: stop,
                isLive: _phase == _Phase.live && !isStale),
        ],
      ),
    );
  }
}

class _PositionPanel extends ConsumerWidget {
  final TrackingPosition position;
  final Stop? stop;
  final bool isLive;
  const _PositionPanel(
      {required this.position, required this.stop, required this.isLive});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final distance = stop == null
        ? null
        : distanceMetres(
            position.lat!, position.lng!, stop!.latitude, stop!.longitude);
    return Container(
      width: double.infinity,
      color: Colors.white,
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 20),
      child: SafeArea(
        top: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                StatusChip(
                  label: isLive ? s.live : s.staleLocation,
                  color: isLive ? RaadColors.green : RaadColors.amber,
                ),
                const Spacer(),
                if (position.eventTime != null)
                  Text(
                    s.lastUpdated(clock(position.eventTime!)),
                    style:
                        const TextStyle(fontSize: 12.5, color: RaadColors.grey),
                  ),
              ],
            ),
            if (distance != null) ...[
              const SizedBox(height: 10),
              Text(
                s.distanceToStop(friendlyDistance(distance)),
                style:
                    const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
              ),
              Text(stop!.name, style: const TextStyle(color: RaadColors.grey)),
            ],
            if (position.speedKph != null) ...[
              const SizedBox(height: 6),
              Text(s.speed(position.speedKph!.round().toString())),
            ],
            if (!Env.hasMap) ...[
              const SizedBox(height: 6),
              Text(
                  '${position.lat!.toStringAsFixed(5)}, ${position.lng!.toStringAsFixed(5)}'),
            ],
          ],
        ),
      ),
    );
  }
}
