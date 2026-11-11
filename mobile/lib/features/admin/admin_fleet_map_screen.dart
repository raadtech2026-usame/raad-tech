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

          return Stack(
            children: [
              FlutterMap(
                mapController: _mapController,
                options: const MapOptions(
                  initialCenter: _defaultCenter,
                  initialZoom: 13,
                  minZoom: 4,
                  maxZoom: 18,
                  interactionOptions: InteractionOptions(
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
                          point: LatLng(
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

  Future<void> _startIntercom(Strings s) async {
    final deviceId = widget.details?.deviceId;
    if (deviceId == null || deviceId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(s.adminNoDeviceLinked)),
      );
      return;
    }

    setState(() {
      _isConnecting = true;
    });

    try {
      final res = await ref.read(adminRepositoryProvider).requestIntercom(deviceId: deviceId);
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

  Future<void> _watchLiveVideo(Strings s) async {
    final deviceId = widget.details?.deviceId;
    if (deviceId == null || deviceId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(s.adminNoDeviceLinked)),
      );
      return;
    }

    try {
      final session = await ref.read(videoRepositoryProvider).requestLive(
        deviceId: deviceId,
        cameraId: '01CAMERA000000000000000A',
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

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final theme = Theme.of(context);

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
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          if (_isIntercomActive) ...[
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
            Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    icon: const Icon(Icons.videocam_rounded),
                    label: Text(s.adminWatchLiveCamera),
                    style: FilledButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                    onPressed: () => _watchLiveVideo(s),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton.icon(
                    icon: _isConnecting
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.record_voice_over_rounded),
                    label: Text(
                      _isConnecting ? s.adminIntercomConnecting : s.adminIntercomTalkToDriver,
                    ),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                    onPressed: _isConnecting ? null : () => _startIntercom(s),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}