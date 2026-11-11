import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../../core/l10n/strings.dart';
import '../../shared/widgets.dart';
import '../map/bus_map.dart';
import '../video/video_player_screen.dart';
import '../video/video_providers.dart';
import 'admin_data.dart';
import 'admin_screens.dart';

/// Pillar 2: Live Tracking, Live Video & Two-Way Intercom.
/// Displays an interactive map of all active/online buses.
/// Tapping a bus opens an action panel with telemetry, live camera, and two-way intercom.
class AdminFleetMapScreen extends ConsumerStatefulWidget {
  const AdminFleetMapScreen({super.key});

  @override
  ConsumerState<AdminFleetMapScreen> createState() => _AdminFleetMapScreenState();
}

class _AdminFleetMapScreenState extends ConsumerState<AdminFleetMapScreen> {
  final _mapController = MapController();

  // Default coordinate for Mogadishu/Somalia center when no vehicles report yet
  static const _defaultCenter = LatLng(2.0469, 45.3182);

  @override
  void dispose() {
    _mapController.dispose();
    super.dispose();
  }

  void _inspectVehicle(OnlineVehicle vehicle, AdminVehicle? details) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => _VehicleActionSheet(
        vehicle: vehicle,
        details: details,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final fleetAsync = ref.watch(adminFleetOnlineProvider);
    final vehiclesAsync = ref.watch(adminVehiclesListProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(s.adminFleetMapTitle),
        actions: adminTopActions(
          context,
          ref,
          onRefresh: () {
            ref.invalidate(adminFleetOnlineProvider);
            ref.invalidate(adminVehiclesListProvider);
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
                onPressed: () => ref.invalidate(adminFleetOnlineProvider),
                child: Text(s.retry),
              ),
            ],
          ),
        ),
        data: (fleet) {
          final onlineList = fleet.vehicles;
          final vehicleMap = {
            for (final v in (vehiclesAsync.valueOrNull ?? <AdminVehicle>[])) v.id: v
          };

          // Find first valid vehicle position or fallback to default center
          LatLng center = _defaultCenter;
          for (final v in onlineList) {
            if (v.position != null) {
              center = LatLng(v.position!.latitude, v.position!.longitude);
              break;
            }
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
                  MarkerLayer(
                    markers: [
                      for (int i = 0; i < onlineList.length; i++)
                        Marker(
                          point: onlineList[i].position != null
                              ? LatLng(
                                  onlineList[i].position!.latitude,
                                  onlineList[i].position!.longitude,
                                )
                              : LatLng(
                                  _defaultCenter.latitude + (i * 0.008) - 0.004,
                                  _defaultCenter.longitude + (i * 0.008) - 0.004,
                                ),
                          width: 52,
                          height: 52,
                          child: GestureDetector(
                            onTap: () => _inspectVehicle(
                              onlineList[i],
                              vehicleMap[onlineList[i].vehicleId],
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
                    ],
                  ),
                ],
              ),
              Positioned(
                top: 12,
                left: 16,
                right: 16,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: Theme.of(context).colorScheme.surface.withValues(alpha: 0.95),
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
                          color: onlineList.isEmpty ? Colors.grey : RaadColors.green,
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          onlineList.isEmpty
                              ? s.adminNoBusesOnRoad
                              : '${onlineList.length} ${s.adminOnlineNow} · ${s.adminSelectBusToInspect}',
                          style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
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

  const _VehicleActionSheet({
    required this.vehicle,
    required this.details,
  });

  @override
  ConsumerState<_VehicleActionSheet> createState() => _VehicleActionSheetState();
}

class _VehicleActionSheetState extends ConsumerState<_VehicleActionSheet> {
  bool _isIntercomActive = false;
  bool _isConnecting = false;
  String? _sessionId;
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
                  child: Text('${s.adminTerminalId}: ${d.terminalId} (${d.model ?? 'MDVR'})'),
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

  Future<void> _startIntercom(Strings s) async {
    final deviceId = _effectiveDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(s.adminNoDeviceLinked)),
      );
      return;
    }

    final cameraId = (_resolvedDevice?.cameras.isNotEmpty == true)
        ? _resolvedDevice!.cameras.first.id
        : '01CAMERA000000000000000A';

    setState(() {
      _isConnecting = true;
    });

    try {
      final res = await ref.read(adminRepositoryProvider).requestIntercom(
            deviceId: deviceId,
            cameraId: cameraId,
          );
      if (!mounted) return;
      setState(() {
        _isConnecting = false;
        _isIntercomActive = true;
        _sessionId = res['id'] as String?;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _isConnecting = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${s.somethingWrong}: $e')),
      );
    }
  }

  Future<void> _endIntercom() async {
    if (_sessionId != null) {
      await ref.read(adminRepositoryProvider).stopVideoSession(_sessionId!);
    }
    if (!mounted) return;
    setState(() {
      _isIntercomActive = false;
      _sessionId = null;
    });
  }

  Future<void> _watchLiveVideo(Strings s, {String? selectedCameraId}) async {
    final deviceId = _effectiveDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(s.adminNoDeviceLinked)),
      );
      return;
    }

    final cameraId = selectedCameraId ??
        ((_resolvedDevice?.cameras.isNotEmpty == true)
            ? _resolvedDevice!.cameras.first.id
            : '01CAMERA000000000000000A');

    try {
      final session = await ref.read(videoRepositoryProvider).requestLive(
        deviceId: deviceId,
        cameraId: cameraId,
      );
      if (!mounted) return;
      if (session.streamUrl != null) {
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => VideoPlayerScreen(
              videoSessionId: session.id,
              relayStreamUrl: session.streamUrl!,
            ),
          ),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${s.somethingWrong}: $e')),
      );
    }
  }

  Widget _buildCameraWall(BuildContext context, Strings s) {
    final cameras = (_resolvedDevice?.cameras.isNotEmpty == true)
        ? _resolvedDevice!.cameras
        : const [
            DeviceCamera(
              id: '01CAMERA000000000000000A',
              channelNo: 1,
              label: 'Hore (Waddada)',
              position: 'front',
            ),
            DeviceCamera(
              id: '01CAMERA000000000000000B',
              channelNo: 2,
              label: 'Gudaha Baska',
              position: 'cabin',
            ),
            DeviceCamera(
              id: '01CAMERA000000000000000C',
              channelNo: 3,
              label: 'Dhabarka (Rear)',
              position: 'rear',
            ),
            DeviceCamera(
              id: '01CAMERA000000000000000D',
              channelNo: 4,
              label: 'Albaabka (Door)',
              position: 'door',
            ),
          ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              'Kaamirooyinka Baska (${cameras.length} CH)',
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
            ),
            Text(
              'Taabo si aad toos ugu daawato',
              style: TextStyle(fontSize: 12, color: context.muted),
            ),
          ],
        ),
        const SizedBox(height: 10),
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 2,
            crossAxisSpacing: 10,
            mainAxisSpacing: 10,
            childAspectRatio: 2.3,
          ),
          itemCount: cameras.length,
          itemBuilder: (ctx, idx) {
            final cam = cameras[idx];
            return InkWell(
              borderRadius: BorderRadius.circular(12),
              onTap: () => _watchLiveVideo(s, selectedCameraId: cam.id),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                decoration: BoxDecoration(
                  color: RaadColors.brandPrimary.withValues(alpha: 0.08),
                  border: Border.all(
                    color: RaadColors.brandPrimary.withValues(alpha: 0.25),
                  ),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(6),
                      decoration: const BoxDecoration(
                        color: RaadColors.brandPrimary,
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(
                        Icons.videocam_rounded,
                        color: Colors.white,
                        size: 16,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            'CH ${cam.channelNo}',
                            style: const TextStyle(
                              fontWeight: FontWeight.bold,
                              fontSize: 12.5,
                              color: RaadColors.brandPrimary,
                            ),
                          ),
                          Text(
                            cam.label ?? 'Kaamero ${cam.channelNo}',
                            style: const TextStyle(fontSize: 11),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final theme = Theme.of(context);
    final hasDevice = _effectiveDeviceId != null && _effectiveDeviceId!.isNotEmpty;
    final speed = widget.vehicle.position?.speedKph;

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
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: RaadColors.brandPrimary.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: const Icon(
                  Icons.directions_bus_rounded,
                  color: RaadColors.brandPrimary,
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
                      style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
                    ),
                    const SizedBox(height: 2),
                    Row(
                      children: [
                        Container(
                          width: 8,
                          height: 8,
                          decoration: const BoxDecoration(
                            color: RaadColors.green,
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 6),
                        Text(
                          s.adminOnlineNow,
                          style: TextStyle(fontSize: 13, color: context.muted),
                        ),
                        if (speed != null) ...[
                          const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                            decoration: BoxDecoration(
                              color: Colors.blue.withValues(alpha: 0.1),
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Text(
                              '${speed.toStringAsFixed(0)} km/h',
                              style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.blue),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          if (_isLoadingDevice)
            const Center(child: Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: CircularProgressIndicator(),
            ))
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
                      style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
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
          ] else if (_isIntercomActive) ...[
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: RaadColors.green.withValues(alpha: 0.1),
                border: Border.all(color: RaadColors.green.withValues(alpha: 0.3)),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.mic_rounded, color: RaadColors.green, size: 24),
                      const SizedBox(width: 8),
                      Text(
                        s.adminIntercomConnected,
                        style: const TextStyle(fontWeight: FontWeight.bold, color: RaadColors.green),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  FilledButton.icon(
                    style: FilledButton.styleFrom(
                      backgroundColor: RaadColors.red,
                      foregroundColor: Colors.white,
                    ),
                    icon: const Icon(Icons.call_end_rounded),
                    label: Text(s.adminIntercomDisconnect),
                    onPressed: _endIntercom,
                  ),
                ],
              ),
            ),
          ] else ...[
            _buildCameraWall(context, s),
            const SizedBox(height: 14),
            OutlinedButton.icon(
              icon: _isConnecting
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.record_voice_over_rounded),
              label: Text(
                _isConnecting
                    ? s.adminIntercomConnecting
                    : s.adminIntercomTalkToDriver,
              ),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 13),
              ),
              onPressed: _isConnecting ? null : () => _startIntercom(s),
            ),
          ],
        ],
      ),
    );
  }
}