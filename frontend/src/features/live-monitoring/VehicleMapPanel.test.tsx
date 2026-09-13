import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

let userPanHandler: (() => void) | null = null;
const unsubscribeUserPan = vi.fn();

const mockProvider = {
  mount: vi.fn(),
  unmount: vi.fn(),
  setCenter: vi.fn(),
  setZoom: vi.fn(),
  fitBounds: vi.fn(),
  addMarker: vi.fn(),
  updateMarker: vi.fn(),
  updateMarkerPopup: vi.fn(),
  removeMarker: vi.fn(),
  onMarkerClick: vi.fn(),
  addGeoJsonSource: vi.fn(),
  addLineLayer: vi.fn(),
  addCircleLayer: vi.fn(),
  addPointLayer: vi.fn(),
  removeLayer: vi.fn(),
  removeSource: vi.fn(),
  onUserPanOrZoom: vi.fn((handler: () => void) => {
    userPanHandler = handler;
    return unsubscribeUserPan;
  }),
};

vi.mock("../../shared/map/MapView", () => ({
  MapView: (props: { onReady?: (provider: typeof mockProvider) => void }) => {
    props.onReady?.(mockProvider);
    return <div data-testid="mock-map" />;
  },
}));

import { VehicleMapPanel } from "./VehicleMapPanel";

describe("VehicleMapPanel", () => {
  beforeEach(() => {
    for (const fn of Object.values(mockProvider)) fn.mockClear();
    unsubscribeUserPan.mockClear();
    userPanHandler = null;
  });

  it("shows the 'select a vehicle' empty state when no vehicle id is given", () => {
    render(
      <VehicleMapPanel vehicleId="" position={null} hasKnownPosition={false} isPositionLoading={false} routeStops={null} />,
    );
    expect(screen.getByText("Select a vehicle to start tracking")).toBeInTheDocument();
  });

  it("suppresses the 'no live position' empty state while the snapshot is still loading", () => {
    render(
      <VehicleMapPanel
        vehicleId="v1"
        position={null}
        hasKnownPosition={false}
        isPositionLoading
        routeStops={null}
      />,
    );
    expect(screen.queryByText("No live position data")).not.toBeInTheDocument();
  });

  it("adds a marker (with a custom element) for a valid position and skips a non-finite one without crashing", () => {
    const { rerender } = render(
      <VehicleMapPanel
        vehicleId="v1"
        position={{ lat: Number.NaN, lng: Number.NaN, headingDeg: 0 }}
        hasKnownPosition
        isPositionLoading={false}
        routeStops={null}
      />,
    );
    expect(mockProvider.addMarker).not.toHaveBeenCalled();

    rerender(
      <VehicleMapPanel
        vehicleId="v1"
        position={{ lat: 2.05, lng: 45.32, headingDeg: 90 }}
        hasKnownPosition
        isPositionLoading={false}
        routeStops={null}
      />,
    );
    expect(mockProvider.addMarker).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "live-vehicle",
        position: { lat: 2.05, lng: 45.32 },
        headingDeg: 90,
        element: expect.any(HTMLElement),
      }),
    );
  });

  it("adds route/stop layers once route stops are provided, and removes the marker on vehicle change", () => {
    const { rerender } = render(
      <VehicleMapPanel
        vehicleId="v1"
        position={null}
        hasKnownPosition={false}
        isPositionLoading={false}
        routeStops={[
          { id: "s1", name: "A", latitude: 1, longitude: 1, sequenceNo: 1, geofenceRadiusM: null },
        ]}
      />,
    );
    expect(mockProvider.addLineLayer).toHaveBeenCalled();
    // Route stops are Point geometry — must use the dedicated point layer (Mapbox `circle` type),
    // never `addCircleLayer` (which is `fill`-based and only paints Polygon geometry).
    expect(mockProvider.addPointLayer).toHaveBeenCalledWith(
      expect.objectContaining({ id: "active-trip-stops", sourceId: "active-trip-stops" }),
    );
    expect(mockProvider.addCircleLayer).not.toHaveBeenCalled();

    rerender(
      <VehicleMapPanel vehicleId="v2" position={null} hasKnownPosition={false} isPositionLoading={false} routeStops={null} />,
    );
    expect(mockProvider.removeMarker).toHaveBeenCalledWith("live-vehicle");
  });

  describe("camera-follow behavior (root-cause fix)", () => {
    it("recenters on every position update while following (the default)", () => {
      const { rerender } = render(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.05, lng: 45.32, headingDeg: 0 }}
          hasKnownPosition
          isPositionLoading={false}
          routeStops={null}
        />,
      );
      expect(mockProvider.setCenter).toHaveBeenCalledWith({ lat: 2.05, lng: 45.32 });

      rerender(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 3, lng: 46, headingDeg: 0 }}
          hasKnownPosition
          isPositionLoading={false}
          routeStops={null}
        />,
      );
      expect(mockProvider.setCenter).toHaveBeenCalledWith({ lat: 3, lng: 46 });
    });

    it("stops recentering once the user manually pans/zooms, and shows a Recenter control", () => {
      const { rerender } = render(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.05, lng: 45.32, headingDeg: 0 }}
          hasKnownPosition
          isPositionLoading={false}
          routeStops={null}
        />,
      );
      mockProvider.setCenter.mockClear();

      // Simulate the user dragging the map — MapProvider.onUserPanOrZoom's own registered
      // handler fires.
      act(() => userPanHandler?.());

      rerender(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 9, lng: 9, headingDeg: 0 }}
          hasKnownPosition
          isPositionLoading={false}
          routeStops={null}
        />,
      );
      // The marker still moves to the real position...
      expect(mockProvider.updateMarker).toHaveBeenCalledWith("live-vehicle", { lat: 9, lng: 9 }, 0);
      // ...but the camera does not follow it anymore.
      expect(mockProvider.setCenter).not.toHaveBeenCalled();

      expect(screen.getByRole("button", { name: /recenter/i })).toBeInTheDocument();
    });

    it("clicking Recenter resumes following and immediately centers on the current position", async () => {
      const { rerender } = render(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.05, lng: 45.32, headingDeg: 0 }}
          hasKnownPosition
          isPositionLoading={false}
          routeStops={null}
        />,
      );
      act(() => userPanHandler?.()); // stop following
      rerender(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 9, lng: 9, headingDeg: 0 }}
          hasKnownPosition
          isPositionLoading={false}
          routeStops={null}
        />,
      );
      mockProvider.setCenter.mockClear();

      await userEvent.click(screen.getByRole("button", { name: /recenter/i }));

      expect(mockProvider.setCenter).toHaveBeenCalledWith({ lat: 9, lng: 9 });
      expect(screen.getByRole("button", { name: /following/i })).toBeInTheDocument();
    });

    it("resets to following when the selected vehicle changes", () => {
      const { rerender } = render(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.05, lng: 45.32, headingDeg: 0 }}
          hasKnownPosition
          isPositionLoading={false}
          routeStops={null}
        />,
      );
      act(() => userPanHandler?.()); // stop following v1
      rerender(
        <VehicleMapPanel
          vehicleId="v2"
          position={{ lat: 5, lng: 6, headingDeg: 0 }}
          hasKnownPosition
          isPositionLoading={false}
          routeStops={null}
        />,
      );

      expect(screen.getByRole("button", { name: /following/i })).toBeInTheDocument();
    });
  });

  describe("dynamic hover popup (vehicle-popup staleness investigation)", () => {
    it("renders the popup with the given title/fix-status/speed on marker creation", () => {
      render(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.05, lng: 45.32, headingDeg: 90, eventTime: "2026-01-01T12:03:08Z" }}
          hasKnownPosition
          isPositionLoading={false}
          vehicleTitle="BENCH-001 — Bus 001"
          speedKph={0}
          gpsFixStatus="live"
          routeStops={null}
        />,
      );

      const call = vi.mocked(mockProvider.addMarker).mock.calls[0][0];
      expect(call.popupHtml).toContain("BENCH-001 — Bus 001");
      expect(call.popupHtml).toContain("0 km/h");
      expect(call.popupHtml).toContain("Live");
    });

    it("falls back to the raw vehicleId when no vehicleTitle is given yet", () => {
      render(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.05, lng: 45.32, headingDeg: 90, eventTime: "2026-01-01T12:03:08Z" }}
          hasKnownPosition
          isPositionLoading={false}
          routeStops={null}
        />,
      );

      const call = vi.mocked(mockProvider.addMarker).mock.calls[0][0];
      expect(call.popupHtml).toContain("v1");
    });

    it("never binds a popup for a pre-existing fixture with no eventTime, preserving old callers unchanged", () => {
      render(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.05, lng: 45.32, headingDeg: 90 }}
          hasKnownPosition
          isPositionLoading={false}
          routeStops={null}
        />,
      );

      const call = vi.mocked(mockProvider.addMarker).mock.calls[0][0];
      expect(call.popupHtml).toBeUndefined();
    });

    it("refreshes the popup content in place (never recreating the marker) when speed/position/timestamp change", () => {
      const { rerender } = render(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.05, lng: 45.32, headingDeg: 90, eventTime: "2026-01-01T12:03:08Z" }}
          hasKnownPosition
          isPositionLoading={false}
          vehicleTitle="BENCH-001 — Bus 001"
          speedKph={0}
          gpsFixStatus="live"
          routeStops={null}
        />,
      );
      expect(mockProvider.addMarker).toHaveBeenCalledTimes(1);

      rerender(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.06, lng: 45.33, headingDeg: 91, eventTime: "2026-01-01T12:03:15Z" }}
          hasKnownPosition
          isPositionLoading={false}
          vehicleTitle="BENCH-001 — Bus 001"
          speedKph={18}
          gpsFixStatus="live"
          routeStops={null}
        />,
      );

      expect(mockProvider.addMarker).toHaveBeenCalledTimes(1); // never recreated
      expect(mockProvider.updateMarkerPopup).toHaveBeenCalledTimes(1);
      const [, html] = vi.mocked(mockProvider.updateMarkerPopup).mock.calls[0];
      expect(html).toContain("18 km/h");
    });

    it("refreshes the popup on a fix-status change alone, with no new position", () => {
      const { rerender } = render(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.05, lng: 45.32, headingDeg: 90, eventTime: "2026-01-01T12:03:08Z" }}
          hasKnownPosition
          isPositionLoading={false}
          vehicleTitle="BENCH-001 — Bus 001"
          speedKph={0}
          gpsFixStatus="live"
          routeStops={null}
        />,
      );
      mockProvider.updateMarkerPopup.mockClear();

      rerender(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.05, lng: 45.32, headingDeg: 90, eventTime: "2026-01-01T12:03:08Z" }}
          hasKnownPosition
          isPositionLoading={false}
          vehicleTitle="BENCH-001 — Bus 001"
          speedKph={0}
          gpsFixStatus="stale"
          routeStops={null}
        />,
      );

      expect(mockProvider.addMarker).toHaveBeenCalledTimes(1);
      const [, html] = vi.mocked(mockProvider.updateMarkerPopup).mock.calls.at(-1)!;
      expect(html).toContain("Stale");
    });

    it("self-corrects the popup title once vehicleTitle resolves after the marker was already created", () => {
      const { rerender } = render(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.05, lng: 45.32, headingDeg: 90, eventTime: "2026-01-01T12:03:08Z" }}
          hasKnownPosition
          isPositionLoading={false}
          speedKph={0}
          gpsFixStatus="live"
          routeStops={null}
        />,
      );
      expect(vi.mocked(mockProvider.addMarker).mock.calls[0][0].popupHtml).toContain("v1");

      rerender(
        <VehicleMapPanel
          vehicleId="v1"
          position={{ lat: 2.05, lng: 45.32, headingDeg: 90, eventTime: "2026-01-01T12:03:08Z" }}
          hasKnownPosition
          isPositionLoading={false}
          vehicleTitle="BENCH-001 — Bus 001"
          speedKph={0}
          gpsFixStatus="live"
          routeStops={null}
        />,
      );

      expect(mockProvider.addMarker).toHaveBeenCalledTimes(1); // still not recreated
      const [, html] = vi.mocked(mockProvider.updateMarkerPopup).mock.calls.at(-1)!;
      expect(html).toContain("BENCH-001 — Bus 001");
    });
  });
});
