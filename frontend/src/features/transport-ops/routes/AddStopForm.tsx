import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MapPin } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { addStopToRoute } from "./api";
import styles from "./AddStopForm.module.css";

// `entities.py`'s `_STOP_NAME_MAX_LENGTH` (Database Design §6.6: name VARCHAR(160)).
const STOP_NAME_MAX_LENGTH = 160;
// `_validate_latitude`/`_validate_longitude` (`domain/entities.py`): standard geographic bounds.
const MIN_LATITUDE = -90;
const MAX_LATITUDE = 90;
const MIN_LONGITUDE = -180;
const MAX_LONGITUDE = 180;

const DECIMAL_PATTERN = /^-?\d+(\.\d+)?$/;
// Matches `CreateVehicleForm.tsx`'s identical "positive whole number" pattern for `capacity`.
const POSITIVE_INT_PATTERN = /^[1-9]\d*$/;

const schema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Stop name is required")
    .max(STOP_NAME_MAX_LENGTH, `Stop name must be at most ${STOP_NAME_MAX_LENGTH} characters`),
  latitude: z
    .string()
    .trim()
    .min(1, "Latitude is required")
    .refine((value) => DECIMAL_PATTERN.test(value), { message: "Must be a valid decimal number" })
    .refine((value) => Number(value) >= MIN_LATITUDE && Number(value) <= MAX_LATITUDE, {
      message: `Latitude must be between ${MIN_LATITUDE} and ${MAX_LATITUDE}`,
    }),
  longitude: z
    .string()
    .trim()
    .min(1, "Longitude is required")
    .refine((value) => DECIMAL_PATTERN.test(value), { message: "Must be a valid decimal number" })
    .refine((value) => Number(value) >= MIN_LONGITUDE && Number(value) <= MAX_LONGITUDE, {
      message: `Longitude must be between ${MIN_LONGITUDE} and ${MAX_LONGITUDE}`,
    }),
  sequenceNo: z
    .string()
    .trim()
    .min(1, "Sequence number is required")
    .refine((value) => POSITIVE_INT_PATTERN.test(value), {
      message: "Sequence number must be a positive whole number",
    }),
  geofenceRadiusM: z
    .string()
    .trim()
    .refine((value) => value === "" || POSITIVE_INT_PATTERN.test(value), {
      message: "Geofence radius must be a positive whole number",
    }),
});

type FormValues = z.infer<typeof schema>;

const DEFAULT_VALUES: FormValues = { name: "", latitude: "", longitude: "", sequenceNo: "", geofenceRadiusM: "" };

export interface AddStopFormProps {
  open: boolean;
  onClose: () => void;
  routeId: string | null;
  routeName?: string;
  /** The next unused `sequence_no` for this route (highest existing + 1, or 1 for an empty
   * route) — pre-filled as a convenience default, not a validated suggestion; the field stays
   * fully editable since `Route.add_stop` is the real source of truth for duplicate rejection. */
  nextSequenceNo: number;
}

/**
 * The "Add stop" action on the route detail drawer — a distinct, explicit UI action, matching
 * `LinkGuardianForm.tsx`'s precedent for how a distinct backend command
 * (`POST /routes/{route_id}/stops`, `AddStopToRouteRequest`) becomes its own dedicated form
 * rather than a hidden field on `CreateRouteForm`.
 *
 * **This form only adds stops — it cannot reorder or remove one.** `Route.move_stop`/
 * `remove_stop` are implemented at the domain/application layers but have no HTTP route this
 * phase (see `./api.ts`'s `addStopToRoute` docstring for the full citation) — `RoutesPage`'s own
 * stop list carries the visible "why can't I reorder stops" affordance the roadmap's F5 entry
 * calls for; this form does not attempt to work around that gap.
 *
 * **Two distinct failure shapes to surface, both real:** a duplicate `sequence_no` within the
 * route raises `ConflictError` (409), and out-of-range coordinates/sequence raise a `DomainError`
 * — both from `Route.add_stop`. Surfaced verbatim via a toast using `error.message`, the same
 * handling every other `ApiError` consumer in this codebase already applies.
 */
export function AddStopForm({ open, onClose, routeId, routeName, nextSequenceNo }: AddStopFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULT_VALUES,
  });

  // `nextSequenceNo` is only a convenience default, recomputed per-route by the caller — reset
  // to it whenever the drawer opens (or the suggested value changes while open), never on every
  // keystroke re-render, unlike an RHF `values` option would (which resets on every new object
  // reference, wiping in-progress input).
  useEffect(() => {
    if (open) {
      reset({ ...DEFAULT_VALUES, sequenceNo: String(nextSequenceNo) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, nextSequenceNo]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      if (!routeId) {
        return Promise.reject(new Error("No route selected."));
      }
      return addStopToRoute(routeId, {
        name: values.name,
        latitude: Number(values.latitude),
        longitude: Number(values.longitude),
        sequenceNo: Number(values.sequenceNo),
        geofenceRadiusM: values.geofenceRadiusM ? Number(values.geofenceRadiusM) : null,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["routes", "detail", routeId] });
      toast.success("Stop added", "The stop has been added to this route.");
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not add the stop.";
      toast.error("Add stop failed", message);
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
  if (!open || !routeId) {
    return null;
  }

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<MapPin size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Add stop"
      subtitle={routeName ? `Add a stop to ${routeName}` : "Add a stop to this route"}
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Add stop
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <FormField label="Stop name" error={errors.name?.message}>
          <Input placeholder="e.g. Main Street & 5th Ave" invalid={!!errors.name} {...register("name")} />
        </FormField>

        <div className={styles.coordRow}>
          <FormField label="Latitude" error={errors.latitude?.message}>
            <Input placeholder="e.g. 2.0469" invalid={!!errors.latitude} {...register("latitude")} />
          </FormField>
          <FormField label="Longitude" error={errors.longitude?.message}>
            <Input placeholder="e.g. 45.3182" invalid={!!errors.longitude} {...register("longitude")} />
          </FormField>
        </div>

        <FormField
          label="Sequence number"
          hint="This stop's position in the route's ordered list. Each stop needs a unique number."
          error={errors.sequenceNo?.message}
        >
          <Input placeholder="e.g. 1" invalid={!!errors.sequenceNo} {...register("sequenceNo")} />
        </FormField>

        <FormField
          label="Geofence radius (meters)"
          hint="Optional — overrides the organization default for this stop."
          error={errors.geofenceRadiusM?.message}
        >
          <Input placeholder="e.g. 100" invalid={!!errors.geofenceRadiusM} {...register("geofenceRadiusM")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
