import { useQuery } from "@tanstack/react-query";
import { getActiveDeviceDetails, getDeviceAssignmentForVehicle, type ActiveDevice } from "./api";

export type VehicleActiveDeviceStatus = "idle" | "loading" | "no-assignment" | "ready" | "error";

export interface UseVehicleActiveDeviceResult {
  status: VehicleActiveDeviceStatus;
  device: ActiveDevice | null;
}

/**
 * ADR-0028 §C/§G: the **sole** path by which the unified Vehicle Operations view learns a
 * vehicle's active device. Two-step resolution, mirroring ADR-0027's own endpoint shape exactly:
 * `GET /vehicles/{id}/device-assignment` (device_id) -> `GET /devices/{device_id}` (cameras/
 * is_online/terminal_id). Deliberately never reads a `device_id` off any GPS position frame or
 * snapshot — `useVehiclePosition` (this same feature folder) has no `device_id` anywhere in its
 * own return shape, by construction, so there is nothing here to accidentally fall back to.
 *
 * `status` distinguishes "no vehicle selected yet" (`idle`) from "vehicle selected, resolution
 * in flight" (`loading`) from "vehicle has no active device" (`no-assignment`, the honest 404
 * case) from a genuine fetch failure (`error`, e.g. a 403 for a caller lacking
 * `fleet_device.devices.read` — never silently swallowed or reinterpreted client-side).
 */
export function useVehicleActiveDevice(vehicleId: string): UseVehicleActiveDeviceResult {
  const assignmentQuery = useQuery({
    queryKey: ["vehicles", "device-assignment", vehicleId],
    queryFn: () => getDeviceAssignmentForVehicle(vehicleId),
    enabled: vehicleId !== "",
  });

  const deviceId = assignmentQuery.data?.deviceId ?? null;

  const deviceQuery = useQuery({
    queryKey: ["devices", "active-device", deviceId],
    queryFn: () => getActiveDeviceDetails(deviceId as string),
    enabled: deviceId !== null,
  });

  if (vehicleId === "") {
    return { status: "idle", device: null };
  }
  if (assignmentQuery.isError || deviceQuery.isError) {
    return { status: "error", device: null };
  }
  if (assignmentQuery.isLoading) {
    return { status: "loading", device: null };
  }
  if (deviceId === null) {
    return { status: "no-assignment", device: null };
  }
  if (deviceQuery.data) {
    return { status: "ready", device: deviceQuery.data };
  }
  return { status: "loading", device: null };
}
