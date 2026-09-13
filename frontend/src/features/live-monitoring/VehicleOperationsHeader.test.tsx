import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { VehicleOperationsHeader, type VehicleOperationsHeaderProps } from "./VehicleOperationsHeader";

const VEHICLES = [
  { id: "v1", plateNo: "ABC-1234", label: "Bus 12" },
  { id: "v2", plateNo: "XYZ-9999", label: null },
];

const DEVICE = {
  id: "device-1",
  terminalId: "TERM12345678",
  isOnline: true,
  cameras: [
    { id: "cam-1", channelNo: 1, position: "road_facing" as const, label: "Front" },
    { id: "cam-2", channelNo: 2, position: "in_cabin" as const, label: "Cabin" },
  ],
};

function baseProps(overrides: Partial<VehicleOperationsHeaderProps> = {}): VehicleOperationsHeaderProps {
  return {
    vehicles: VEHICLES,
    vehiclesLoading: false,
    selectedVehicleId: "",
    onSelectVehicle: vi.fn(),
    gps: {
      wsStatus: "connecting",
      isAuthOrPolicyClose: false,
      livePosition: null,
      gpsFixStatus: "no_fix",
    },
    deviceStatus: "idle",
    device: null,
    showCameraChip: true,
    showAllVehiclesOption: true,
    ...overrides,
  };
}

describe("VehicleOperationsHeader", () => {
  it("shows an honest placeholder and no status chips before a vehicle is selected", () => {
    render(<VehicleOperationsHeader {...baseProps()} />);
    expect(screen.getByText("Select a vehicle to begin")).toBeInTheDocument();
    expect(screen.queryByTestId("chip-gps")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chip-device")).not.toBeInTheDocument();
  });

  it("lists every vehicle and reports the chosen id to the caller", async () => {
    const onSelectVehicle = vi.fn();
    render(<VehicleOperationsHeader {...baseProps({ onSelectVehicle })} />);
    await userEvent.selectOptions(screen.getByLabelText("Vehicle"), "v2");
    expect(onSelectVehicle).toHaveBeenCalledWith("v2");
  });

  it("shows GPS Live only when the socket is open, not policy-closed, and the fix is live", () => {
    render(
      <VehicleOperationsHeader
        {...baseProps({
          selectedVehicleId: "v1",
          gps: {
            wsStatus: "open",
            isAuthOrPolicyClose: false,
            livePosition: { lat: 2.05, lng: 45.32, headingDeg: 90, eventTime: "2026-01-01T00:00:00Z" },
            gpsFixStatus: "live",
          },
        })}
      />,
    );
    expect(screen.getByTestId("chip-gps")).toHaveTextContent("Live");
  });

  it("shows 'No Fix' (root-cause fix) when the socket is open but the device reports no GPS fix", () => {
    // The exact production bug this investigation started from: a connected socket must never
    // be conflated with a trustworthy position.
    render(
      <VehicleOperationsHeader
        {...baseProps({
          selectedVehicleId: "v1",
          gps: {
            wsStatus: "open",
            isAuthOrPolicyClose: false,
            livePosition: { lat: 2.05, lng: 45.32, headingDeg: 90, eventTime: "2026-01-01T00:00:00Z" },
            gpsFixStatus: "no_fix",
          },
        })}
      />,
    );
    expect(screen.getByTestId("chip-gps")).toHaveTextContent("No Fix");
  });

  it("shows 'Not authorized' rather than a silent connecting state on a policy close", () => {
    render(
      <VehicleOperationsHeader
        {...baseProps({
          selectedVehicleId: "v1",
          gps: {
            wsStatus: "closed",
            isAuthOrPolicyClose: true,
            livePosition: null,
            gpsFixStatus: "no_fix",
          },
        })}
      />,
    );
    expect(screen.getByTestId("chip-gps")).toHaveTextContent("Not authorized");
  });

  it("shows the device's online status and terminal id once resolved", () => {
    render(
      <VehicleOperationsHeader
        {...baseProps({ selectedVehicleId: "v1", deviceStatus: "ready", device: DEVICE })}
      />,
    );
    expect(screen.getByTestId("chip-device")).toHaveTextContent("Online");
    expect(screen.getByTestId("chip-device")).toHaveTextContent("TERM12345678");
  });

  it("shows a 'No device' chip for a vehicle with no active assignment", () => {
    render(
      <VehicleOperationsHeader
        {...baseProps({ selectedVehicleId: "v1", deviceStatus: "no-assignment", device: null })}
      />,
    );
    expect(screen.getByTestId("chip-device")).toHaveTextContent("No device");
  });

  it("shows the resolved camera count when video is role-eligible", () => {
    render(
      <VehicleOperationsHeader
        {...baseProps({ selectedVehicleId: "v1", deviceStatus: "ready", device: DEVICE, showCameraChip: true })}
      />,
    );
    expect(screen.getByTestId("chip-cameras")).toHaveTextContent("2");
  });

  it("hides the Cameras chip entirely for a role without video access", () => {
    render(
      <VehicleOperationsHeader
        {...baseProps({ selectedVehicleId: "v1", deviceStatus: "ready", device: DEVICE, showCameraChip: false })}
      />,
    );
    expect(screen.queryByTestId("chip-cameras")).not.toBeInTheDocument();
  });

  it("shows the last GPS update time once a live position exists", () => {
    render(
      <VehicleOperationsHeader
        {...baseProps({
          selectedVehicleId: "v1",
          gps: {
            wsStatus: "open",
            isAuthOrPolicyClose: false,
            livePosition: { lat: 2.05, lng: 45.32, headingDeg: 90, eventTime: "2026-01-01T00:00:00Z" },
            gpsFixStatus: "live",
          },
        })}
      />,
    );
    expect(screen.getByText(/Last GPS update/)).toBeInTheDocument();
  });

  it("shows 'Last valid position' instead of 'Last GPS update' while the fix is invalid", () => {
    render(
      <VehicleOperationsHeader
        {...baseProps({
          selectedVehicleId: "v1",
          gps: {
            wsStatus: "open",
            isAuthOrPolicyClose: false,
            livePosition: { lat: 2.05, lng: 45.32, headingDeg: 90, eventTime: "2026-01-01T00:00:00Z" },
            gpsFixStatus: "no_fix",
          },
        })}
      />,
    );
    expect(screen.getByText(/Last valid position/)).toBeInTheDocument();
  });
});
