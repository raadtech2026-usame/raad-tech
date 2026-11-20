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
              width: 52,
              height: 52,
              child: Container(
                decoration: BoxDecoration(
                  color: widget.isStale ? RaadColors.grey : RaadColors.blue,
                  shape: BoxShape.circle,
                  border: Border.all(color: Colors.white, width: 3),
                  boxShadow: const [
                    BoxShadow(blurRadius: 6, color: Colors.black26),
                  ],
                ),
                child: const Icon(
                  Icons.directions_bus_rounded,
                  color: Colors.white,
                  size: 26,
                ),
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
