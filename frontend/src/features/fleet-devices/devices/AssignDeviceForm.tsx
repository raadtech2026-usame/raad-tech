import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Select } from "../../../shared/components/Select/Select";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { assignDeviceToVehicle, listVehiclesForPicker, reassignDevice, type Device, type VehicleOption } from "./api";
import styles from "./AssignDeviceForm.module.css";

// Matches `fleet_device.domain.value_objects`'s own `_ULID_PATTERN`.
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;

const schema = z.object({
  vehicleId: z
    .string()
    .min(1, "Vehicle is required")
    .refine((value) => ULID_PATTERN.test(value), { message: "Select a valid vehicle" }),
});

type FormValues = z.infer<typeof schema>;
const DEFAULT_VALUES: FormValues = { vehicleId: "" };

export type AssignDeviceMode = "assign" | "reassign";

export interface AssignDeviceFormProps {
  open: boolean;
  onClose: () => void;
  device: Device | null;
  mode: AssignDeviceMode;
  /** Reports the vehicle the device was just bound to — `DeviceAssignmentResponse`
   * (`api/schemas.py`) carries no vehicle name, only `vehicle_id`, so `DevicesPage` needs the
   * option the operator picked (not another round trip) to show anything friendlier than a raw
   * id for the rest of this browser session — see `./api.ts`'s `listVehiclesForPicker` docstring
   * for why no persistent, cross-session lookup is possible at all. */
  onAssigned: (vehicle: VehicleOption) => void;
}

/**
 * The device↔vehicle assignment action — a distinct, explicit UI action ("assign device to
 * vehicle"/"reassign device to vehicle"), never folded silently into a form field, matching the
 * roadmap's own Phase F3 note and the backend's explicit-command modeling
 * (`POST /devices/{id}/assign` / `/reassign`,
 * `fleet_device.application.commands.AssignDeviceToVehicleCommand`/`ReassignDeviceCommand`).
 *
 * Shares one component between the "assign" (device currently `activated`, no active binding)
 * and "reassign" (device currently `assigned`, closes the old binding and opens a new one in the
 * same request — `reassign_device`, `application/services.py`) flows: same vehicle picker, same
 * validation, only the submitted mutation and copy differ — mirroring how the backend itself
 * keeps them as two thin sibling use-cases over the identical `DeviceAssignment.open(...)`
 * domain behavior.
 *
 * **The conflict path this component exists to surface honestly:** `ensure_device_has_no_active_
 * assignment`/`ensure_vehicle_has_no_active_device` (`application/validators.py`) enforce
 * "one active binding per device & per vehicle" (Phase 2 §19) — attempting to assign/reassign a
 * device to a vehicle that already has a different active device, or a device that is already
 * actively bound elsewhere, raises the backend's real `ConflictError` (HTTP 409,
 * `error.code === "CONFLICT"`) with a message naming the vehicle/device already involved. This
 * form's `onError` shows that message verbatim via a toast and keeps the drawer open for another
 * attempt, rather than failing silently or showing a generic error — a safety-adjacent invariant
 * worth its own explicit test (`.claude/rules/testing.md` #3's spirit, per the roadmap's own
 * explicit call-out for this specific invariant).
 */
export function AssignDeviceForm({ open, onClose, device, mode, onAssigned }: AssignDeviceFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const vehiclesQuery = useQuery({
    queryKey: ["vehicles", "assign-picker", device?.organizationId],
    queryFn: () => listVehiclesForPicker(device?.organizationId ?? "", ""),
    enabled: open && device !== null,
    staleTime: 30_000,
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULT_VALUES,
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      if (!device) {
        return Promise.reject(new Error("No device selected."));
      }
      return mode === "assign"
        ? assignDeviceToVehicle(device.id, values.vehicleId)
        : reassignDevice(device.id, values.vehicleId);
    },
    onSuccess: (assignment, values) => {
      queryClient.invalidateQueries({ queryKey: ["devices", "list"] });
      const vehicle = (vehiclesQuery.data ?? []).find((option) => option.id === values.vehicleId);
      toast.success(
        mode === "assign" ? "Device assigned" : "Device reassigned",
        `${device?.terminalId ?? "Device"} is now bound to ${vehicle?.plateNo ?? assignment.vehicleId}.`,
      );
      onAssigned(vehicle ?? { id: assignment.vehicleId, plateNo: assignment.vehicleId, label: null });
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message =
        error instanceof ApiError
          ? error.message
          : `Could not ${mode === "assign" ? "assign" : "reassign"} the device.`;
      toast.error(mode === "assign" ? "Assignment failed" : "Reassignment failed", message);
    },
  });

  function handleClose(): void {
    if (mutation.isPending) {
      return;
    }
    reset(DEFAULT_VALUES);
    mutation.reset();
    onClose();
  }

  const onValid = handleSubmit((values) => mutation.mutate(values));

  // Hooks above always run in the same order regardless; the early return only affects what
  // renders. `device === null` should never actually happen from `DevicesPage` (it only opens
  // this form from a row that already has a `selectedDevice`) — guarded anyway so a caller
  // mistake fails safe (nothing rendered) rather than showing a picker for no device at all.
  if (!open || !device) {
    return null;
  }
  const vehicleOptions = vehiclesQuery.data ?? [];
  const vehicleError = errors.vehicleId?.message ?? (vehiclesQuery.isError ? "Could not load vehicles." : undefined);

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Link2 size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title={mode === "assign" ? "Assign to vehicle" : "Reassign to vehicle"}
      subtitle={device ? `Terminal ${device.terminalId}` : undefined}
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            {mode === "assign" ? "Assign" : "Reassign"}
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <FormField label="Vehicle" error={vehicleError}>
          <Select {...register("vehicleId")} disabled={vehiclesQuery.isLoading} aria-label="Vehicle">
            <option value="">{vehiclesQuery.isLoading ? "Loading vehicles…" : "Select a vehicle"}</option>
            {vehicleOptions.map((vehicle) => (
              <option key={vehicle.id} value={vehicle.id}>
                {vehicle.plateNo}
                {vehicle.label ? ` — ${vehicle.label}` : ""}
              </option>
            ))}
          </Select>
        </FormField>
      </form>
    </FormDrawer>
  );
}
