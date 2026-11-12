import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../../core/l10n/strings.dart';
import '../../shared/widgets.dart';
import '../map/bus_map.dart';
import 'admin_data.dart';
import 'admin_multi_camera_screen.dart';
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

  // Cache of last known positions for vehicles (so offline buses remain visible)
  final Map<String, OnlineVehiclePosition> _lastKnownPositions = {};
  final Set<String> _requestedLatestPositions = {};

  @override
  void dispose() {
    _mapController.dispose();
    super.dispose();
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

    return Scaffold(
      appBar: AppBar(
        title: Text(s.adminFleetMapTitle),
        actions: adminTopActions(
          context,
          ref,
          onRefresh: () {
            ref.invalidate(adminFleetOnlineProvider);
            ref.invalidate(adminVehiclesListProvider);
            ref.invalidate(adminBoardProvider);
          },
        ),
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

          // Cache positions from online vehicles
          final onlineIds = <String>{};
          for (final v in onlineList) {
            onlineIds.add(v.vehicleId);
            if (v.position != null) {
              _lastKnownPositions[v.vehicleId] = v.position!;
            }
          }

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

          // 1. Online bus markers
          for (int i = 0; i < onlineList.length; i++) {
            final v = onlineList[i];
            final pos = v.position ?? _lastKnownPositions[v.vehicleId];
            final point = pos != null
                ? LatLng(pos.latitude, pos.longitude)
                : LatLng(
                    _defaultCenter.latitude + (i * 0.008) - 0.004,
                    _defaultCenter.longitude + (i * 0.008) - 0.004,
                  );

            markers.add(
              Marker(
                point: point,
                width: 52,
                height: 52,
                child: GestureDetector(
                  onTap: () => _inspectVehicle(
                    vehicle: v,
                    details: vehicleMap[v.vehicleId],
                    driverName: vehicleDriverMap[v.vehicleId],
                  ),
                  child: Container(
                    decoration: BoxDecoration(
                      color: RaadColors.brandPrimary,
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 2.5),
                      boxShadow: const [
                        BoxShadow(
                          color: Colors.black26,
                          blurRadius: 6,
                          offset: Offset(0, 3),
                        ),
                      ],
                    ),
                    child: const Icon(
                      Icons.directions_bus_rounded,
                      color: Colors.white,
                      size: 26,
                    ),
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
                width: 48,
                height: 48,
                child: GestureDetector(
                  onTap: () => _inspectVehicle(
                    vehicle: offlineVehicle,
                    details: v,
                    driverName: vehicleDriverMap[v.id],
                  ),
                  child: Container(
                    decoration: BoxDecoration(
                      color: const Color(0xFF64748B), // Slate grey for offline
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 2),
                      boxShadow: const [
                        BoxShadow(
                          color: Colors.black26,
                          blurRadius: 4,
                          offset: Offset(0, 2),
                        ),
                      ],
                    ),
                    child: const Icon(
                      Icons.directions_bus_rounded,
                      color: Colors.white70,
                      size: 22,
                    ),
                  ),
                ),
              ),
            );
          }

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
                    urlTemplate: const MapboxTileSource().urlTemplate,
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
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
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
                if (_resolvedDevice != null) ...[
                  const Divider(height: 16),
                  Row(
                    children: [
                      const Icon(Icons.developer_board_rounded,
                          size: 20, color: RaadColors.brandPrimary),
                      const SizedBox(width: 10),
                      Text(
                        '${s.adminTerminalId}:',
                        style: TextStyle(fontSize: 13, color: context.muted),
                      ),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          _resolvedDevice!.terminalId,
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
