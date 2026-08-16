import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockProvider = {
  mount: vi.fn(),
  unmount: vi.fn(),
  setCenter: vi.fn(),
  setZoom: vi.fn(),
  fitBounds: vi.fn(),
  addMarker: vi.fn(),
  updateMarker: vi.fn(),
  removeMarker: vi.fn(),
  addGeoJsonSource: vi.fn(),
  addLineLayer: vi.fn(),
  addCircleLayer: vi.fn(),
  removeLayer: vi.fn(),
  removeSource: vi.fn(),
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

  it("adds a marker for a valid position and skips a non-finite one without crashing", () => {
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
    expect(mockProvider.addMarker).toHaveBeenCalledWith({
      id: "live-vehicle",
      position: { lat: 2.05, lng: 45.32 },
      headingDeg: 90,
    });
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
    expect(mockProvider.addCircleLayer).toHaveBeenCalled();

    rerender(
      <VehicleMapPanel vehicleId="v2" position={null} hasKnownPosition={false} isPositionLoading={false} routeStops={null} />,
    );
    expect(mockProvider.removeMarker).toHaveBeenCalledWith("live-vehicle");
  });
});
