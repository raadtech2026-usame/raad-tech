import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

import '../../core/l10n/strings.dart';
import '../../shared/widgets.dart';
import '../video/flv_relay_bridge.dart';
import '../video/intercom_service.dart';
import 'admin_data.dart';

/// Multi-Camera CCTV Video Wall + Integrated Two-Way Intercom Screen.
///
/// Automatically mounts and streams all connected camera channels simultaneously
/// using the lightweight sub-stream (`stream_type: "sub"` per ADR-0043) for minimum
/// cellular bandwidth and zero lag.
///
/// Features docked two-way Push-to-Talk intercom at the bottom so the Org Admin
/// can view all camera angles while communicating directly with the driver.
class AdminMultiCameraScreen extends ConsumerStatefulWidget {
  final String vehicleId;
  final String plateNo;
  final String? label;
  final String? driverName;
  final double? speedKph;
  final String? deviceId;
  final List<DeviceCamera> cameras;

  const AdminMultiCameraScreen({
    super.key,
    required this.vehicleId,
    required this.plateNo,
    this.label,
    this.driverName,
    this.speedKph,
    this.deviceId,
    this.cameras = const [],
  });

  @override
  ConsumerState<AdminMultiCameraScreen> createState() =>
      _AdminMultiCameraScreenState();
}

class _AdminMultiCameraScreenState
    extends ConsumerState<AdminMultiCameraScreen> {
  late final IntercomController _intercomController;
  bool _isIntercomConnecting = false;
  bool _isIntercomActive = false;
  String? _intercomSessionId;
  String? _intercomError;

  // Single focused camera channel if tapped (null = 2x2 grid)
  int? _focusedCameraIndex;

  @override
  void initState() {
    super.initState();
    _intercomController = IntercomController(
      onPhaseChanged: (phase) {
        if (!mounted) return;
        setState(() {});
      },
      onError: (err) {
        if (!mounted) return;
        setState(() => _intercomError = err);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(err), backgroundColor: RaadColors.red),
        );
      },
    );
  }

  @override
  void dispose() {
    _endIntercom();
    super.dispose();
  }

  Future<void> _startIntercom(Strings s) async {
    final devId = widget.deviceId;
    if (devId == null || devId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(s.adminNoDeviceLinkedMessage)),
      );
      return;
    }

    final cameraId = widget.cameras.isNotEmpty
        ? widget.cameras.first.id
        : '01CAMERA000000000000000A';

    setState(() {
      _isIntercomConnecting = true;
      _intercomError = null;
    });

    try {
      final res = await ref.read(adminRepositoryProvider).requestIntercom(
            deviceId: devId,
            cameraId: cameraId,
          );
      if (!mounted) return;

      final sessionId = res['id'] as String?;
      final streamUrl = res['stream_url'] as String?;
      final uplinkUrl = res['uplink_url'] as String?;

      await _intercomController.connect(
        streamUrl: streamUrl,
        uplinkUrl: uplinkUrl,
      );

      if (!mounted) return;
      setState(() {
        _isIntercomConnecting = false;
        _isIntercomActive = true;
        _intercomSessionId = sessionId;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _isIntercomConnecting = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${s.somethingWrong}: $e')),
      );
    }
  }

  Future<void> _endIntercom() async {
    await _intercomController.disconnect();
    if (_intercomSessionId != null) {
      final id = _intercomSessionId!;
      _intercomSessionId = null;
      try {
        await ref.read(adminRepositoryProvider).stopVideoSession(id);
      } catch (_) {}
    }
    if (mounted) {
      setState(() {
        _isIntercomActive = false;
        _isIntercomConnecting = false;
      });
    }
  }

  String _formatSpeed(Strings s) {
    final speed = widget.speedKph;
    if (speed == null || speed <= 0) {
      return s.adminSpeedStopped;
    }
    return s.adminSpeedMoving(speed.round());
  }

  String _channelLabel(int index, Strings s) {
    switch (index) {
      case 0:
        return 'Ch 1 · ${s.adminFrontCamera}';
      case 1:
        return 'Ch 2 · ${s.adminCabinCamera}';
      case 2:
        return 'Ch 3 · ${s.adminDoorCamera}';
      case 3:
        return 'Ch 4 · ${s.adminRearCamera}';
      default:
        return s.adminCameraChannel(index + 1);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final vehicleTitle = widget.label != null && widget.label!.isNotEmpty
        ? '${widget.plateNo} — ${widget.label}'
        : widget.plateNo;
    final driverText = widget.driverName != null && widget.driverName!.isNotEmpty
        ? widget.driverName!
        : s.adminDriverUnassigned;

    // Use reported cameras or fallback to standard 4 channels
    final activeChannels = widget.cameras.isNotEmpty
        ? widget.cameras.map((c) => c.id).toList()
        : ['camera_1', 'camera_2', 'camera_3', 'camera_4'];

    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        backgroundColor: const Color(0xFF1E293B),
        foregroundColor: Colors.white,
        titleSpacing: 0,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  vehicleTitle,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: RaadColors.green.withOpacity(0.2),
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(color: RaadColors.green, width: 0.8),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 6,
                        height: 6,
                        decoration: const BoxDecoration(
                          color: RaadColors.green,
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 4),
                      const Text(
                        'LIVE',
                        style: TextStyle(
                          color: RaadColors.green,
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 2),
            Text(
              '${s.adminDriverLabel}: $driverText  •  ${_formatSpeed(s)}',
              style: TextStyle(fontSize: 12, color: Colors.grey[400]),
            ),
          ],
        ),
        actions: [
          if (_focusedCameraIndex != null)
            IconButton(
              tooltip: 'Grid view',
              icon: const Icon(Icons.grid_view_rounded),
              onPressed: () => setState(() => _focusedCameraIndex = null),
            ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: widget.deviceId == null || widget.deviceId!.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24.0),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(Icons.videocam_off_rounded,
                              size: 56, color: Colors.grey),
                          const SizedBox(height: 12),
                          Text(
                            s.adminNoDeviceLinkedMessage,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 16,
                              fontWeight: FontWeight.w600,
                            ),
                            textAlign: TextAlign.center,
                          ),
                        ],
                      ),
                    ),
                  )
                : _focusedCameraIndex != null
                    ? _CameraStreamTile(
                        key: ValueKey('focused_$_focusedCameraIndex'),
                        deviceId: widget.deviceId!,
                        cameraId: activeChannels[_focusedCameraIndex!],
                        channelLabel: _channelLabel(_focusedCameraIndex!, s),
                        isFocused: true,
                        onTap: () => setState(() => _focusedCameraIndex = null),
                      )
                    : GridView.builder(
                        padding: const EdgeInsets.all(8),
                        itemCount: activeChannels.length,
                        gridDelegate:
                            const SliverGridDelegateWithFixedCrossAxisCount(
                          crossAxisCount: 2,
                          crossAxisSpacing: 8,
                          mainAxisSpacing: 8,
                          childAspectRatio: 1.3,
                        ),
                        itemBuilder: (context, index) {
                          return _CameraStreamTile(
                            key: ValueKey('ch_$index'),
                            deviceId: widget.deviceId!,
                            cameraId: activeChannels[index],
                            channelLabel: _channelLabel(index, s),
                            isFocused: false,
                            onTap: () =>
                                setState(() => _focusedCameraIndex = index),
                          );
                        },
                      ),
          ),
          _buildIntercomBottomBar(context, s),
        ],
      ),
    );
  }

  Widget _buildIntercomBottomBar(BuildContext context, Strings s) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
      decoration: const BoxDecoration(
        color: Color(0xFF1E293B),
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
        boxShadow: [
          BoxShadow(
            color: Colors.black45,
            offset: Offset(0, -3),
            blurRadius: 8,
          ),
        ],
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_isIntercomActive) ...[
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Container(
                    width: 10,
                    height: 10,
                    decoration: BoxDecoration(
                      color: _intercomController.isTransmitting
                          ? RaadColors.red
                          : RaadColors.green,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    _intercomController.isTransmitting
                        ? s.adminTransmitting
                        : s.adminListening,
                    style: TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 14,
                      color: _intercomController.isTransmitting
                          ? RaadColors.red
                          : RaadColors.green,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: GestureDetector(
                      onTapDown: (_) => _intercomController.startTalking(),
                      onTapUp: (_) => _intercomController.stopTalking(),
                      onTapCancel: () => _intercomController.stopTalking(),
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        decoration: BoxDecoration(
                          color: _intercomController.isTransmitting
                              ? RaadColors.red
                              : RaadColors.brandPrimary,
                          borderRadius: BorderRadius.circular(12),
                          boxShadow: [
                            BoxShadow(
                              color: (_intercomController.isTransmitting
                                      ? RaadColors.red
                                      : RaadColors.brandPrimary)
                                  .withOpacity(0.4),
                              blurRadius: 8,
                              offset: const Offset(0, 2),
                            ),
                          ],
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              _intercomController.isTransmitting
                                  ? Icons.mic_rounded
                                  : Icons.mic_none_rounded,
                              color: Colors.white,
                              size: 24,
                            ),
                            const SizedBox(width: 8),
                            Text(
                              _intercomController.isTransmitting
                                  ? s.adminTransmitting
                                  : s.adminHoldToTalk,
                              style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.bold,
                                fontSize: 15,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  IconButton.filled(
                    style: IconButton.filledStyleFrom(
                      backgroundColor: RaadColors.red.withOpacity(0.2),
                      foregroundColor: RaadColors.red,
                      padding: const EdgeInsets.all(12),
                    ),
                    icon: const Icon(Icons.call_end_rounded),
                    tooltip: s.adminIntercomDisconnect,
                    onPressed: _endIntercom,
                  ),
                ],
              ),
            ] else ...[
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  style: FilledButton.styleFrom(
                    backgroundColor: RaadColors.brandPrimary,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  icon: _isIntercomConnecting
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.record_voice_over_rounded, size: 22),
                  label: Text(
                    _isIntercomConnecting
                        ? s.adminIntercomConnecting
                        : s.adminIntercomTalkToDriver,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  onPressed:
                      _isIntercomConnecting ? null : () => _startIntercom(s),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Independent video player tile connecting to a single camera channel.
/// Always requests the low-bandwidth `stream_type: "sub"` per ADR-0043.
class _CameraStreamTile extends ConsumerStatefulWidget {
  final String deviceId;
  final String cameraId;
  final String channelLabel;
  final bool isFocused;
  final VoidCallback onTap;

  const _CameraStreamTile({
    super.key,
    required this.deviceId,
    required this.cameraId,
    required this.channelLabel,
    required this.isFocused,
    required this.onTap,
  });

  @override
  ConsumerState<_CameraStreamTile> createState() => _CameraStreamTileState();
}

class _CameraStreamTileState extends ConsumerState<_CameraStreamTile> {
  final _bridge = FlvRelayBridge();
  Player? _player;
  VideoController? _controller;
  bool _isConnecting = true;
  String? _sessionId;
  String? _error;

  @override
  void initState() {
    super.initState();
    _startStream();
  }

  Future<void> _startStream() async {
    setState(() {
      _isConnecting = true;
      _error = null;
    });

    try {
      // ADR-0043: Request lightweight sub-stream
      final res = await ref.read(adminRepositoryProvider).requestLiveVideo(
            deviceId: widget.deviceId,
            cameraId: widget.cameraId,
            streamType: 'sub',
          );
      if (!mounted) return;

      final sessionId = res['id'] as String?;
      final streamUrl = res['stream_url'] as String?;
      _sessionId = sessionId;

      if (streamUrl == null || streamUrl.isEmpty) {
        throw Exception('No stream URL returned');
      }

      final localUrl = await _bridge.start(streamUrl);
      final player = Player();
      final controller = VideoController(player);
      _player = player;
      _controller = controller;

      await player.open(Media(localUrl));
      if (!mounted) return;
      setState(() => _isConnecting = false);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _isConnecting = false;
        _error = e.toString();
      });
    }
  }

  @override
  void dispose() {
    if (_sessionId != null) {
      final id = _sessionId!;
      ref.read(adminRepositoryProvider).stopVideoSession(id).then(
            (_) {},
            onError: (_) {},
          );
    }
    _bridge.stop();
    _player?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: widget.onTap,
      child: Container(
        decoration: BoxDecoration(
          color: const Color(0xFF020617),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: widget.isFocused
                ? RaadColors.brandPrimary
                : const Color(0xFF334155),
            width: widget.isFocused ? 2 : 1,
          ),
        ),
        clipBehavior: Clip.antiAlias,
        child: Stack(
          fit: StackFit.expand,
          children: [
            if (_controller != null && !_isConnecting && _error == null)
              Video(controller: _controller!)
            else if (_isConnecting)
              const Center(
                child: SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: RaadColors.brandPrimary,
                  ),
                ),
              )
            else if (_error != null)
              Center(
                child: Padding(
                  padding: const EdgeInsets.all(8.0),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.signal_cellular_connected_no_internet_0_bar,
                          size: 28, color: Colors.grey),
                      const SizedBox(height: 4),
                      Text(
                        widget.channelLabel,
                        style: const TextStyle(
                          color: Colors.grey,
                          fontSize: 11,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 2),
                      const Text(
                        'Offline',
                        style: TextStyle(color: Colors.grey, fontSize: 10),
                      ),
                    ],
                  ),
                ),
              ),

            // Top overlay with channel name & status badge
            Positioned(
              top: 6,
              left: 6,
              right: 6,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: Colors.black.withOpacity(0.65),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      widget.channelLabel,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 10,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  if (!_isConnecting && _error == null)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 4, vertical: 2),
                      decoration: BoxDecoration(
                        color: RaadColors.green.withOpacity(0.8),
                        borderRadius: BorderRadius.circular(3),
                      ),
                      child: const Text(
                        'SUB',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 8,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
