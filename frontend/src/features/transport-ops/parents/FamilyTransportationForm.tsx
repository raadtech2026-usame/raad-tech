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
  getRouteWithStops,
  listRoutesForPicker,
  listVehiclesForPicker,
  setFamilyTransportation,
} from "./api";
import styles from "./forms.module.css";

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

export interface FamilyTransportationFormProps {
  open: boolean;
  onClose: () => void;
  parentId: string | null;
  parentName?: string;
  organizationId: string | null;
}

/**
 * `PUT /parents/{parent_id}/transportation` (2026-09-12 business-model correction) — the one
 * place an admin assigns or changes a family's Vehicle/Route/Stops. Applies identically to
 * every one of this Parent's currently-linked children, replacing each child's own current
 * active assignment (if any) with a fresh one against the new values, in one backend
 * transaction — this is the family-wide replacement for opening each Student separately.
 *
 * Route/Pickup/Dropoff/Vehicle picker shape mirrors `student-assignments/AssignStudentForm.tsx`
 * exactly (route → dependent stop pickers → optional, organization-scoped vehicle picker); the
 * picker functions themselves are this folder's own duplicated copies (`./api.ts`), not a
 * cross-feature-folder import.
 *
 * **No pre-fill from the family's current assignment** — a deliberate scope cut for this first
 * pass, not an oversight: each child's own `StudentAssignmentSection` already shows the current
 * route/pickup/dropoff/vehicle (identically, for every child), so the admin can see today's
 * values there before opening this form to change them.
 */
export function FamilyTransportationForm({
  open,
  onClose,
  parentId,
  parentName,
  organizationId,
}: FamilyTransportationFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const routesQuery = useQuery({
    queryKey: ["routes", "family-transportation-picker"],
    queryFn: () => listRoutesForPicker(""),
    enabled: open && parentId !== null,
    staleTime: 30_000,
  });

  const vehiclesQuery = useQuery({
    queryKey: ["vehicles", "family-transportation-picker", organizationId],
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
    queryKey: ["routes", "stops-for-family-transportation", watchedRouteId],
    queryFn: () => getRouteWithStops(watchedRouteId),
    enabled: open && !!watchedRouteId,
    staleTime: 30_000,
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      if (!parentId) {
        return Promise.reject(new Error("No parent selected."));
      }
      return setFamilyTransportation(parentId, {
        routeId: values.routeId,
        pickupStopId: values.pickupStopId,
        dropoffStopId: values.dropoffStopId,
        vehicleId: values.vehicleId || null,
      });
    },
    onSuccess: () => {
      // Every child's own assignment changed together - invalidate broadly rather than one
      // query key per child, the same "re-fetch, don't hand-merge" posture this codebase's own
      // WS-driven queries already follow (`CLAUDE.md`'s Phase F8 note).
      queryClient.invalidateQueries({ queryKey: ["student-assignments"] });
      queryClient.invalidateQueries({ queryKey: ["parents", "linked-students"] });
      toast.success(
        "Family transportation set",
        parentName ? `${parentName}'s children now share this route and vehicle.` : "This family's children now share this route and vehicle.",
      );
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not set this family's transportation.";
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

  if (!open || !parentId) {
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
      title="Family transportation"
      subtitle={parentName ? `Set ${parentName}'s Vehicle/Route/Stops` : "Set this family's Vehicle/Route/Stops"}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Save
          </Button>
        </>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <p>
          Applied to every child currently linked to this parent — RAAD's "one family, one bus"
          rule means they always share the same route and vehicle.
        </p>

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

        <FormField label="Vehicle" hint="Optional — the specific bus this family rides, if already known.">
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
