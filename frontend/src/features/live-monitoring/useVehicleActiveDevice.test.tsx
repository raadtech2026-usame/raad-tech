import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("./api", () => ({
  getDeviceAssignmentForVehicle: vi.fn(),
  getActiveDeviceDetails: vi.fn(),
}));

import { getActiveDeviceDetails, getDeviceAssignmentForVehicle } from "./api";
import { useVehicleActiveDevice } from "./useVehicleActiveDevice";

const DEVICE = {
  id: "01DEVICE0000000000000000A",
  terminalId: "TERM12345678",
  isOnline: true,
  cameras: [{ id: "01CAMERA000000000000000A", channelNo: 1, position: "road_facing" as const, label: "Front" }],
};

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useVehicleActiveDevice", () => {
  beforeEach(() => {
    vi.mocked(getDeviceAssignmentForVehicle).mockReset();
    vi.mocked(getActiveDeviceDetails).mockReset();
  });

  it("reports 'idle' when no vehicle is selected, without calling either endpoint", () => {
    const { result } = renderHook(() => useVehicleActiveDevice(""), { wrapper });

    expect(result.current).toEqual({ status: "idle", device: null });
    expect(getDeviceAssignmentForVehicle).not.toHaveBeenCalled();
    expect(getActiveDeviceDetails).not.toHaveBeenCalled();
  });

  it("resolves through both endpoints in order and returns 'ready' with the device", async () => {
    vi.mocked(getDeviceAssignmentForVehicle).mockResolvedValue({ deviceId: DEVICE.id });
    vi.mocked(getActiveDeviceDetails).mockResolvedValue(DEVICE);

    const { result } = renderHook(() => useVehicleActiveDevice("vehicle-1"), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.device).toEqual(DEVICE);
    expect(getDeviceAssignmentForVehicle).toHaveBeenCalledWith("vehicle-1");
    expect(getActiveDeviceDetails).toHaveBeenCalledWith(DEVICE.id);
  });

  it("reports 'no-assignment' and never calls GET /devices/{id} when the vehicle has no active device", async () => {
    vi.mocked(getDeviceAssignmentForVehicle).mockResolvedValue(null);

    const { result } = renderHook(() => useVehicleActiveDevice("vehicle-1"), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("no-assignment"));
    expect(result.current.device).toBeNull();
    expect(getActiveDeviceDetails).not.toHaveBeenCalled();
  });

  it("reports 'error' on a genuine fetch failure (e.g. a 403), never silently reinterpreted", async () => {
    vi.mocked(getDeviceAssignmentForVehicle).mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useVehicleActiveDevice("vehicle-1"), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.device).toBeNull();
  });

  describe("camera presence refresh (ADR-0046, audit C3)", () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    async function detailCallsAfter(cameras: typeof DEVICE.cameras, ms: number): Promise<number> {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      vi.mocked(getDeviceAssignmentForVehicle).mockResolvedValue({ deviceId: DEVICE.id });
      vi.mocked(getActiveDeviceDetails).mockResolvedValue({ ...DEVICE, cameras });
      const { result } = renderHook(() => useVehicleActiveDevice("vehicle-1"), { wrapper });
      await waitFor(() => expect(result.current.status).toBe("ready"));
      const before = vi.mocked(getActiveDeviceDetails).mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
      });
      return vi.mocked(getActiveDeviceDetails).mock.calls.length - before;
    }

    it("re-checks within about 10 s while a camera is still unknown (terminal not reported yet)", async () => {
      const unknown = [{ ...DEVICE.cameras[0], videoSignal: "unknown" as const }];
      expect(await detailCallsAfter(unknown, 10_500)).toBeGreaterThanOrEqual(1);
    });

    it("keeps the normal one-minute refresh once every camera is known", async () => {
      const known = [{ ...DEVICE.cameras[0], videoSignal: "present" as const }];
      expect(await detailCallsAfter(known, 10_500)).toBe(0);
    });
  });
});
