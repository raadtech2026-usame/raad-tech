import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigation } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Select } from "../../../shared/components/Select/Select";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import {
  assignStudentToRoute,
  getRouteWithStops,
  listRoutesForPicker,
  listVehiclesForPicker,
} from "./api";
import styles from "./AssignStudentForm.module.css";

// Matches `transport_ops.domain.value_objects`'s own `_ULID_PATTERN`.
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;
const ulidField = (label: string) =>
  z
    .string()
    .min(1, `${label} is required`)
    .refine((value) => ULID_PATTERN.test(value), { message: `Select a valid ${label.toLowerCase()}` });

const schema = z.object({
  routeId: ulidField("Route"),
  pickupStopId: ulidField("Pickup stop"),
  dropoffStopId: ulidField("Dropoff stop"),
  vehicleId: z.string(),
});

type FormValues = z.infer<typeof schema>;
const DEFAULT_VALUES: FormValues = { routeId: "", pickupStopId: "", dropoffStopId: "", vehicleId: "" };

export interface AssignStudentFormProps {
  open: boolean;
  onClose: () => void;
  studentId: string | null;
  studentName?: string;
  organizationId: string | null;
}

/**
 * `POST /student-assignments` (`AssignStudentToRouteRequest`, `transport_ops.api.schemas`) —
 * "the CR-1 gate record" (API Contracts §4.3 line 127). The route picker is global (no backend
 * organization filter available — see `./api.ts`'s `listRoutesForPicker` docstring); the pickup/
 * dropoff stop pickers are dependent selects, populated from the *chosen* route's own embedded,
 * pre-ordered stop list (`getRouteWithStops`) — disabled until a route is picked, mirroring
 * `CreateDriverForm.tsx`'s "pick the parent first, dependent picker enables after" pattern. The
 * vehicle picker is optional (`AssignStudentToRouteRequest.vehicle_id` is nullable) and *is*
 * organization-scoped, since `fleet_device`'s own repository does whitelist that filter.
 *
 * **Cross-organization student/route and a duplicate active assignment both surface the
 * backend's real error verbatim** (`DomainError`/`ConflictError`) via a toast — this form does
 * not attempt to pre-validate either client-side.
 */
export function AssignStudentForm({ open, onClose, studentId, studentName, organizationId }: AssignStudentFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const routesQuery = useQuery({
    queryKey: ["routes", "assign-student-picker"],
    queryFn: () => listRoutesForPicker(""),
    enabled: open && studentId !== null,
    staleTime: 30_000,
  });

  const vehiclesQuery = useQuery({
    queryKey: ["vehicles", "assign-student-picker", organizationId],
    queryFn: () => listVehiclesForPicker(organizationId ?? "", ""),
    enabled: open && !!organizationId,
    staleTime: 30_000,
  });

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULT_VALUES,
  });

  const watchedRouteId = watch("routeId");

  const routeStopsQuery = useQuery({
    queryKey: ["routes", "stops-for-assign-student", watchedRouteId],
    queryFn: () => getRouteWithStops(watchedRouteId),
    enabled: open && !!watchedRouteId,
    staleTime: 30_000,
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      if (!studentId || !organizationId) {
        return Promise.reject(new Error("No student selected."));
      }
      return assignStudentToRoute({
        organizationId,
        studentId,
        routeId: values.routeId,
        pickupStopId: values.pickupStopId,
        dropoffStopId: values.dropoffStopId,
        vehicleId: values.vehicleId || null,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["student-assignments", "active-for-student", studentId] });
      toast.success("Route assigned", studentName ? `${studentName} has been assigned to this route.` : "The student has been assigned to this route.");
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not assign the student to this route.";
      toast.error("Assignment failed", message);
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
  // renders, mirroring `LinkGuardianForm.tsx`'s identical `studentId === null` guard.
  if (!open || !studentId) {
    return null;
  }

  const routeOptions = routesQuery.data ?? [];
  const routeError = errors.routeId?.message ?? (routesQuery.isError ? "Could not load routes." : undefined);

  const stopOptions = routeStopsQuery.data?.stops ?? [];
  const pickupError =
    errors.pickupStopId?.message ?? (routeStopsQuery.isError ? "Could not load this route's stops." : undefined);
  const dropoffError =
    errors.dropoffStopId?.message ?? (routeStopsQuery.isError ? "Could not load this route's stops." : undefined);

  const vehicleOptions = vehiclesQuery.data ?? [];

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Navigation size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Assign to route"
      subtitle={studentName ? `Assign ${studentName} to a route` : "Assign this student to a route"}
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Assign
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <FormField label="Route" error={routeError}>
          <Select {...register("routeId")} disabled={routesQuery.isLoading} aria-label="Route">
            <option value="">{routesQuery.isLoading ? "Loading routes…" : "Select a route"}</option>
            {routeOptions.map((route) => (
              <option key={route.id} value={route.id}>
                {route.name}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label="Pickup stop" error={pickupError}>
          <Select
            {...register("pickupStopId")}
            disabled={!watchedRouteId || routeStopsQuery.isLoading}
            aria-label="Pickup stop"
          >
            <option value="">
              {!watchedRouteId ? "Select a route first" : routeStopsQuery.isLoading ? "Loading stops…" : "Select a stop"}
            </option>
            {stopOptions.map((stop) => (
              <option key={stop.id} value={stop.id}>
                {stop.sequenceNo}. {stop.name}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label="Dropoff stop" error={dropoffError}>
          <Select
            {...register("dropoffStopId")}
            disabled={!watchedRouteId || routeStopsQuery.isLoading}
            aria-label="Dropoff stop"
          >
            <option value="">
              {!watchedRouteId ? "Select a route first" : routeStopsQuery.isLoading ? "Loading stops…" : "Select a stop"}
            </option>
            {stopOptions.map((stop) => (
              <option key={stop.id} value={stop.id}>
                {stop.sequenceNo}. {stop.name}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label="Vehicle" hint="Optional — the specific bus this student rides, if already known.">
          <Select {...register("vehicleId")} disabled={vehiclesQuery.isLoading} aria-label="Vehicle">
            <option value="">{vehiclesQuery.isLoading ? "Loading vehicles…" : "No vehicle"}</option>
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
