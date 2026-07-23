import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserRound } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Select } from "../../../shared/components/Select/Select";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { changeTripDriver, listDriversForPicker, type Trip } from "./api";
import styles from "./ChangeTripDriverForm.module.css";

// Matches `transport_ops.domain.value_objects`'s own `_ULID_PATTERN`.
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;

const schema = z.object({
  driverId: z
    .string()
    .min(1, "Driver is required")
    .refine((value) => ULID_PATTERN.test(value), { message: "Select a valid driver" }),
});

type FormValues = z.infer<typeof schema>;
const DEFAULT_VALUES: FormValues = { driverId: "" };

export interface ChangeTripDriverFormProps {
  open: boolean;
  onClose: () => void;
  trip: Trip | null;
}

/**
 * `PATCH /trips/{id}/driver` (`ChangeTripDriverRequest`, body `{driver_id}` — "change driver — no
 * device change", API Contracts line 132) — a distinct, explicit UI action on the trip detail
 * drawer, matching `AssignDeviceForm.tsx`'s precedent for how a distinct backend command becomes
 * its own dedicated form rather than a hidden field on `ScheduleTripForm`.
 *
 * The driver picker is global, not organization-scoped — see `./api.ts`'s `listDriversForPicker`
 * docstring for the discovered whitelist gap this reflects; a cross-organization pick still
 * surfaces the backend's real `DomainError` verbatim via a toast.
 */
export function ChangeTripDriverForm({ open, onClose, trip }: ChangeTripDriverFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const driversQuery = useQuery({
    queryKey: ["drivers", "trip-change-driver-picker"],
    queryFn: () => listDriversForPicker(""),
    enabled: open && trip !== null,
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
      if (!trip) {
        return Promise.reject(new Error("No trip selected."));
      }
      return changeTripDriver(trip.id, values.driverId);
    },
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["trips", "list"] });
      queryClient.invalidateQueries({ queryKey: ["trips", "detail", updated.id] });
      toast.success("Driver changed", "This trip's driver has been updated.");
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not change the driver.";
      toast.error("Change driver failed", message);
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
  // renders, mirroring `AssignDeviceForm.tsx`'s identical `device === null` guard.
  if (!open || !trip) {
    return null;
  }

  const driverOptions = driversQuery.data ?? [];
  const driverError = errors.driverId?.message ?? (driversQuery.isError ? "Could not load drivers." : undefined);

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<UserRound size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Change driver"
      subtitle="Reassign this trip to a different driver"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Change driver
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <FormField label="Driver" error={driverError}>
          <Select {...register("driverId")} disabled={driversQuery.isLoading} aria-label="Driver">
            <option value="">{driversQuery.isLoading ? "Loading drivers…" : "Select a driver"}</option>
            {driverOptions.map((driver) => (
              <option key={driver.id} value={driver.id}>
                {driver.licenseNo}
              </option>
            ))}
          </Select>
        </FormField>
      </form>
    </FormDrawer>
  );
}
