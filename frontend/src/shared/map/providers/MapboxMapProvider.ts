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
  PointLayerOptions,
} from "../MapProvider";

/** `data-role="heading-arrow"` marks a marker element's own child that should receive heading
 * rotation independently of the marker's root node — see `updateMarker`'s own docstring below
 * and `features/live-monitoring/vehicleMarker.ts`, this convention's one producer today. */
const HEADING_ARROW_SELECTOR = '[data-role="heading-arrow"]';

/** Mapbox GL JS implementation of {@link MapProvider} (ADR-0011, upgraded to the Standard style
 * per current Mapbox guidance — see `mount()`'s own docstring). The only file in this codebase
 * that imports `mapbox-gl` directly — every other consumer goes through `MapView`/`MapProvider`,
 * so switching providers later never touches feature code. */
export class MapboxMapProvider implements MapProvider {
  private map: mapboxgl.Map | null = null;
  private markers = new Map<string, mapboxgl.Marker>();
  private popups = new Map<string, mapboxgl.Popup>();

  async mount(options: MapViewOptions): Promise<void> {
    mapboxgl.accessToken = options.accessToken;
    this.map = new mapboxgl.Map({
      container: options.container,
      center: [options.center.lng, options.center.lat],
      zoom: options.zoom,
      // Mapbox Standard (docs.mapbox.com/map-styles/guides/standard-styles) — the current
      // recommended style for new projects, replacing the classic `light-v11` this codebase
      // previously hardcoded. Configured just below for a clean, professional fleet-management
      // presentation: no 3D buildings/landmarks (flat, top-down clarity for tracking markers)
      // and no POI clutter (restaurants/shops are noise on a school-transportation map); road,
      // place, and transit labels stay on since drivers/routes need real-world context.
      style: "mapbox://styles/mapbox/standard",
    });
    const map = this.map;
    await new Promise<void>((resolve, reject) => {
      map.once("load", () => resolve());
      map.once("error", (event) => reject(event.error));
    });
    try {
      map.setConfigProperty("basemap", "lightPreset", "day");
      map.setConfigProperty("basemap", "showPointOfInterestLabels", false);
      map.setConfigProperty("basemap", "show3dObjects", false);
    } catch {
      // A test double or a future non-Standard style may not expose this config schema —
      // cosmetic only, never fatal to mounting the map itself.
    }
    map.addControl(new mapboxgl.NavigationControl({ showCompass: true }), "top-right");
    map.addControl(
      new mapboxgl.ScaleControl({ maxWidth: 120, unit: "metric" }),
      "bottom-left",
    );
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
    // `rotation` is deliberately never passed to the `Marker` constructor here — rotating the
    // whole marker element would also rotate a custom bus-glyph element sideways. Heading is
    // instead applied only to a `[data-role="heading-arrow"]` child, if the element has one
    // (see `_applyHeading` below); a caller with no custom element (or no such child) simply
    // gets no heading indicator, never a sideways-rotated default pin.
    const marker = new mapboxgl.Marker({ element: options.element })
      .setLngLat([options.position.lng, options.position.lat])
      .addTo(this.requireMap());
    this.markers.set(options.id, marker);
    this._applyHeading(marker.getElement(), options.headingDeg);
    if (options.popupHtml) {
      this._bindHoverPopup(options.id, marker, options.popupHtml);
    }
  }

  updateMarker(id: string, position: LatLng, headingDeg?: number): void {
    const marker = this.markers.get(id);
    if (!marker) return;
    marker.setLngLat([position.lng, position.lat]);
    this._applyHeading(marker.getElement(), headingDeg);
    this.popups.get(id)?.setLngLat([position.lng, position.lat]);
  }

  /** `mapboxgl.Popup.setHTML` swaps only the popup's own content DOM — it never repositions,
   * closes, or reopens the popup, whether currently shown or not (the same "safe to call on a
   * hidden instance" shape `updateMarker`'s own `this.popups.get(id)?.setLngLat(...)` above
   * already relies on for a closed popup's position). This is that same retained-instance
   * pattern, for content instead of position. */
  updateMarkerPopup(id: string, popupHtml: string): void {
    this.popups.get(id)?.setHTML(popupHtml);
  }

  removeMarker(id: string): void {
    this.markers.get(id)?.remove();
    this.markers.delete(id);
    this.popups.get(id)?.remove();
    this.popups.delete(id);
  }

  onMarkerClick(id: string, handler: () => void): void {
    const marker = this.markers.get(id);
    if (!marker) return;
    marker.getElement().addEventListener("click", handler);
  }

  addGeoJsonSource(options: GeoJsonSourceOptions): void {
    this.requireMap().addSource(options.id, { type: "geojson", data: options.data });
  }

  addLineLayer(options: LineLayerOptions): void {
    this.requireMap().addLayer({
      id: options.id,
      type: "line",
      source: options.sourceId,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": options.color ?? "#1E63FF",
        "line-width": options.widthPx ?? 4,
        // A soft outer glow keeps the route legible over the Standard style's own road/place
        // labels without needing a wider, more overpowering core line.
        "line-opacity": 0.9,
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
    // A subtle boundary line so a geofence stays visually understandable even over a busy
    // basemap area, per this UI upgrade's own "clear boundary, subtle fill" requirement —
    // additive: `removeLayer(options.id)` below already tears this down with it (same id
    // family, `-outline` suffix, never orphaned).
    this.requireMap().addLayer({
      id: `${options.id}-outline`,
      type: "line",
      source: options.sourceId,
      paint: {
        "line-color": options.color ?? "#2FBF4F",
        "line-width": 1.5,
        "line-opacity": 0.6,
      },
    });
  }

  /** Mapbox's native `circle` layer type — the correct type for `Point`/`MultiPoint` geometry
   * (e.g. route stops); `addCircleLayer` above is `fill`-based and only paints `Polygon`
   * geometry despite its name. */
  addPointLayer(options: PointLayerOptions): void {
    this.requireMap().addLayer({
      id: options.id,
      type: "circle",
      source: options.sourceId,
      paint: {
        "circle-radius": options.radiusPx ?? 6,
        "circle-color": options.color ?? "#1E63FF",
        "circle-stroke-width": 2,
        "circle-stroke-color": "#ffffff",
      },
    });
  }

  removeLayer(id: string): void {
    const map = this.requireMap();
    if (map.getLayer(`${id}-outline`)) {
      map.removeLayer(`${id}-outline`);
    }
    if (map.getLayer(id)) {
      map.removeLayer(id);
    }
  }

  removeSource(id: string): void {
    if (this.requireMap().getSource(id)) {
      this.requireMap().removeSource(id);
    }
  }

  onUserPanOrZoom(handler: () => void): () => void {
    const map = this.requireMap();
    // `dragstart` has no programmatic equivalent in this codebase's own usage (nothing here
    // ever calls `map.panBy`/`dragTo`), so it is unconditionally user-initiated. `zoomstart`/
    // `rotatestart`/`pitchstart` fire for both user gestures *and* this provider's own
    // `setCenter`/`setZoom`/`fitBounds` calls — Mapbox's own documented way to tell them apart
    // is `event.originalEvent`, present only when a real DOM input (wheel/touch/keyboard)
    // caused the change, undefined for a programmatic camera move.
    const onDragStart = () => handler();
    const onGestureStart = (event?: { originalEvent?: unknown }) => {
      if (event?.originalEvent) {
        handler();
      }
    };
    // `zoomstart`/`rotatestart`/`pitchstart` each declare a slightly different, non-optional
    // `{ originalEvent?: ... } | void` payload shape across mapbox-gl's own per-event overloads
    // of `on`/`off` — no single handler signature satisfies all three simultaneously under
    // strict overload resolution. One narrow, well-scoped cast (rather than three near-duplicate
    // handlers, one per exact declared shape) is the pragmatic choice here: every event this
    // method touches is read-only-checked for `originalEvent`'s presence, so the imprecision is
    // safe.
    const on = map.on.bind(map) as (event: string, handler: (event?: { originalEvent?: unknown }) => void) => void;
    const off = map.off.bind(map) as (event: string, handler: (event?: { originalEvent?: unknown }) => void) => void;
    on("dragstart", onDragStart);
    on("zoomstart", onGestureStart);
    on("rotatestart", onGestureStart);
    on("pitchstart", onGestureStart);
    return () => {
      off("dragstart", onDragStart);
      off("zoomstart", onGestureStart);
      off("rotatestart", onGestureStart);
      off("pitchstart", onGestureStart);
    };
  }

  /** A hover-only card (Mapbox UI upgrade's "clean popup/card" requirement) — deliberately
   * independent of the marker's own click behavior (`FleetMapPanel` attaches its own click
   * listener to `element` for click-to-select-vehicle navigation; this never interferes with
   * that). `closeButton`/`closeOnClick` are both off since visibility is driven entirely by
   * pointer enter/leave, not Mapbox's own click-to-dismiss default. */
  private _bindHoverPopup(id: string, marker: mapboxgl.Marker, html: string): void {
    const popup = new mapboxgl.Popup({ offset: 22, closeButton: false, closeOnClick: false });
    popup.setHTML(html);
    this.popups.set(id, popup);
    const element = marker.getElement();
    element.addEventListener("mouseenter", () => {
      popup.setLngLat(marker.getLngLat()).addTo(this.requireMap());
    });
    element.addEventListener("mouseleave", () => {
      popup.remove();
    });
  }

  private _applyHeading(element: HTMLElement | undefined, headingDeg: number | undefined): void {
    if (!element) return;
    const arrow = element.querySelector<HTMLElement>(HEADING_ARROW_SELECTOR);
    if (!arrow) return;
    if (headingDeg === undefined) {
      arrow.removeAttribute("data-visible");
      return;
    }
    arrow.style.transform = `rotate(${headingDeg}deg)`;
    arrow.setAttribute("data-visible", "true");
  }

  private requireMap(): mapboxgl.Map {
    if (!this.map) {
      throw new Error("MapboxMapProvider: mount() must resolve before calling any other method.");
    }
    return this.map;
  }
}
