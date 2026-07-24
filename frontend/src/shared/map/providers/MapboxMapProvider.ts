import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import type {
  CircleLayerOptions,
  GeoJsonSourceOptions,
  LineLayerOptions,
  MapBounds,
  MapMarkerOptions,
  MapProvider,
  MapViewOptions,
  LatLng,
} from "../MapProvider";

/** Mapbox GL JS implementation of {@link MapProvider} (ADR-0011). The only file in this codebase
 * that imports `mapbox-gl` directly — every other consumer goes through `MapView`/`MapProvider`,
 * so switching providers later never touches feature code. */
export class MapboxMapProvider implements MapProvider {
  private map: mapboxgl.Map | null = null;
  private markers = new Map<string, mapboxgl.Marker>();

  async mount(options: MapViewOptions): Promise<void> {
    mapboxgl.accessToken = options.accessToken;
    this.map = new mapboxgl.Map({
      container: options.container,
      center: [options.center.lng, options.center.lat],
      zoom: options.zoom,
      style: "mapbox://styles/mapbox/light-v11",
    });
    await new Promise<void>((resolve, reject) => {
      this.map!.once("load", () => resolve());
      this.map!.once("error", (event) => reject(event.error));
    });
  }

  unmount(): void {
    this.markers.forEach((marker) => marker.remove());
    this.markers.clear();
    this.map?.remove();
    this.map = null;
  }

  setCenter(position: LatLng): void {
    this.requireMap().setCenter([position.lng, position.lat]);
  }

  setZoom(zoom: number): void {
    this.requireMap().setZoom(zoom);
  }

  fitBounds(bounds: MapBounds, paddingPx = 40): void {
    this.requireMap().fitBounds(
      [
        [bounds.sw.lng, bounds.sw.lat],
        [bounds.ne.lng, bounds.ne.lat],
      ],
      { padding: paddingPx },
    );
  }

  addMarker(options: MapMarkerOptions): void {
    const marker = new mapboxgl.Marker({ element: options.element, rotation: options.headingDeg })
      .setLngLat([options.position.lng, options.position.lat])
      .addTo(this.requireMap());
    this.markers.set(options.id, marker);
  }

  updateMarker(id: string, position: LatLng, headingDeg?: number): void {
    const marker = this.markers.get(id);
    if (!marker) return;
    marker.setLngLat([position.lng, position.lat]);
    if (headingDeg !== undefined) {
      marker.setRotation(headingDeg);
    }
  }

  removeMarker(id: string): void {
    this.markers.get(id)?.remove();
    this.markers.delete(id);
  }

  addGeoJsonSource(options: GeoJsonSourceOptions): void {
    this.requireMap().addSource(options.id, { type: "geojson", data: options.data });
  }

  addLineLayer(options: LineLayerOptions): void {
    this.requireMap().addLayer({
      id: options.id,
      type: "line",
      source: options.sourceId,
      paint: {
        "line-color": options.color ?? "#1E63FF",
        "line-width": options.widthPx ?? 3,
      },
    });
  }

  addCircleLayer(options: CircleLayerOptions): void {
    this.requireMap().addLayer({
      id: options.id,
      type: "fill",
      source: options.sourceId,
      paint: {
        "fill-color": options.color ?? "#2FBF4F",
        "fill-opacity": options.opacity ?? 0.15,
      },
    });
  }

  removeLayer(id: string): void {
    if (this.requireMap().getLayer(id)) {
      this.requireMap().removeLayer(id);
    }
  }

  removeSource(id: string): void {
    if (this.requireMap().getSource(id)) {
      this.requireMap().removeSource(id);
    }
  }

  private requireMap(): mapboxgl.Map {
    if (!this.map) {
      throw new Error("MapboxMapProvider: mount() must resolve before calling any other method.");
    }
    return this.map;
  }
}
