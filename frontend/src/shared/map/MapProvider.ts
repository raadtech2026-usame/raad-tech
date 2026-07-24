/**
 * The pluggable map abstraction `.claude/rules/frontend.md` #6 requires ("do not hardcode a
 * single map vendor into feature code") — every concrete provider (currently only
 * `providers/MapboxMapProvider`) implements this interface; `MapView` is the only place a
 * feature ever touches a provider directly.
 *
 * Shaped around what Phase F7 (Live Monitoring & Maps) actually needs, per its own documented
 * scope (`docs/architecture/frontend-flutter-master-roadmap.md`'s Phase F7 entry): a fleet-wide
 * view and a per-vehicle detail view (markers), route/stop overlay (reusing F5's route data,
 * a line + point layer), and geofence display (circle/polygon layers) — not a speculative
 * general-purpose map API surface beyond that.
 */

export interface LatLng {
  lat: number;
  lng: number;
}

export interface MapBounds {
  /** South-west corner. */
  sw: LatLng;
  /** North-east corner. */
  ne: LatLng;
}

export interface MapMarkerOptions {
  id: string;
  position: LatLng;
  /** Rotation in degrees, 0-360, clockwise from north — matches `heading_deg` on the tracking
   * wire contract (API Contracts §11.2) directly, so a caller never has to convert units. */
  headingDeg?: number;
  /** Arbitrary data a caller can use to render a custom marker element (e.g. a vehicle icon
   * colored by status) — this abstraction does not prescribe marker appearance. */
  element?: HTMLElement;
}

export interface GeoJsonSourceOptions {
  id: string;
  data: GeoJSON.Feature | GeoJSON.FeatureCollection;
}

export interface LineLayerOptions {
  id: string;
  sourceId: string;
  color?: string;
  widthPx?: number;
}

export interface CircleLayerOptions {
  id: string;
  sourceId: string;
  color?: string;
  opacity?: number;
}

export interface MapViewOptions {
  container: HTMLElement;
  center: LatLng;
  zoom: number;
  accessToken: string;
}

/**
 * One instance per mounted map. `MapView` owns the instance's lifecycle (`mount`/`unmount`);
 * every other method assumes `mount` has already resolved.
 */
export interface MapProvider {
  mount(options: MapViewOptions): Promise<void>;
  unmount(): void;

  setCenter(position: LatLng): void;
  setZoom(zoom: number): void;
  fitBounds(bounds: MapBounds, paddingPx?: number): void;

  addMarker(options: MapMarkerOptions): void;
  /** Updates an existing marker's position/heading in place — the hot path for live tracking,
   * called on every `/ws/tracking` frame; must not tear down and recreate the marker element. */
  updateMarker(id: string, position: LatLng, headingDeg?: number): void;
  removeMarker(id: string): void;

  addGeoJsonSource(options: GeoJsonSourceOptions): void;
  addLineLayer(options: LineLayerOptions): void;
  addCircleLayer(options: CircleLayerOptions): void;
  removeLayer(id: string): void;
  removeSource(id: string): void;
}
