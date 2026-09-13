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
  /** Pre-rendered HTML for a small hover card (plain markup, no framework tree — the same
   * "imperative Mapbox API, not a React tree" shape `element` already takes). Shown while the
   * pointer is over the marker, hidden on pointer-leave; a caller wanting click-to-navigate
   * behavior on the marker itself still attaches its own click listener to `element` — this is
   * deliberately independent of that. `undefined` renders no popup at all — and, unlike
   * `position`/`headingDeg`, a marker created without one can never gain one later via
   * {@link MapProvider.updateMarkerPopup}, only refresh one it already has. */
  popupHtml?: string;
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

/**
 * A filled-polygon overlay (Mapbox `fill` + a matching `line` outline) — for **Polygon/
 * MultiPolygon** geometry only, e.g. a future geofence boundary. Despite the name, this is not
 * the right layer for rendering a `Point` (use {@link addPointLayer} instead, e.g. a route stop)
 * — a `fill` layer paints nothing for `Point` features, since Mapbox GL requires matching
 * geometry types per layer type.
 */
export interface CircleLayerOptions {
  id: string;
  sourceId: string;
  color?: string;
  opacity?: number;
}

/**
 * A small filled dot per feature (Mapbox native `circle` layer type) — the correct layer type
 * for **Point/MultiPoint** geometry, e.g. route stops along a trip.
 */
export interface PointLayerOptions {
  id: string;
  sourceId: string;
  color?: string;
  radiusPx?: number;
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
  /**
   * Updates an already-bound marker's popup content in place — `updateMarker`'s own sibling for
   * the popup half of a marker's state, so a vehicle's hover card never has to go stale between
   * `addMarker` calls just because the marker itself keeps moving in place. A no-op if the marker
   * was never given a `popupHtml` at `addMarker` time (mirrors `updateMarker`'s own "no-op for an
   * unknown id" defensive shape) — this only refreshes an existing popup's content, it can never
   * attach one after the fact.
   *
   * Safe to call regardless of whether the popup is currently open or closed: an open popup's
   * content changes immediately in place, with no reposition/close/reopen/flicker of any kind
   * (the concrete provider must never tear down and recreate the popup to satisfy this); a closed
   * popup simply shows the new content the next time it opens.
   */
  updateMarkerPopup(id: string, popupHtml: string): void;
  removeMarker(id: string): void;
  /** Registers a click handler on an already-added marker — for a vehicle-detail popup/card.
   * A no-op if the marker doesn't exist (mirrors `updateMarker`'s own defensive shape). */
  onMarkerClick(id: string, handler: () => void): void;

  addGeoJsonSource(options: GeoJsonSourceOptions): void;
  addLineLayer(options: LineLayerOptions): void;
  addCircleLayer(options: CircleLayerOptions): void;
  addPointLayer(options: PointLayerOptions): void;
  removeLayer(id: string): void;
  removeSource(id: string): void;

  /**
   * Fires exactly when the *user* pans/zooms/rotates the map (mouse drag, touch, scroll-wheel,
   * keyboard) — never for a programmatic `setCenter`/`setZoom`/`fitBounds` call this same
   * provider makes on a caller's behalf. This is the vendor-neutral signal a "follow vehicle"
   * feature needs to know when to stop recentering the camera (root-cause fix, RAAD Live
   * Tracking wrong-location investigation — the camera-jump/steal-focus half of that
   * investigation): the map genuinely does not know the difference between "I just moved this"
   * and "the user just moved this" unless the provider tells it. Returns an unsubscribe function.
   */
  onUserPanOrZoom(handler: () => void): () => void;
}
