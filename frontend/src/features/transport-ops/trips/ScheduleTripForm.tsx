import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { useAuthStore } from "../../../shared/stores/authStore";
import { ApiError } from "../../../shared/api/types";
import {
  listDriversForPicker,
  listOrganizationsForPicker,
  listRoutesForPicker,
  listVehiclesForPicker,
  scheduleTrip,
} from "./api";
import { tripTypeLabel } from "./labels";
import styles from "./ScheduleTripForm.module.css";

// Matches `transport_ops.domain.value_objects`'s own `_ULID_PATTERN`.
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;

function buildSchema(requiresOrganizationPicker: boolean) {
  return z.object({
    organizationId: requiresOrganizationPicker
      ? z
          .string()
          .trim()
          .min(1, "Organization is required")
          .refine((value) => ULID_PATTERN.test(value), {
            message: "Must be a valid organization ID (26-character ULID)",
          })
      : z.string(),
    vehicleId: z
      .string()
      .min(1, "Vehicle is required")
      .refine((value) => ULID_PATTERN.test(value), { message: "Select a valid vehicle" }),
    driverId: z
      .string()
      .min(1, "Driver is required")
      .refine((value) => ULID_PATTERN.test(value), { message: "Select a valid driver" }),
    routeId: z
      .string()
      .min(1, "Route is required")
      .refine((value) => ULID_PATTERN.test(value), { message: "Select a valid route" }),
    tripType: z.enum(["morning", "afternoon"], { message: "Select a trip type" }),
    scheduledDate: z.string().min(1, "Scheduled date is required"),
  });
}

type FormValues = z.infer<ReturnType<typeof buildSchema>>;

const DEFAULT_VALUES: FormValues = {
  organizationId: "",
  vehicleId: "",
  driverId: "",
  routeId: "",
  tripType: "morning",
  scheduledDate: "",
};

export interface ScheduleTripFormProps {
  open: boolean;
  onClose: () => void;
}

/**
 * `POST /trips` (`ScheduleTripRequest`, `transport_ops.api.schemas`) exactly: `organization_id`,
 * `vehicle_id`, `driver_id`, `route_id`, `trip_type`, `scheduled_date`. `organization_id` follows
 * `CreateRouteForm.tsx`'s exact precedent: an Org Admin's own `principal.organizationId` is used
 * directly; `founder` (the only other role holding `transport_ops.trips.create`) sees a
 * `GET /organizations` picker.
 *
 * **The vehicle picker is organization-scoped once an organization is known** (real backend
 * filter support, `./api.ts`'s `listVehiclesForPicker`); **the driver and route pickers are not**
 * — see `./api.ts`'s `listDriversForPicker`/`listRoutesForPicker` docstrings for the discovered
 * whitelist gap this reflects. A cross-organization driver/route pick still surfaces the
 * backend's real `DomainError` verbatim via a toast on submit; the form does not pretend to
 * prevent it client-side where it can't.
 */
export function ScheduleTripForm({ open, onClose }: ScheduleTripFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const principal = useAuthStore((s) => s.principal);
  const ownOrganizationId = principal?.organizationId ?? null;

  const showOrganizationPicker = ownOrganizationId === null;

  const organizationsQuery = useQuery({
    queryKey: ["organizations", "trip-create-picker"],
    queryFn: () => listOrganizationsForPicker(""),
    enabled: open && showOrganizationPicker,
    staleTime: 60_000,
  });

  const schema = useMemo(() => buildSchema(showOrganizationPicker), [showOrganizationPicker]);

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

  const watchedOrganizationId = watch("organizationId");
  const effectiveOrganizationId = ownOrganizationId ?? watchedOrganizationId;

  const vehiclesQuery = useQuery({
    queryKey: ["vehicles", "trip-create-picker", effectiveOrganizationId],
    queryFn: () => listVehiclesForPicker(effectiveOrganizationId, ""),
    enabled: open && !!effectiveOrganizationId,
    staleTime: 30_000,
  });

  const driversQuery = useQuery({
    queryKey: ["drivers", "trip-create-picker"],
    queryFn: () => listDriversForPicker(""),
    enabled: open,
    staleTime: 30_000,
  });

  const routesQuery = useQuery({
    queryKey: ["routes", "trip-create-picker"],
    queryFn: () => listRoutesForPicker(""),
    enabled: open,
    staleTime: 30_000,
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      scheduleTrip({
        organizationId: ownOrganizationId ?? values.organizationId,
        vehicleId: values.vehicleId,
        driverId: values.driverId,
        routeId: values.routeId,
        tripType: values.tripType,
        scheduledDate: values.scheduledDate,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips", "list"] });
      toast.success("Trip scheduled", "The trip has been added to the schedule.");
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not schedule the trip.";
      toast.error("Schedule failed", message);
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

  const organizationOptions = organizationsQuery.data ?? [];
  const organizationError =
    errors.organizationId?.message ?? (organizationsQuery.isError ? "Could not load organizations." : undefined);

  const vehicleOptions = vehiclesQuery.data ?? [];
  const vehicleError = errors.vehicleId?.message ?? (vehiclesQuery.isError ? "Could not load vehicles." : undefined);

  const driverOptions = driversQuery.data ?? [];
  const driverError = errors.driverId?.message ?? (driversQuery.isError ? "Could not load drivers." : undefined);

  const routeOptions = routesQuery.data ?? [];
  const routeError = errors.routeId?.message ?? (routesQuery.isError ? "Could not load routes." : undefined);

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<CalendarClock size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Schedule trip"
      subtitle="Assign a vehicle, driver, and route to a scheduled date"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Schedule trip
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        {showOrganizationPicker && (
          <FormField label="Organization" error={organizationError}>
            <Select {...register("organizationId")} disabled={organizationsQuery.isLoading} aria-label="Organization">
              <option value="">
                {organizationsQuery.isLoading ? "Loading organizations…" : "Select an organization"}
              </option>
              {organizationOptions.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </Select>
          </FormField>
        )}

        <FormField label="Vehicle" error={vehicleError}>
          <Select
            {...register("vehicleId")}
            disabled={!effectiveOrganizationId || vehiclesQuery.isLoading}
            aria-label="Vehicle"
          >
            <option value="">
              {!effectiveOrganizationId
                ? "Select an organization first"
                : vehiclesQuery.isLoading
                  ? "Loading vehicles…"
                  : "Select a vehicle"}
            </option>
            {vehicleOptions.map((vehicle) => (
              <option key={vehicle.id} value={vehicle.id}>
                {vehicle.plateNo}
                {vehicle.label ? ` — ${vehicle.label}` : ""}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField
          label="Driver"
          hint="Drivers across every organization are shown — the driver must belong to the same organization as this trip, or the request will be rejected."
          error={driverError}
        >
          <Select {...register("driverId")} disabled={driversQuery.isLoading} aria-label="Driver">
            <option value="">{driversQuery.isLoading ? "Loading drivers…" : "Select a driver"}</option>
            {driverOptions.map((driver) => (
              <option key={driver.id} value={driver.id}>
                {driver.licenseNo}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField
          label="Route"
          hint="Routes across every organization are shown — the route must belong to the same organization as this trip, or the request will be rejected."
          error={routeError}
        >
          <Select {...register("routeId")} disabled={routesQuery.isLoading} aria-label="Route">
            <option value="">{routesQuery.isLoading ? "Loading routes…" : "Select a route"}</option>
            {routeOptions.map((route) => (
              <option key={route.id} value={route.id}>
                {route.name}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label="Trip type" error={errors.tripType?.message}>
          <Select {...register("tripType")} aria-label="Trip type">
            <option value="morning">{tripTypeLabel("morning")}</option>
            <option value="afternoon">{tripTypeLabel("afternoon")}</option>
          </Select>
        </FormField>

        <FormField label="Scheduled date" error={errors.scheduledDate?.message}>
          <Input type="date" invalid={!!errors.scheduledDate} {...register("scheduledDate")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
