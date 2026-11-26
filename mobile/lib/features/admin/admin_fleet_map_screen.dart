import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../../core/auth/auth_state.dart';
import '../../core/l10n/strings.dart';
import '../../core/network/realtime_clients.dart';
import '../../shared/widgets.dart';
import '../map/bus_map.dart';
import 'admin_data.dart';
import 'admin_screens.dart';

/// Pillar 2: Live Tracking, Live Video & Two-Way Intercom.
/// Displays an interactive map of all buses in the fleet (both online and offline at last known position).
/// Tapping a bus opens an action panel with telemetry, driver details, speed, and a direct button
/// to the multi-camera CCTV wall screen.
class AdminFleetMapScreen extends ConsumerStatefulWidget {
  const AdminFleetMapScreen({super.key});

  @override
  ConsumerState<AdminFleetMapScreen> createState() =>
      _AdminFleetMapScreenState();
}

class _AdminFleetMapScreenState extends ConsumerState<AdminFleetMapScreen> {
  final _mapController = MapController();

  // Default coordinate for Mogadishu/Somalia center when no vehicles report yet
  static const _defaultCenter = LatLng(2.0469, 45.3182);

  // Cache of last known positions for vehicles (so offline buses and live WS updates stay visible)
  final Map<String, OnlineVehiclePosition> _lastKnownPositions = {};
  final Set<String> _requestedLatestPositions = {};

  // Live /ws/tracking sockets per online vehicle (mirrors Web Dashboard FleetMapPanel)
  final Map<String, TrackingSocket> _sockets = {};
  final Map<String, StreamSubscription<TrackingPosition>> _socketSubs = {};
  Timer? _fleetRefreshTimer;

  // Session-dismissed banner alerts
  final Set<String> _dismissedAlertIds = {};

  @override
  void initState() {
    super.initState();
    // Periodically refresh online fleet membership & snapshots every 15s in background.
    _fleetRefreshTimer = Timer.periodic(const Duration(seconds: 15), (_) {
      if (mounted) {
        ref.invalidate(adminFleetOnlineProvider);
        ref.invalidate(adminAlertsProvider);
      }
    });
  }

  @override
  void dispose() {
    _fleetRefreshTimer?.cancel();
    for (final sub in _socketSubs.values) {
      sub.cancel();
    }
    _socketSubs.clear();
    for (final socket in _sockets.values) {
      socket.dispose();
    }
    _sockets.clear();
    _mapController.dispose();
    super.dispose();
  }

  void _syncLiveSockets(List<OnlineVehicle> onlineList) {
    final token = ref.read(apiClientProvider).accessToken;
    if (token == null || token.isEmpty) return;

    final wantedIds = onlineList.take(40).map((v) => v.vehicleId).toSet();

    // Dispose sockets for vehicles no longer online
    final removed = _sockets.keys.where((id) => !wantedIds.contains(id)).toList();
    for (final id in removed) {
      _socketSubs.remove(id)?.cancel();
      _sockets.remove(id)?.dispose();
    }

    // Open TrackingSocket for any new online vehicle
    for (final id in wantedIds) {
      if (_sockets.containsKey(id)) continue;
      final socket = TrackingSocket();
      _sockets[id] = socket;
      _socketSubs[id] = socket.positions.listen((pos) {
        if (!mounted || !pos.hasFix) return;
        setState(() {
          _lastKnownPositions[id] = OnlineVehiclePosition(
            latitude: pos.lat!,
            longitude: pos.lng!,
            headingDeg: pos.headingDeg?.toDouble(),
            speedKph: pos.speedKph?.toDouble(),
            eventTime: pos.eventTime ?? DateTime.now().toUtc(),
          );
        });
      });
      socket.connect(accessToken: token, vehicleId: id);
    }
  }

  Future<void> _performAlertAction({
    required SafetyAlert alert,
    required String action, // 'resolve' | 'false_alarm' | 'acknowledge'
    required Strings s,
  }) async {
    try {
      final repo = ref.read(adminRepositoryProvider);
      if (action == 'resolve') {
        await repo.resolveSafetyAlert(alert.id);
      } else if (action == 'false_alarm') {
        await repo.markSafetyAlertFalseAlarm(alert.id);
      } else {
        await repo.acknowledgeSafetyAlert(alert.id);
      }
      if (!mounted) return;
      setState(() => _dismissedAlertIds.add(alert.id));
      ref.invalidate(adminAlertsProvider);
      showNotice(
        context,
        action == 'resolve'
            ? s.adminResolveAlert
            : (action == 'false_alarm'
                ? s.adminFalseAlarm
                : s.adminAcknowledgeAlert),
      );
    } catch (e) {
      if (mounted) showNotice(context, errorMessage(e, s), isError: true);
    }
  }

  void _showAlertActionSheet(
    SafetyAlert alert,
    AdminVehicle? vehicle,
    Strings s,
  ) {
    final busLabel =
        vehicle?.displayName ??
        (alert.vehicleId.length > 8
            ? alert.vehicleId.substring(0, 8)
            : alert.vehicleId);
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (ctx) => Container(
        decoration: BoxDecoration(
          color: Theme.of(context).scaffoldBackgroundColor,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
        ),
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 28),
        child: SafeArea(
          top: false,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Icon(
                    Icons.warning_amber_rounded,
                    color: RaadColors.red,
                    size: 24,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          s.notificationTitle(
                            'system',
                            'safety_alert',
                            'Digniin Badbaado',
                            alarmType: alert.alarmType,
                          ),
                          style: const TextStyle(
                            fontWeight: FontWeight.w800,
                            fontSize: 16,
                          ),
                        ),
                        Text(
                          '$busLabel · ${alert.status.toUpperCase()}',
                          style: TextStyle(fontSize: 12.5, color: context.muted),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close_rounded),
                    onPressed: () => Navigator.pop(ctx),
                  ),
                ],
              ),
              const Divider(height: 20),
              FilledButton.icon(
                icon: const Icon(Icons.videocam_rounded),
                label: Text(s.adminWatchLiveCamera),
                onPressed: () {
                  Navigator.pop(ctx);
                  Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => AdminMultiCameraScreen(
                        vehicleId: alert.vehicleId,
                        plateNo: vehicle?.plateNo ?? 'Bus',
                        label: vehicle?.label,
                      ),
                    ),
                  );
                },
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                icon: const Icon(Icons.check_circle_outline_rounded, color: RaadColors.green),
                label: Text(s.adminResolveAlert),
                onPressed: () {
                  Navigator.pop(ctx);
                  _performAlertAction(alert: alert, action: 'resolve', s: s);
                },
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                icon: const Icon(Icons.notifications_off_outlined, color: RaadColors.amber),
                label: Text(s.adminFalseAlarm),
                onPressed: () {
                  Navigator.pop(ctx);
                  _performAlertAction(alert: alert, action: 'false_alarm', s: s);
                },
              ),
              if (alert.status == 'open') ...[
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  icon: const Icon(Icons.visibility_outlined),
                  label: Text(s.adminAcknowledgeAlert),
                  onPressed: () {
                    Navigator.pop(ctx);
                    _performAlertAction(alert: alert, action: 'acknowledge', s: s);
                  },
                ),
              ],
              const SizedBox(height: 6),
              TextButton(
                onPressed: () {
                  Navigator.pop(ctx);
                  setState(() => _dismissedAlertIds.add(alert.id));
                },
                child: Text(s.adminHideForNow),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _showAllAlertsSheet(
    List<SafetyAlert> allAlerts,
    Map<String, AdminVehicle> vehicleMap,
    Strings s,
  ) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => Container(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.of(context).size.height * 0.72,
        ),
        decoration: BoxDecoration(
          color: Theme.of(context).scaffoldBackgroundColor,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
        ),
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
        child: SafeArea(
          top: false,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  const Icon(Icons.shield_outlined, color: RaadColors.red),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      '${s.adminSafetyAlertsTitle} (${allAlerts.length})',
                      style: const TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close_rounded),
                    onPressed: () => Navigator.pop(ctx),
                  ),
                ],
              ),
              const Divider(),
              if (allAlerts.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 32),
                  child: Text(
                    s.adminNoOpenAlerts,
                    style: TextStyle(color: context.muted),
                  ),
                )
              else
                Flexible(
                  child: ListView.builder(
                    shrinkWrap: true,
                    itemCount: allAlerts.length,
                    itemBuilder: (_, idx) {
                      final alert = allAlerts[idx];
                      final v = vehicleMap[alert.vehicleId];
                      final busName = v?.displayName ?? alert.vehicleId;
                      return Card(
                        margin: const EdgeInsets.only(bottom: 8),
                        child: ListTile(
                          leading: Icon(
                            Icons.warning_amber_rounded,
                            color: alert.isCritical ? RaadColors.red : RaadColors.amber,
                          ),
                          title: Text(
                            s.notificationTitle(
                              'system',
                              'safety_alert',
                              alert.alarmType,
                              alarmType: alert.alarmType,
                            ),
                            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
                          ),
                          subtitle: Text('$busName · ${alert.status} · x${alert.occurrences}'),
                          trailing: TextButton(
                            onPressed: () {
                              Navigator.pop(ctx);
                              _performAlertAction(alert: alert, action: 'resolve', s: s);
                            },
                            child: Text(s.adminResolveAlert),
                          ),
                          onTap: () {
                            Navigator.pop(ctx);
                            _showAlertActionSheet(alert, v, s);
                          },
                        ),
                      );
                    },
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  void _inspectVehicle({
    required OnlineVehicle vehicle,
    required AdminVehicle? details,
    required String? driverName,
  }) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => _VehicleActionSheet(
        vehicle: vehicle,
        details: details,
        driverName: driverName,
      ),
    );
  }

  void _fetchLastKnownPosition(String vehicleId) {
    if (_requestedLatestPositions.contains(vehicleId)) return;
    _requestedLatestPositions.add(vehicleId);

    ref
        .read(adminRepositoryProvider)
        .getLatestVehiclePosition(vehicleId)
        .then((pos) {
      if (pos != null && mounted) {
        setState(() {
          _lastKnownPositions[vehicleId] = pos;
        });
      }
    }).catchError((_) {});
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final fleetAsync = ref.watch(adminFleetOnlineProvider);
    final vehiclesAsync = ref.watch(adminVehiclesListProvider);
    final boardAsync = ref.watch(adminBoardProvider);
    final allVehiclesForAppBar = vehiclesAsync.valueOrNull ?? <AdminVehicle>[];
    final appBarVehicleMap = {for (final v in allVehiclesForAppBar) v.id: v};
    final activeAlerts = (ref.watch(adminAlertsProvider).valueOrNull ??
            const <SafetyAlert>[])
        .where((a) => a.status == 'open' || a.status == 'acknowledged')
        .toList();

    return Scaffold(
      appBar: AppBar(
        title: Text(s.adminFleetMapTitle),
        actions: [
          IconButton(
            tooltip: s.adminSafetyAlertsTitle,
            onPressed: () =>
                _showAllAlertsSheet(activeAlerts, appBarVehicleMap, s),
            icon: Stack(
              clipBehavior: Clip.none,
              children: [
                const Icon(Icons.shield_outlined),
                if (activeAlerts.isNotEmpty)
                  Positioned(
                    right: -4,
                    top: -4,
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 4,
                        vertical: 1,
                      ),
                      decoration: BoxDecoration(
                        color: RaadColors.red,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        '${activeAlerts.length}',
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 9.5,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
          ...adminTopActions(
            context,
            ref,
            onRefresh: () {
              ref.invalidate(adminFleetOnlineProvider);
              ref.invalidate(adminVehiclesListProvider);
              ref.invalidate(adminBoardProvider);
              ref.invalidate(adminAlertsProvider);
            },
          ),
        ],
      ),
      body: fleetAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(s.somethingWrong),
              const SizedBox(height: 8),
              OutlinedButton(
                onPressed: () {
                  ref.invalidate(adminFleetOnlineProvider);
                  ref.invalidate(adminVehiclesListProvider);
                },
                child: Text(s.retry),
              ),
            ],
          ),
        ),
        data: (fleet) {
          final onlineList = fleet.vehicles;
          final allVehicles = vehiclesAsync.valueOrNull ?? <AdminVehicle>[];
          final vehicleMap = {for (final v in allVehicles) v.id: v};

          // Build driver lookup from daily dispatch board
          final vehicleDriverMap = <String, String>{};
          final board = boardAsync.valueOrNull;
          if (board != null) {
            for (final bv in board.vehicles) {
              for (final trip in bv.trips) {
                if (trip.driverName != null && trip.driverName!.isNotEmpty) {
                  vehicleDriverMap[bv.vehicleId] = trip.driverName!;
                  break;
                }
              }
              if (!vehicleDriverMap.containsKey(bv.vehicleId)) {
                for (final crew in bv.crew) {
                  if (crew.roleName?.toLowerCase() == 'driver') {
                    vehicleDriverMap[bv.vehicleId] = crew.name;
                    break;
                  }
                }
              }
            }
          }

          // Cache positions from online vehicles, preferring newer live WebSocket telemetry
          final onlineIds = <String>{};
          for (final v in onlineList) {
            onlineIds.add(v.vehicleId);
            final incoming = v.position;
            if (incoming != null) {
              final existing = _lastKnownPositions[v.vehicleId];
              final existingTime = existing?.eventTime;
              final incomingTime = incoming.eventTime;
              if (existing == null ||
                  existingTime == null ||
                  (incomingTime != null && !incomingTime.isBefore(existingTime))) {
                _lastKnownPositions[v.vehicleId] = incoming;
              }
            }
          }

          // Keep live /ws/tracking subscriptions in sync for all online vehicles
          _syncLiveSockets(onlineList);

          // Trigger fetch for offline vehicles that have no cached position yet
          for (final v in allVehicles) {
            if (!onlineIds.contains(v.id) &&
                !_lastKnownPositions.containsKey(v.id)) {
              _fetchLastKnownPosition(v.id);
            }
          }

          // Find first valid vehicle position or fallback to default center
          LatLng center = _defaultCenter;
          for (final v in onlineList) {
            if (v.position != null) {
              center = LatLng(v.position!.latitude, v.position!.longitude);
              break;
            }
          }
          if (center == _defaultCenter && _lastKnownPositions.isNotEmpty) {
            final firstPos = _lastKnownPositions.values.first;
            center = LatLng(firstPos.latitude, firstPos.longitude);
          }

          // Collect markers: online vehicles first, then offline vehicles with known coordinates
          final markers = <Marker>[];

          // 1. Online bus markers (matched with web dashboard icon + live WS updates)
          final nowUtc = DateTime.now().toUtc();
          for (int i = 0; i < onlineList.length; i++) {
            final v = onlineList[i];
            final pos = _lastKnownPositions[v.vehicleId] ?? v.position;
            final point = pos != null
                ? LatLng(pos.latitude, pos.longitude)
                : LatLng(
                    _defaultCenter.latitude + (i * 0.008) - 0.004,
                    _defaultCenter.longitude + (i * 0.008) - 0.004,
                  );
            final isStaleFix = pos == null ||
                pos.eventTime == null ||
                nowUtc.difference(pos.eventTime!.toUtc()).inMinutes >= 2;

            final effectiveVehicle = OnlineVehicle(
              vehicleId: v.vehicleId,
              plateNo: v.plateNo,
              label: v.label,
              deviceId: v.deviceId,
              isOnline: v.isOnline,
              position: pos,
            );

            markers.add(
              Marker(
                point: point,
                width: 56,
                height: 56,
                child: GestureDetector(
                  onTap: () => _inspectVehicle(
                    vehicle: effectiveVehicle,
                    details: vehicleMap[v.vehicleId],
                    driverName: vehicleDriverMap[v.vehicleId],
                  ),
                  child: RaadBusMarker(
                    fixStatus: isStaleFix
                        ? BusMarkerFixStatus.stale
                        : BusMarkerFixStatus.live,
                    headingDeg: pos?.headingDeg,
                    size: 38,
                  ),
                ),
              ),
            );
          }

          // 2. Offline bus markers at last known position
          for (final v in allVehicles) {
            if (onlineIds.contains(v.id)) continue; // Already rendered above
            final pos = _lastKnownPositions[v.id];
            if (pos == null) continue; // No position on record yet

            final point = LatLng(pos.latitude, pos.longitude);
            final offlineVehicle = OnlineVehicle(
              vehicleId: v.id,
              plateNo: v.plateNo,
              label: v.label,
              deviceId: v.deviceId,
              isOnline: false,
              position: pos,
            );

            markers.add(
              Marker(
                point: point,
                width: 50,
                height: 50,
                child: GestureDetector(
                  onTap: () => _inspectVehicle(
                    vehicle: offlineVehicle,
                    details: v,
                    driverName: vehicleDriverMap[v.id],
                  ),
                  child: RaadBusMarker(
                    fixStatus: BusMarkerFixStatus.offline,
                    headingDeg: pos.headingDeg,
                    size: 32,
                  ),
                ),
              ),
            );
          }

          final alerts = (ref.watch(adminAlertsProvider).valueOrNull ??
                  const <SafetyAlert>[])
              .where(
                (a) =>
                    a.isCritical &&
                    a.status == 'open' &&
                    !_dismissedAlertIds.contains(a.id),
              )
              .toList();
          final hasCriticalAlert = alerts.isNotEmpty;
          final topAlert = hasCriticalAlert ? alerts.first : null;
          final alertVehicle =
              topAlert != null ? vehicleMap[topAlert.vehicleId] : null;

          return Stack(
            children: [
              FlutterMap(
                mapController: _mapController,
                options: MapOptions(
                  initialCenter: center,
                  initialZoom: 13,
                  minZoom: 4,
                  maxZoom: 18,
                  interactionOptions: const InteractionOptions(
                    flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
                  ),
                ),
                children: [
                  TileLayer(
                    urlTemplate:
                        (ref.watch(activeMapTileSourceProvider).valueOrNull ??
                                DynamicMapTileSource.defaultSource)
                            .urlTemplate,
                    userAgentPackageName: 'so.raad.mobile',
                    maxNativeZoom: 18,
                  ),
                  MarkerLayer(markers: markers),
                ],
              ),
              Positioned(
                top: 12,
                left: 16,
                right: 16,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (hasCriticalAlert && topAlert != null) ...[
                      InkWell(
                        onTap: () {
                          Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => AdminMultiCameraScreen(
                                vehicleId: topAlert.vehicleId,
                                plateNo: alertVehicle?.plateNo ?? 'Bus',
                                label: alertVehicle?.label,
                              ),
                            ),
                          );
                        },
                        borderRadius: BorderRadius.circular(12),
                        child: Container(
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 14,
                            vertical: 10,
                          ),
                          decoration: BoxDecoration(
                            color: RaadColors.red,
                            borderRadius: BorderRadius.circular(12),
                            boxShadow: const [
                              BoxShadow(
                                color: Colors.black26,
                                blurRadius: 8,
                                offset: Offset(0, 3),
                              ),
                            ],
                          ),
                          child: Row(
                            children: [
                              const Icon(
                                Icons.warning_amber_rounded,
                                color: Colors.white,
                                size: 22,
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment:
                                      CrossAxisAlignment.start,
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Text(
                                      s.notificationTitle(
                                        'system',
                                        'safety_alert',
                                        'Digniin Badbaado',
                                        alarmType: topAlert.alarmType,
                                      ),
                                      style: const TextStyle(
                                        color: Colors.white,
                                        fontWeight: FontWeight.w800,
                                        fontSize: 13,
                                      ),
                                    ),
                                    Text(
                                      '${alertVehicle?.label ?? alertVehicle?.plateNo ?? (topAlert.vehicleId.length > 8 ? topAlert.vehicleId.substring(0, 8) : topAlert.vehicleId)} · Taabo si aad u daawato',
                                      style: const TextStyle(
                                        color: Colors.white,
                                        fontSize: 11.5,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 8,
                                  vertical: 4,
                                ),
                                decoration: BoxDecoration(
                                  color: Colors.white,
                                  borderRadius: BorderRadius.circular(6),
                                ),
                                child: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    const Icon(
                                      Icons.videocam,
                                      size: 14,
                                      color: RaadColors.red,
                                    ),
                                    const SizedBox(width: 4),
                                    Text(
                                      s.watchVideo,
                                      style: const TextStyle(
                                        fontSize: 11,
                                        fontWeight: FontWeight.w700,
                                        color: RaadColors.red,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              const SizedBox(width: 4),
                              IconButton(
                                tooltip: s.adminResolveAlert,
                                icon: const Icon(
                                  Icons.close_rounded,
                                  color: Colors.white,
                                  size: 20,
                                ),
                                padding: EdgeInsets.zero,
                                constraints: const BoxConstraints(
                                  minWidth: 30,
                                  minHeight: 30,
                                ),
                                onPressed: () => _showAlertActionSheet(
                                  topAlert,
                                  alertVehicle,
                                  s,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 10,
                      ),
                      decoration: BoxDecoration(
                        color: Theme.of(context)
                            .colorScheme
                            .surface
                            .withValues(alpha: 0.95),
                        borderRadius: BorderRadius.circular(12),
                        boxShadow: const [
                          BoxShadow(
                            color: Colors.black12,
                            blurRadius: 8,
                            offset: Offset(0, 2),
                          ),
                        ],
                      ),
                      child: Row(
                        children: [
                          Container(
                            width: 10,
                            height: 10,
                            decoration: BoxDecoration(
                              color: onlineList.isEmpty
                                  ? Colors.grey
                                  : RaadColors.green,
                              shape: BoxShape.circle,
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              onlineList.isEmpty
                                  ? s.adminNoBusesOnRoad
                                  : '${onlineList.length} ${s.adminOnlineNow} · ${s.adminSelectBusToInspect}',
                              style: const TextStyle(
                                fontWeight: FontWeight.w600,
                                fontSize: 13,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              Positioned(
                bottom: 8,
                right: 8,
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  color: Colors.white70,
                  child: Text(
                    (ref.watch(activeMapTileSourceProvider).valueOrNull ??
                            DynamicMapTileSource.defaultSource)
                        .attribution,
                    style:
                        const TextStyle(fontSize: 10, color: Colors.black87),
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _VehicleActionSheet extends ConsumerStatefulWidget {
  final OnlineVehicle vehicle;
  final AdminVehicle? details;
  final String? driverName;

  const _VehicleActionSheet({
    required this.vehicle,
    required this.details,
    this.driverName,
  });

  @override
  ConsumerState<_VehicleActionSheet> createState() =>
      _VehicleActionSheetState();
}

class _VehicleActionSheetState extends ConsumerState<_VehicleActionSheet> {
  AdminDevice? _resolvedDevice;
  bool _isLoadingDevice = true;

  @override
  void initState() {
    super.initState();
    _loadDevice();
  }

  Future<void> _loadDevice() async {
    final dev = await ref
        .read(adminRepositoryProvider)
        .getVehicleActiveDevice(widget.vehicle.vehicleId);
    if (!mounted) return;
    setState(() {
      _resolvedDevice = dev;
      _isLoadingDevice = false;
    });
  }

  String? get _effectiveDeviceId =>
      widget.vehicle.deviceId ??
      _resolvedDevice?.id ??
      widget.details?.deviceId;

  Future<void> _showLinkDeviceDialog(Strings s) async {
    final devices = await ref.read(adminDevicesProvider.future);
    if (!mounted) return;

    if (devices.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(s.adminNoDeviceAttached)),
      );
      return;
    }

    String? selectedId = devices.first.id;

    await showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: Text(s.adminLinkDevice),
          content: DropdownButtonFormField<String>(
            initialValue: selectedId,
            items: [
              for (final d in devices)
                DropdownMenuItem(
                  value: d.id,
                  child: Text(
                    '${s.adminTerminalId}: ${d.terminalId} (${d.model ?? 'MDVR'})',
                  ),
                ),
            ],
            onChanged: (val) {
              setDialogState(() => selectedId = val);
            },
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: Text(s.cancel),
            ),
            FilledButton(
              onPressed: selectedId == null
                  ? null
                  : () async {
                      Navigator.pop(ctx);
                      try {
                        await ref
                            .read(adminRepositoryProvider)
                            .assignDevice(selectedId!, widget.vehicle.vehicleId);
                        if (!mounted) return;
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text(s.adminDeviceLinkedSuccess)),
                        );
                        _loadDevice();
                        ref.invalidate(adminFleetOnlineProvider);
                        ref.invalidate(adminVehiclesListProvider);
                      } catch (e) {
                        if (!mounted) return;
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text('${s.somethingWrong}: $e')),
                        );
                      }
                    },
              child: Text(s.adminLinkDevice),
            ),
          ],
        ),
      ),
    );
  }

  void _openMultiCameraScreen(Strings s) {
    final devId = _effectiveDeviceId;
    if (devId == null || devId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(s.adminNoDeviceLinkedMessage)),
      );
      return;
    }

    Navigator.of(context).pop(); // Close bottom sheet
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => AdminMultiCameraScreen(
          vehicleId: widget.vehicle.vehicleId,
          plateNo: widget.vehicle.plateNo,
          label: widget.vehicle.label,
          driverName: widget.driverName,
          speedKph: widget.vehicle.position?.speedKph,
          deviceId: devId,
          cameras: _resolvedDevice?.cameras ?? const [],
        ),
      ),
    );
  }

  String _formatSpeed(Strings s) {
    if (!widget.vehicle.isOnline) {
      return s.adminSpeedOffline;
    }
    final speed = widget.vehicle.position?.speedKph;
    if (speed == null || speed <= 0) {
      return s.adminSpeedStopped;
    }
    return s.adminSpeedMoving(speed.round());
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final theme = Theme.of(context);
    final hasDevice =
        _effectiveDeviceId != null && _effectiveDeviceId!.isNotEmpty;
    final isOnline = widget.vehicle.isOnline;
    final driverText = widget.driverName != null && widget.driverName!.isNotEmpty
        ? widget.driverName!
        : s.adminDriverUnassigned;

    return Container(
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
      ),
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Center(
            child: Container(
              width: 40,
              height: 4,
              margin: const EdgeInsets.only(bottom: 16),
              decoration: BoxDecoration(
                color: Colors.grey.withValues(alpha: 0.3),
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),

          // Header: Bus Icon, Plate, Online/Offline badge & Speed
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: isOnline
                      ? RaadColors.brandPrimary.withValues(alpha: 0.12)
                      : Colors.grey.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Icon(
                  Icons.directions_bus_rounded,
                  color: isOnline ? RaadColors.brandPrimary : const Color(0xFF64748B),
                  size: 28,
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      widget.vehicle.displayName,
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 18,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        Container(
                          width: 8,
                          height: 8,
                          decoration: BoxDecoration(
                            color: isOnline ? RaadColors.green : const Color(0xFF64748B),
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 6),
                        Text(
                          isOnline ? s.adminStatusOnline : s.adminStatusOffline,
                          style: TextStyle(
                            fontSize: 12.5,
                            fontWeight: FontWeight.w600,
                            color: isOnline ? RaadColors.green : const Color(0xFF64748B),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: isOnline
                                ? Colors.blue.withValues(alpha: 0.1)
                                : Colors.grey.withValues(alpha: 0.12),
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: Text(
                            _formatSpeed(s),
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                              color: isOnline ? Colors.blue : const Color(0xFF64748B),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),

          const SizedBox(height: 18),

          // Telemetry and Driver Info Card
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerLow,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(
                color: theme.colorScheme.outlineVariant.withValues(alpha: 0.4),
              ),
            ),
            child: Column(
              children: [
                Row(
                  children: [
                    const Icon(Icons.person_rounded,
                        size: 20, color: RaadColors.brandPrimary),
                    const SizedBox(width: 10),
                    Text(
                      '${s.adminDriverLabel}:',
                      style: TextStyle(fontSize: 13, color: context.muted),
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        driverText,
                        style: const TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w600,
                        ),
                        textAlign: TextAlign.end,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),

          const SizedBox(height: 16),

          if (!isOnline) ...[
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFF64748B).withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: const Color(0xFF64748B).withValues(alpha: 0.25),
                ),
              ),
              child: Row(
                children: [
                  const Icon(Icons.info_outline_rounded,
                      color: Color(0xFF64748B), size: 20),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      s.adminOfflineBusNotice,
                      style: const TextStyle(
                        fontSize: 12,
                        color: Color(0xFF64748B),
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),
          ],

          if (_isLoadingDevice)
            const Center(
              child: Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: CircularProgressIndicator(),
              ),
            )
          else if (!hasDevice) ...[
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: Colors.amber.withValues(alpha: 0.1),
                border: Border.all(color: Colors.amber.withValues(alpha: 0.3)),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(
                children: [
                  const Icon(Icons.warning_amber_rounded, color: Colors.amber),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      s.adminNoDeviceAttached,
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                  TextButton.icon(
                    icon: const Icon(Icons.link_rounded, size: 18),
                    label: Text(s.adminLinkDevice),
                    onPressed: () => _showLinkDeviceDialog(s),
                  ),
                ],
              ),
            ),
          ] else ...[
            // Primary Full-Width Action: Daawo Kaamirooyinka (Live Videos)
            FilledButton.icon(
              style: FilledButton.styleFrom(
                backgroundColor: RaadColors.brandPrimary,
                padding: const EdgeInsets.symmetric(vertical: 15),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
              icon: const Icon(Icons.videocam_rounded, size: 22),
              label: Text(
                s.adminWatchLiveVideos,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                ),
              ),
              onPressed: () => _openMultiCameraScreen(s),
            ),
          ],
        ],
      ),
    );
  }
}
