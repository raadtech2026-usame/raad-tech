import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../../core/config/env.dart';
import '../../shared/widgets.dart';

/// Where map tiles come from. The provider is a seam (`.claude/rules/flutter.md` #6): screens
/// use [BusMap] and never name a vendor.
abstract class MapTileSource {
  String get urlTemplate;
  String get attribution;
}

/// Mapbox raster tiles, the provider the web dashboard uses (ADR-0011). The token is the
/// public one given at build time.
class MapboxTileSource implements MapTileSource {
  const MapboxTileSource();

  @override
  String get urlTemplate =>
      'https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256/{z}/{x}/{y}@2x'
      '?access_token=${Env.mapboxAccessToken}';

  @override
  String get attribution => '© Mapbox © OpenStreetMap';
}

/// A bus and, optionally, the family's stop. Follows the bus as it moves.
class BusMap extends StatefulWidget {
  final double busLatitude;
  final double busLongitude;
  final double? heading;
  final double? stopLatitude;
  final double? stopLongitude;
  final String? stopName;
  final bool isStale;
  final MapTileSource tiles;

  const BusMap({
    super.key,
    required this.busLatitude,
    required this.busLongitude,
    this.heading,
    this.stopLatitude,
    this.stopLongitude,
    this.stopName,
    this.isStale = false,
    this.tiles = const MapboxTileSource(),
  });

  @override
  State<BusMap> createState() => _BusMapState();
}

class _BusMapState extends State<BusMap> {
  final _controller = MapController();
  bool _ready = false;

  LatLng get _bus => LatLng(widget.busLatitude, widget.busLongitude);

  @override
  void didUpdateWidget(BusMap oldWidget) {
    super.didUpdateWidget(oldWidget);
    final moved = oldWidget.busLatitude != widget.busLatitude ||
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
          urlTemplate: widget.tiles.urlTemplate,
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
                child: const Icon(Icons.location_on_rounded,
                    size: 44, color: RaadColors.green),
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
                    BoxShadow(blurRadius: 6, color: Colors.black26)
                  ],
                ),
                child: const Icon(Icons.directions_bus_rounded,
                    color: Colors.white, size: 26),
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
            child: Text(widget.tiles.attribution,
                style: const TextStyle(fontSize: 10)),
          ),
        ),
      ],
    );
  }
}
