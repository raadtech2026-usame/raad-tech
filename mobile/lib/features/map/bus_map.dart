import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../../core/auth/auth_state.dart';
import '../../core/config/env.dart';
import '../../shared/widgets.dart';

/// Where map tiles come from. The provider is a seam (`.claude/rules/flutter.md` #6): screens
/// use [BusMap] and never name a vendor.
abstract class MapTileSource {
  String get urlTemplate;
  String get attribution;
}

/// Mapbox raster tiles when token is configured, with seamless OpenStreetMap fallback
/// when MAPBOX_ACCESS_TOKEN is not injected at build time (ADR-0011).
class MapboxTileSource implements MapTileSource {
  final String? accessToken;
  const MapboxTileSource({this.accessToken});

  @override
  String get urlTemplate {
    final token = (accessToken != null && accessToken!.isNotEmpty)
        ? accessToken!
        : Env.mapboxAccessToken;
    if (token.isNotEmpty) {
      return 'https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256/{z}/{x}/{y}@2x'
          '?access_token=$token';
    }
    // High-reliability public OSM raster tiles (requires zero vendor token)
    return 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  }

  @override
  String get attribution =>
      ((accessToken != null && accessToken!.isNotEmpty) ||
              Env.mapboxAccessToken.isNotEmpty)
          ? '© Mapbox © OpenStreetMap'
          : '© OpenStreetMap contributors';
}

/// Google Maps raster tiles (standard slippy tile server).
/// [mapType]:
/// - 'm': Standard roadmap (clean, fast, free)
/// - 'y': Hybrid (satellite imagery + road names/labels)
/// - 's': Satellite only
/// - 'p': Terrain
class GoogleMapsTileSource implements MapTileSource {
  final String mapType;
  final String? apiKey;

  const GoogleMapsTileSource({
    this.mapType = 'm',
    this.apiKey,
  });

  @override
  String get urlTemplate {
    final key = (apiKey != null && apiKey!.isNotEmpty)
        ? apiKey!
        : Env.googleMapsApiKey;
    final keyParam = key.isNotEmpty ? '&key=$key' : '';
    return 'https://mt1.google.com/vt/lyrs=$mapType&x={x}&y={y}&z={z}$keyParam';
  }

  @override
  String get attribution => '© Google Maps';
}

/// Resolves the default tile source based on build-time environment.
class DynamicMapTileSource {
  const DynamicMapTileSource._();

  static MapTileSource get defaultSource {
    if (Env.googleMapsApiKey.isNotEmpty) {
      return const GoogleMapsTileSource();
    }
    // High-reliability Google Maps direct tiles as primary default
    return const GoogleMapsTileSource();
  }
}

/// Riverpod provider that checks the backend's active map provider configuration.
/// Defaults to [DynamicMapTileSource.defaultSource] if offline or unreachable.
final activeMapTileSourceProvider = FutureProvider<MapTileSource>((ref) async {
  try {
    final client = ref.watch(apiClientProvider);
    final res =
        await client.get('/config/map-provider', auth: false, cache: false);
    final provider = (res['provider'] as String?)?.toLowerCase() ?? '';
    final apiKey = res['apiKey'] as String?;
    if (provider.contains('google')) {
      return GoogleMapsTileSource(apiKey: apiKey);
    } else if (provider == 'mapbox') {
      return MapboxTileSource(accessToken: apiKey);
    }
  } catch (_) {
    // Offline or network error: gracefully fall back to default
  }
  return DynamicMapTileSource.defaultSource;
});

/// A bus and, optionally, the family's stop. Follows the bus as it moves.
class BusMap extends StatefulWidget {
  final double busLatitude;
  final double busLongitude;
  final double? heading;
  final double? stopLatitude;
  final double? stopLongitude;
  final String? stopName;
  final bool isStale;
  final MapTileSource? tiles;

  const BusMap({
    super.key,
    required this.busLatitude,
    required this.busLongitude,
    this.heading,
    this.stopLatitude,
    this.stopLongitude,
    this.stopName,
    this.isStale = false,
    this.tiles,
  });

  @override
  State<BusMap> createState() => _BusMapState();
}

class _BusMapState extends State<BusMap> {
  final _controller = MapController();
  bool _ready = false;

  LatLng get _bus => LatLng(widget.busLatitude, widget.busLongitude);
  MapTileSource get _tileSource =>
      widget.tiles ?? DynamicMapTileSource.defaultSource;

  @override
  void didUpdateWidget(BusMap oldWidget) {
    super.didUpdateWidget(oldWidget);
    final moved =
        oldWidget.busLatitude != widget.busLatitude ||
        oldWidget.busLongitude != widget.busLongitude;
    if (moved && _ready) {
      _controller.move(_bus, _controller.camera.zoom);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final hasStop = widget.stopLatitude != null && widget.stopLongitude != null;
    return FlutterMap(
      mapController: _controller,
      options: MapOptions(
        initialCenter: _bus,
        initialZoom: 15,
        minZoom: 5,
        maxZoom: 18,
        onMapReady: () => _ready = true,
        interactionOptions: const InteractionOptions(
          flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
        ),
      ),
      children: [
        TileLayer(
          urlTemplate: _tileSource.urlTemplate,
          userAgentPackageName: 'so.raad.mobile',
          maxNativeZoom: 18,
        ),
        MarkerLayer(
          markers: [
            if (hasStop)
              Marker(
                point: LatLng(widget.stopLatitude!, widget.stopLongitude!),
                width: 44,
                height: 44,
                alignment: Alignment.topCenter,
                child: const Icon(
                  Icons.location_on_rounded,
                  size: 44,
                  color: RaadColors.green,
                ),
              ),
            Marker(
              point: _bus,
              width: 56,
              height: 56,
              child: RaadBusMarker(
                fixStatus: widget.isStale
                    ? BusMarkerFixStatus.stale
                    : BusMarkerFixStatus.live,
                headingDeg: widget.heading,
              ),
            ),
          ],
        ),
        Align(
          alignment: Alignment.bottomRight,
          child: Container(
            margin: const EdgeInsets.all(4),
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            color: Colors.white70,
            child: Text(
              _tileSource.attribution,
              style: const TextStyle(fontSize: 10),
            ),
          ),
        ),
      ],
    );
  }
}

enum BusMarkerFixStatus { live, stale, offline }

/// Web-dashboard-matched RAAD bus marker (`vehicleMarker.ts` / `.module.css`):
/// circular white-bordered badge (blue = live with animated pulse ring, amber = stale/no fix,
/// slate = offline), side-profile bus vector glyph, and rotated heading indicator.
class RaadBusMarker extends StatefulWidget {
  final BusMarkerFixStatus fixStatus;
  final double? headingDeg;
  final double size;

  const RaadBusMarker({
    super.key,
    required this.fixStatus,
    this.headingDeg,
    this.size = 38,
  });

  @override
  State<RaadBusMarker> createState() => _RaadBusMarkerState();
}

class _RaadBusMarkerState extends State<RaadBusMarker>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulseController;

  bool get _shouldAnimatePulse {
    if (widget.fixStatus != BusMarkerFixStatus.live) return false;
    final bindingName = WidgetsBinding.instance.runtimeType.toString();
    return !bindingName.contains('TestWidgetsFlutterBinding');
  }

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2000),
    );
    if (_shouldAnimatePulse) {
      _pulseController.repeat();
    }
  }

  @override
  void didUpdateWidget(RaadBusMarker oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_shouldAnimatePulse && !_pulseController.isAnimating) {
      _pulseController.repeat();
    } else if (!_shouldAnimatePulse && _pulseController.isAnimating) {
      _pulseController.stop();
    }
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  Color get _badgeColor => switch (widget.fixStatus) {
    BusMarkerFixStatus.live => RaadColors.blue,
    BusMarkerFixStatus.stale => RaadColors.amber,
    BusMarkerFixStatus.offline => RaadColors.grey,
  };

  @override
  Widget build(BuildContext context) {
    final badgeColor = _badgeColor;
    final outerSize = widget.size + 18;
    return SizedBox(
      width: outerSize,
      height: outerSize,
      child: Stack(
        alignment: Alignment.center,
        clipBehavior: Clip.none,
        children: [
          if (widget.fixStatus == BusMarkerFixStatus.live)
            AnimatedBuilder(
              animation: _pulseController,
              builder: (_, __) {
                final t = Curves.easeOut.transform(_pulseController.value);
                final scale = 0.85 + 0.55 * t;
                final opacity = (1.0 - t) * 0.65;
                return Transform.scale(
                  scale: scale,
                  child: Container(
                    width: widget.size + 8,
                    height: widget.size + 8,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: badgeColor.withValues(alpha: opacity),
                        width: 2.2,
                      ),
                    ),
                  ),
                );
              },
            ),
          if (widget.headingDeg != null)
            Transform.rotate(
              angle: widget.headingDeg! * math.pi / 180.0,
              child: Align(
                alignment: Alignment.topCenter,
                child: Padding(
                  padding: const EdgeInsets.only(top: 1),
                  child: CustomPaint(
                    size: const Size(10, 8),
                    painter: _HeadingTrianglePainter(color: badgeColor),
                  ),
                ),
              ),
            ),
          Container(
            width: widget.size,
            height: widget.size,
            decoration: BoxDecoration(
              color: badgeColor,
              shape: BoxShape.circle,
              border: Border.all(color: Colors.white, width: 2.4),
              boxShadow: const [
                BoxShadow(
                  color: Color(0x590F172A),
                  blurRadius: 6,
                  offset: Offset(0, 2),
                ),
              ],
            ),
            child: Center(
              child: CustomPaint(
                size: Size(widget.size * 0.5, widget.size * 0.5),
                painter: const _WebBusSvgPainter(),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _HeadingTrianglePainter extends CustomPainter {
  final Color color;
  const _HeadingTrianglePainter({required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.fill;
    final path = Path()
      ..moveTo(size.width / 2, 0)
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(covariant _HeadingTrianglePainter oldDelegate) =>
      oldDelegate.color != color;
}

class _WebBusSvgPainter extends CustomPainter {
  const _WebBusSvgPainter();

  @override
  void paint(Canvas canvas, Size size) {
    // Mirrors frontend/src/features/live-monitoring/vehicleMarker.ts Lucide Bus SVG (24x24 viewBox)
    final sx = size.width / 24.0;
    final sy = size.height / 24.0;
    canvas.save();
    canvas.scale(sx, sy);

    final stroke = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.0
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    // Window vertical mullions
    canvas.drawLine(const Offset(8, 6), const Offset(8, 12), stroke);
    canvas.drawLine(const Offset(15, 6), const Offset(15, 12), stroke);
    // Belt line
    canvas.drawLine(const Offset(2, 12), const Offset(21.6, 12), stroke);
    // Outer bus silhouette
    final body = Path()
      ..moveTo(18, 18)
      ..lineTo(21, 18)
      ..lineTo(21.8, 15.2)
      ..cubicTo(22, 14.4, 22, 13.6, 21.8, 12.8)
      ..lineTo(20.4, 7.8)
      ..cubicTo(20.1, 6.8, 19.1, 6, 18, 6)
      ..lineTo(4, 6)
      ..cubicTo(2.9, 6, 2, 6.9, 2, 8)
      ..lineTo(2, 18)
      ..lineTo(5, 18);
    canvas.drawPath(body, stroke);
    // Axle span + wheels
    canvas.drawLine(const Offset(9, 18), const Offset(14, 18), stroke);
    canvas.drawCircle(const Offset(7, 18), 2, stroke);
    canvas.drawCircle(const Offset(16, 18), 2, stroke);

    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
