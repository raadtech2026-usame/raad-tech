import { beforeEach, describe, expect, it, vi } from "vitest";

// The real "error" handler (MapboxMapProvider.mount) reads `event.error` — the mock's handler
// type reflects that shape rather than the zero-arg `() => void` "load" handler actually needs,
// so the simulated error event below can be passed without a cast.
const onceHandlers = new Map<string, (event?: { error?: unknown }) => void>();

const mapInstance = {
  once: vi.fn((event: string, handler: (event?: { error?: unknown }) => void) => {
    onceHandlers.set(event, handler);
  }),
  remove: vi.fn(),
  setCenter: vi.fn(),
  setZoom: vi.fn(),
  fitBounds: vi.fn(),
  addSource: vi.fn(),
  addLayer: vi.fn(),
  getLayer: vi.fn(),
  removeLayer: vi.fn(),
  getSource: vi.fn(),
  removeSource: vi.fn(),
};

const markerInstance = {
  setLngLat: vi.fn().mockReturnThis(),
  addTo: vi.fn().mockReturnThis(),
  setRotation: vi.fn(),
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
  return {
    default: {
      Map: MapMock,
      Marker: MarkerMock,
      accessToken: "",
    },
  };
});

vi.mock("mapbox-gl/dist/mapbox-gl.css", () => ({}));

// Imported after the mocks above so the module under test picks up the mocked `mapbox-gl`.
const { MapboxMapProvider } = await import("./MapboxMapProvider");

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
  });

  it("mounts and resolves once the map fires its load event", async () => {
    const provider = await mountProvider();
    expect(provider).toBeInstanceOf(MapboxMapProvider);
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

  it("adds, updates, and removes markers by id", async () => {
    const provider = await mountProvider();
    provider.addMarker({ id: "v1", position: { lat: 1, lng: 2 }, headingDeg: 90 });
    expect(markerInstance.setLngLat).toHaveBeenCalledWith([2, 1]);
    expect(markerInstance.addTo).toHaveBeenCalledWith(mapInstance);

    provider.updateMarker("v1", { lat: 5, lng: 6 }, 45);
    expect(markerInstance.setLngLat).toHaveBeenCalledWith([6, 5]);
    expect(markerInstance.setRotation).toHaveBeenCalledWith(45);

    provider.updateMarker("unknown", { lat: 0, lng: 0 });

    provider.removeMarker("v1");
    expect(markerInstance.remove).toHaveBeenCalled();
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
  });

  it("removes a layer/source only when it exists", async () => {
    const provider = await mountProvider();
    mapInstance.getLayer.mockReturnValueOnce(undefined);
    provider.removeLayer("missing");
    expect(mapInstance.removeLayer).not.toHaveBeenCalled();

    mapInstance.getLayer.mockReturnValueOnce({});
    provider.removeLayer("present");
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
});
