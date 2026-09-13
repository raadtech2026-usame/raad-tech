import { beforeEach, describe, expect, it, vi } from "vitest";

// The real "error" handler (MapboxMapProvider.mount) reads `event.error` — the mock's handler
// type reflects that shape rather than the zero-arg `() => void` "load" handler actually needs,
// so the simulated error event below can be passed without a cast.
const onceHandlers = new Map<string, (event?: { error?: unknown }) => void>();
const onHandlers = new Map<string, (event?: { originalEvent?: unknown }) => void>();

const mapInstance = {
  once: vi.fn((event: string, handler: (event?: { error?: unknown }) => void) => {
    onceHandlers.set(event, handler);
  }),
  on: vi.fn((event: string, handler: (event?: { originalEvent?: unknown }) => void) => {
    onHandlers.set(event, handler);
  }),
  off: vi.fn(),
  remove: vi.fn(),
  setCenter: vi.fn(),
  setZoom: vi.fn(),
  fitBounds: vi.fn(),
  setConfigProperty: vi.fn(),
  addControl: vi.fn(),
  addSource: vi.fn(),
  addLayer: vi.fn(),
  getLayer: vi.fn(),
  removeLayer: vi.fn(),
  getSource: vi.fn(),
  removeSource: vi.fn(),
};

function makeMarkerElement(): HTMLElement {
  const el = document.createElement("div");
  const arrow = document.createElement("span");
  arrow.setAttribute("data-role", "heading-arrow");
  el.appendChild(arrow);
  return el;
}

const markerInstance = {
  setLngLat: vi.fn().mockReturnThis(),
  addTo: vi.fn().mockReturnThis(),
  setRotation: vi.fn(),
  remove: vi.fn(),
  getElement: vi.fn(() => makeMarkerElement()),
  getLngLat: vi.fn(() => ({ lat: 1, lng: 2 })),
};

const popupInstance = {
  setHTML: vi.fn().mockReturnThis(),
  setLngLat: vi.fn().mockReturnThis(),
  addTo: vi.fn().mockReturnThis(),
  remove: vi.fn(),
};

vi.mock("mapbox-gl", () => {
  // Regular `function` (not an arrow) so `new mapboxgl.Map(...)` works — vitest/jest invoke a
  // mock's implementation via `new` when the mock itself is constructed, and arrow functions
  // can't be constructors.
  const MapMock = vi.fn(function MapCtor() {
    return mapInstance;
  });
  const MarkerMock = vi.fn(function MarkerCtor() {
    return markerInstance;
  });
  const PopupMock = vi.fn(function PopupCtor() {
    return popupInstance;
  });
  const NavigationControlMock = vi.fn(function NavigationControlCtor() {
    return {};
  });
  const ScaleControlMock = vi.fn(function ScaleControlCtor() {
    return {};
  });
  return {
    default: {
      Map: MapMock,
      Marker: MarkerMock,
      Popup: PopupMock,
      NavigationControl: NavigationControlMock,
      ScaleControl: ScaleControlMock,
      accessToken: "",
    },
  };
});

vi.mock("mapbox-gl/dist/mapbox-gl.css", () => ({}));

// Imported after the mocks above so the module under test picks up the mocked `mapbox-gl`.
const { MapboxMapProvider } = await import("./MapboxMapProvider");
const mapboxgl = (await import("mapbox-gl")).default;

async function mountProvider() {
  const provider = new MapboxMapProvider();
  const container = document.createElement("div");
  const mountPromise = provider.mount({
    container,
    center: { lat: 24.7136, lng: 46.6753 },
    zoom: 12,
    accessToken: "test-token",
  });
  onceHandlers.get("load")?.();
  await mountPromise;
  return provider;
}

describe("MapboxMapProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    onceHandlers.clear();
    onHandlers.clear();
  });

  it("mounts and resolves once the map fires its load event", async () => {
    const provider = await mountProvider();
    expect(provider).toBeInstanceOf(MapboxMapProvider);
  });

  it("uses the Mapbox Standard style", async () => {
    await mountProvider();
    expect(mapboxgl.Map).toHaveBeenCalledWith(
      expect.objectContaining({ style: "mapbox://styles/mapbox/standard" }),
    );
  });

  it("configures the Standard style for a clean, professional fleet presentation", async () => {
    await mountProvider();
    expect(mapInstance.setConfigProperty).toHaveBeenCalledWith("basemap", "lightPreset", "day");
    expect(mapInstance.setConfigProperty).toHaveBeenCalledWith(
      "basemap",
      "showPointOfInterestLabels",
      false,
    );
    expect(mapInstance.setConfigProperty).toHaveBeenCalledWith(
      "basemap",
      "show3dObjects",
      false,
    );
  });

  it("does not fail mount() when setConfigProperty throws (older/mocked style)", async () => {
    mapInstance.setConfigProperty.mockImplementationOnce(() => {
      throw new Error("unknown config schema");
    });
    await expect(mountProvider()).resolves.toBeInstanceOf(MapboxMapProvider);
  });

  it("adds navigation and scale controls", async () => {
    await mountProvider();
    expect(mapboxgl.NavigationControl).toHaveBeenCalled();
    expect(mapboxgl.ScaleControl).toHaveBeenCalled();
    expect(mapInstance.addControl).toHaveBeenCalledTimes(2);
  });

  it("rejects mount() when the map fires an error before load", async () => {
    const provider = new MapboxMapProvider();
    const container = document.createElement("div");
    const mountPromise = provider.mount({
      container,
      center: { lat: 0, lng: 0 },
      zoom: 10,
      accessToken: "test-token",
    });
    const boom = new Error("boom");
    onceHandlers.get("error")?.({ error: boom });
    await expect(mountPromise).rejects.toThrow();
  });

  it("throws when a method is called before mount() resolves", () => {
    const provider = new MapboxMapProvider();
    expect(() => provider.setZoom(10)).toThrow(/mount\(\) must resolve/);
  });

  it("delegates setCenter/setZoom/fitBounds to the underlying map", async () => {
    const provider = await mountProvider();
    provider.setCenter({ lat: 1, lng: 2 });
    expect(mapInstance.setCenter).toHaveBeenCalledWith([2, 1]);

    provider.setZoom(15);
    expect(mapInstance.setZoom).toHaveBeenCalledWith(15);

    provider.fitBounds({ sw: { lat: 1, lng: 2 }, ne: { lat: 3, lng: 4 } });
    expect(mapInstance.fitBounds).toHaveBeenCalledWith(
      [
        [2, 1],
        [4, 3],
      ],
      { padding: 40 },
    );
  });

  it("adds, updates, and removes markers by id, never rotating the marker root itself", async () => {
    const provider = await mountProvider();
    provider.addMarker({ id: "v1", position: { lat: 1, lng: 2 }, headingDeg: 90 });
    expect(markerInstance.setLngLat).toHaveBeenCalledWith([2, 1]);
    expect(markerInstance.addTo).toHaveBeenCalledWith(mapInstance);
    // Root-cause fix (Mapbox UI upgrade): heading must never rotate the whole marker element —
    // only a `[data-role="heading-arrow"]` child, so a custom bus-glyph marker stays upright.
    expect(markerInstance.setRotation).not.toHaveBeenCalled();

    provider.updateMarker("v1", { lat: 5, lng: 6 }, 45);
    expect(markerInstance.setLngLat).toHaveBeenCalledWith([6, 5]);
    expect(markerInstance.setRotation).not.toHaveBeenCalled();

    provider.updateMarker("unknown", { lat: 0, lng: 0 });

    provider.removeMarker("v1");
    expect(markerInstance.remove).toHaveBeenCalled();
  });

  it("rotates only the marker element's own heading-arrow child, not the marker root", async () => {
    const provider = await mountProvider();
    provider.addMarker({ id: "v1", position: { lat: 1, lng: 2 } });

    provider.updateMarker("v1", { lat: 1, lng: 2 }, 120);

    const element = markerInstance.getElement.mock.results.at(-1)!.value as HTMLElement;
    const arrow = element.querySelector('[data-role="heading-arrow"]') as HTMLElement;
    expect(arrow.style.transform).toBe("rotate(120deg)");
    expect(arrow.getAttribute("data-visible")).toBe("true");
  });

  it("registers a click handler on the marker's own element", async () => {
    const provider = await mountProvider();
    provider.addMarker({ id: "v1", position: { lat: 1, lng: 2 } });
    const handler = vi.fn();

    provider.onMarkerClick("v1", handler);
    const element = markerInstance.getElement.mock.results.at(-1)!.value as HTMLElement;
    element.dispatchEvent(new Event("click"));

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("onMarkerClick is a safe no-op for an unknown marker id", async () => {
    const provider = await mountProvider();
    expect(() => provider.onMarkerClick("unknown", vi.fn())).not.toThrow();
  });

  describe("hover popup + dynamic content updates (vehicle-popup staleness investigation)", () => {
    it("binds a hover popup only when popupHtml is given, shown on mouseenter and hidden on mouseleave", async () => {
      const provider = await mountProvider();

      provider.addMarker({ id: "v1", position: { lat: 1, lng: 2 } });
      expect(mapboxgl.Popup).not.toHaveBeenCalled();

      provider.addMarker({ id: "v2", position: { lat: 1, lng: 2 }, popupHtml: "<div>hi</div>" });
      expect(mapboxgl.Popup).toHaveBeenCalledWith(
        expect.objectContaining({ closeButton: false, closeOnClick: false }),
      );
      expect(popupInstance.setHTML).toHaveBeenCalledWith("<div>hi</div>");

      const element = markerInstance.getElement.mock.results.at(-1)!.value as HTMLElement;
      element.dispatchEvent(new Event("mouseenter"));
      expect(popupInstance.addTo).toHaveBeenCalledWith(mapInstance);

      element.dispatchEvent(new Event("mouseleave"));
      expect(popupInstance.remove).toHaveBeenCalled();
    });

    it("updateMarkerPopup refreshes an existing popup's content in place — never repositioning, closing, or reopening it", async () => {
      const provider = await mountProvider();
      provider.addMarker({ id: "v1", position: { lat: 1, lng: 2 }, popupHtml: "<div>old</div>" });
      popupInstance.setLngLat.mockClear();
      popupInstance.addTo.mockClear();
      popupInstance.remove.mockClear();

      provider.updateMarkerPopup("v1", "<div>new</div>");

      expect(popupInstance.setHTML).toHaveBeenCalledWith("<div>new</div>");
      // No reposition/visibility toggle of any kind — content-only, whether the popup is
      // currently open or closed.
      expect(popupInstance.setLngLat).not.toHaveBeenCalled();
      expect(popupInstance.addTo).not.toHaveBeenCalled();
      expect(popupInstance.remove).not.toHaveBeenCalled();
    });

    it("updateMarkerPopup is a safe no-op when the marker was never given a popupHtml", async () => {
      const provider = await mountProvider();
      provider.addMarker({ id: "v1", position: { lat: 1, lng: 2 } });

      expect(() => provider.updateMarkerPopup("v1", "<div>new</div>")).not.toThrow();
      expect(popupInstance.setHTML).not.toHaveBeenCalled();
    });

    it("updateMarkerPopup is a safe no-op for an unknown marker id", async () => {
      const provider = await mountProvider();
      expect(() => provider.updateMarkerPopup("unknown", "<div>x</div>")).not.toThrow();
    });

    it("removeMarker tears down the marker's own bound popup too", async () => {
      const provider = await mountProvider();
      provider.addMarker({ id: "v1", position: { lat: 1, lng: 2 }, popupHtml: "<div>hi</div>" });

      provider.removeMarker("v1");
      expect(popupInstance.remove).toHaveBeenCalled();

      // No longer tracked — a later updateMarkerPopup for the same (now-removed) id is a no-op.
      popupInstance.setHTML.mockClear();
      provider.updateMarkerPopup("v1", "<div>after-removal</div>");
      expect(popupInstance.setHTML).not.toHaveBeenCalled();
    });
  });

  it("adds sources and layers", async () => {
    const provider = await mountProvider();
    provider.addGeoJsonSource({ id: "route-1", data: { type: "FeatureCollection", features: [] } });
    expect(mapInstance.addSource).toHaveBeenCalledWith("route-1", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });

    provider.addLineLayer({ id: "route-1-line", sourceId: "route-1" });
    expect(mapInstance.addLayer).toHaveBeenCalledWith(
      expect.objectContaining({ id: "route-1-line", type: "line", source: "route-1" }),
    );

    provider.addCircleLayer({ id: "geofence-1", sourceId: "route-1" });
    expect(mapInstance.addLayer).toHaveBeenCalledWith(
      expect.objectContaining({ id: "geofence-1", type: "fill", source: "route-1" }),
    );
    // A subtle outline layer, on the same source — see this provider's own docstring.
    expect(mapInstance.addLayer).toHaveBeenCalledWith(
      expect.objectContaining({ id: "geofence-1-outline", type: "line", source: "route-1" }),
    );
  });

  it("addPointLayer uses Mapbox's native circle layer type, for Point geometry (e.g. route stops)", async () => {
    const provider = await mountProvider();
    provider.addGeoJsonSource({
      id: "stops-1",
      data: { type: "FeatureCollection", features: [] },
    });

    provider.addPointLayer({ id: "stops-1", sourceId: "stops-1" });

    // `addCircleLayer` (above) creates a `fill` layer, which paints nothing for Point geometry —
    // route stops must go through this method instead.
    expect(mapInstance.addLayer).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "stops-1",
        type: "circle",
        source: "stops-1",
        paint: expect.objectContaining({ "circle-radius": expect.any(Number) }),
      }),
    );
    // No `fill`/`-outline` companion layer — a point layer is self-contained, unlike `addCircleLayer`.
    expect(mapInstance.addLayer).not.toHaveBeenCalledWith(
      expect.objectContaining({ id: "stops-1-outline" }),
    );
  });

  it("removes a layer/source (and any outline layer) only when it exists", async () => {
    const provider = await mountProvider();
    mapInstance.getLayer.mockReturnValue(undefined);
    provider.removeLayer("missing");
    expect(mapInstance.removeLayer).not.toHaveBeenCalled();

    mapInstance.getLayer.mockReturnValue({});
    provider.removeLayer("present");
    expect(mapInstance.removeLayer).toHaveBeenCalledWith("present-outline");
    expect(mapInstance.removeLayer).toHaveBeenCalledWith("present");

    mapInstance.getSource.mockReturnValueOnce(undefined);
    provider.removeSource("missing");
    expect(mapInstance.removeSource).not.toHaveBeenCalled();

    mapInstance.getSource.mockReturnValueOnce({});
    provider.removeSource("present");
    expect(mapInstance.removeSource).toHaveBeenCalledWith("present");
  });

  it("tears down all markers and the map on unmount", async () => {
    const provider = await mountProvider();
    provider.addMarker({ id: "v1", position: { lat: 1, lng: 2 } });
    provider.unmount();
    expect(markerInstance.remove).toHaveBeenCalled();
    expect(mapInstance.remove).toHaveBeenCalled();
  });

  describe("onUserPanOrZoom", () => {
    it("fires on a drag (always user-initiated)", async () => {
      const provider = await mountProvider();
      const handler = vi.fn();
      provider.onUserPanOrZoom(handler);

      onHandlers.get("dragstart")?.();

      expect(handler).toHaveBeenCalledTimes(1);
    });

    it("fires on a zoom/rotate/pitch only when a real user gesture caused it", async () => {
      const provider = await mountProvider();
      const handler = vi.fn();
      provider.onUserPanOrZoom(handler);

      // Programmatic (this provider's own setZoom/setCenter/fitBounds) — no originalEvent.
      onHandlers.get("zoomstart")?.({});
      expect(handler).not.toHaveBeenCalled();

      // A real user gesture — Mapbox attaches the causing DOM event.
      onHandlers.get("zoomstart")?.({ originalEvent: new WheelEvent("wheel") });
      expect(handler).toHaveBeenCalledTimes(1);

      onHandlers.get("rotatestart")?.({ originalEvent: new MouseEvent("mousedown") });
      expect(handler).toHaveBeenCalledTimes(2);

      onHandlers.get("pitchstart")?.({ originalEvent: new MouseEvent("mousedown") });
      expect(handler).toHaveBeenCalledTimes(3);
    });

    it("returns an unsubscribe function that detaches every listener", async () => {
      const provider = await mountProvider();
      const unsubscribe = provider.onUserPanOrZoom(vi.fn());

      unsubscribe();

      expect(mapInstance.off).toHaveBeenCalledWith("dragstart", expect.any(Function));
      expect(mapInstance.off).toHaveBeenCalledWith("zoomstart", expect.any(Function));
      expect(mapInstance.off).toHaveBeenCalledWith("rotatestart", expect.any(Function));
      expect(mapInstance.off).toHaveBeenCalledWith("pitchstart", expect.any(Function));
    });
  });
});
