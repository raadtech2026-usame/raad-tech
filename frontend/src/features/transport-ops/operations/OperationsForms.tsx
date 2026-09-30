import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarOff, CalendarRange, UserCheck } from "lucide-react";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import {
  createCover,
  listDriverOptions,
  listRouteOptions,
  listStaffOptions,
  listVehicleOptions,
  recordUnavailability,
  saveTimetableEntry,
  type TimetableEntry,
  type TripPeriod,
  type Unavailability,
  type UnavailabilityReason,
} from "./api";
import { UNAVAILABILITY_REASONS, WEEKDAYS, formatPeriod, isoDay } from "./labels";
import styles from "./Operations.module.css";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Please try again.";
}

function Footer({ onCancel, busy, label, onSubmit, disabled }: {
  onCancel: () => void;
  busy: boolean;
  label: string;
  onSubmit: () => void;
  disabled?: boolean;
}) {
  return (
    <div className={styles.footerActions}>
      <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
        Cancel
      </Button>
      <Button type="button" variant="primary" loading={busy} disabled={disabled} onClick={onSubmit}>
        {label}
      </Button>
    </div>
  );
}

// ---- unavailability ---------------------------------------------------------------------------

export interface UnavailabilityFormProps {
  open: boolean;
  onClose: () => void;
  /** Fixed when opened from a staff profile. */
  staffId?: string;
  staffName?: string;
}

/**
 * ADR-0053 §1: "this person cannot work from X to Y". Not leave management — nothing is
 * requested or approved. Nothing else changes: affected trips show as uncovered until a
 * substitute is named.
 */
export function UnavailabilityForm({ open, onClose, staffId, staffName }: UnavailabilityFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const today = isoDay(new Date());
  const [values, setValues] = useState({ staffId: "", startsOn: today, endsOn: today, reason: "sick" as UnavailabilityReason, note: "" });
  const staffQuery = useQuery({ queryKey: ["operations", "staff-options"], queryFn: listStaffOptions, enabled: open && !staffId });

  useEffect(() => {
    if (open) setValues({ staffId: staffId ?? "", startsOn: today, endsOn: today, reason: "sick", note: "" });
  }, [open, staffId, today]);

  const invalidDates = values.endsOn < values.startsOn;
  const mutation = useMutation({
    mutationFn: () =>
      recordUnavailability({
        staffId: values.staffId,
        startsOn: values.startsOn,
        endsOn: values.endsOn,
        reason: values.reason,
        note: values.note.trim() || null,
      }),
    onSuccess: (item) => {
      queryClient.invalidateQueries({ queryKey: ["daily-operations"] });
      queryClient.invalidateQueries({ queryKey: ["operations", "unavailability"] });
      toast.success("Unavailability recorded", `${item.staffName}: ${formatPeriod(item.startsOn, item.endsOn)}`);
      onClose();
    },
    onError: (error) => toast.error("Could not record", errorText(error)),
  });

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (values.staffId && !invalidDates) mutation.mutate();
  };

  return (
    <FormDrawer
      open={open}
      onClose={() => !mutation.isPending && onClose()}
      icon={<CalendarOff size={22} />}
      iconTint="var(--color-warning-tint)"
      iconColor="var(--color-warning)"
      title="Record unavailability"
      subtitle={staffName ?? "Someone who cannot work for a period"}
      footer={<Footer onCancel={onClose} busy={mutation.isPending} label="Record" onSubmit={() => submit()} disabled={!values.staffId || invalidDates} />}
    >
      <form className={styles.form} onSubmit={submit} noValidate>
        {!staffId && (
          <FormField label="Staff member">
            <Select aria-label="Staff member" value={values.staffId} onChange={(e) => setValues({ ...values, staffId: e.target.value })}>
              <option value="">Choose…</option>
              {(staffQuery.data ?? []).map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </Select>
          </FormField>
        )}
        <div className={styles.formRow}>
          <FormField label="From">
            <Input type="date" aria-label="From" value={values.startsOn} onChange={(e) => setValues({ ...values, startsOn: e.target.value })} />
          </FormField>
          <FormField label="Until (inclusive)" error={invalidDates ? "Ends before it starts" : undefined}>
            <Input type="date" aria-label="Until" value={values.endsOn} onChange={(e) => setValues({ ...values, endsOn: e.target.value })} />
          </FormField>
        </div>
        <FormField label="Reason">
          <Select aria-label="Reason" value={values.reason} onChange={(e) => setValues({ ...values, reason: e.target.value as UnavailabilityReason })}>
            {UNAVAILABILITY_REASONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="Note" hint="Visible to Org Admins only">
          <Input aria-label="Note" value={values.note} maxLength={500} onChange={(e) => setValues({ ...values, note: e.target.value })} />
        </FormField>
      </form>
    </FormDrawer>
  );
}

// ---- cover ------------------------------------------------------------------------------------

export interface CoverFormProps {
  unavailability: Unavailability | null;
  onClose: () => void;
}

/**
 * ADR-0053 §2: names a substitute on one bus. Creates their temporary crew assignment; when a
 * driver is covered, the substitute (who needs active driver access) takes that driver's
 * scheduled trips on that bus.
 */
export function CoverForm({ unavailability, onClose }: CoverFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const open = unavailability !== null;
  const [values, setValues] = useState({ substituteStaffId: "", vehicleId: "", startsOn: "", endsOn: "" });
  const staffQuery = useQuery({ queryKey: ["operations", "staff-options"], queryFn: listStaffOptions, enabled: open });
  const vehicleQuery = useQuery({ queryKey: ["operations", "vehicle-options"], queryFn: listVehicleOptions, enabled: open });

  useEffect(() => {
    if (unavailability) {
      setValues({ substituteStaffId: "", vehicleId: "", startsOn: unavailability.startsOn, endsOn: unavailability.endsOn });
    }
  }, [unavailability]);

  const mutation = useMutation({
    mutationFn: () =>
      createCover({
        unavailabilityId: unavailability!.id,
        substituteStaffId: values.substituteStaffId,
        vehicleId: values.vehicleId,
        startsOn: values.startsOn || null,
        endsOn: values.endsOn || null,
      }),
    onSuccess: (cover) => {
      queryClient.invalidateQueries({ queryKey: ["daily-operations"] });
      queryClient.invalidateQueries({ queryKey: ["operations", "unavailability"] });
      queryClient.invalidateQueries({ queryKey: ["trips"] });
      queryClient.invalidateQueries({ queryKey: ["transport-staff"] });
      const moved = cover.tripsReassigned ? ` ${cover.tripsReassigned} trip(s) now have ${cover.substituteStaffName} as driver.` : "";
      toast.success("Cover in place", `${cover.substituteStaffName} covers ${cover.absentStaffName}.${moved}`);
      for (const warning of cover.warnings) toast.info("Note", warning);
      onClose();
    },
    onError: (error) => toast.error("Could not create the cover", errorText(error)),
  });

  const candidates = (staffQuery.data ?? []).filter((o) => o.id !== unavailability?.staffId);
  const ready = values.substituteStaffId && values.vehicleId;

  return (
    <FormDrawer
      open={open}
      onClose={() => !mutation.isPending && onClose()}
      icon={<UserCheck size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Name a substitute"
      subtitle={unavailability ? `For ${unavailability.staffName}, ${formatPeriod(unavailability.startsOn, unavailability.endsOn)}` : undefined}
      footer={<Footer onCancel={onClose} busy={mutation.isPending} label="Create cover" onSubmit={() => mutation.mutate()} disabled={!ready} />}
    >
      <form className={styles.form} onSubmit={(e) => { e.preventDefault(); if (ready) mutation.mutate(); }} noValidate>
        <FormField label="Substitute" hint="To cover a driver, the substitute needs active driver access.">
          <Select aria-label="Substitute" value={values.substituteStaffId} onChange={(e) => setValues({ ...values, substituteStaffId: e.target.value })}>
            <option value="">Choose…</option>
            {candidates.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="Bus">
          <Select aria-label="Bus" value={values.vehicleId} onChange={(e) => setValues({ ...values, vehicleId: e.target.value })}>
            <option value="">Choose…</option>
            {(vehicleQuery.data ?? []).map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </Select>
        </FormField>
        <div className={styles.formRow}>
          <FormField label="From" hint="Within the unavailability">
            <Input type="date" aria-label="Cover from" value={values.startsOn} onChange={(e) => setValues({ ...values, startsOn: e.target.value })} />
          </FormField>
          <FormField label="Until">
            <Input type="date" aria-label="Cover until" value={values.endsOn} onChange={(e) => setValues({ ...values, endsOn: e.target.value })} />
          </FormField>
        </div>
      </form>
    </FormDrawer>
  );
}

// ---- timetable ----------------------------------------------------------------------------------

export interface TimetableFormProps {
  open: boolean;
  onClose: () => void;
  entry?: TimetableEntry | null;
}

/** ADR-0052 §1: one regular run. Editing never changes trips already generated. */
export function TimetableForm({ open, onClose, entry }: TimetableFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const today = isoDay(new Date());
  const blank = {
    routeId: "",
    vehicleId: "",
    tripType: "morning" as TripPeriod,
    weekdays: [1, 2, 3, 4, 5],
    defaultDriverId: "",
    validFrom: today,
    validUntil: "",
    plannedDeparture: "",
    isActive: true,
  };
  const [values, setValues] = useState(blank);
  const routes = useQuery({ queryKey: ["operations", "route-options"], queryFn: listRouteOptions, enabled: open });
  const vehicles = useQuery({ queryKey: ["operations", "vehicle-options"], queryFn: listVehicleOptions, enabled: open });
  const drivers = useQuery({ queryKey: ["operations", "driver-options"], queryFn: listDriverOptions, enabled: open });

  useEffect(() => {
    if (!open) return;
    setValues(
      entry
        ? {
            routeId: entry.routeId,
            vehicleId: entry.vehicleId,
            tripType: entry.tripType,
            weekdays: entry.weekdays,
            defaultDriverId: entry.defaultDriverId,
            validFrom: entry.validFrom,
            validUntil: entry.validUntil ?? "",
            plannedDeparture: entry.plannedDeparture?.slice(0, 5) ?? "",
            isActive: entry.isActive,
          }
        : blank,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, entry]);

  const mutation = useMutation({
    mutationFn: () =>
      saveTimetableEntry(
        {
          ...values,
          validUntil: values.validUntil || null,
          plannedDeparture: values.plannedDeparture ? `${values.plannedDeparture}:00` : null,
        },
        entry?.id,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["operations", "timetable"] });
      toast.success(entry ? "Timetable updated" : "Added to the timetable", "Trips already generated are unchanged.");
      onClose();
    },
    onError: (error) => toast.error("Could not save", errorText(error)),
  });

  const toggleDay = (day: number) =>
    setValues({
      ...values,
      weekdays: values.weekdays.includes(day) ? values.weekdays.filter((d) => d !== day) : [...values.weekdays, day].sort(),
    });
  const invalid =
    !values.routeId || !values.vehicleId || !values.defaultDriverId || values.weekdays.length === 0 || (values.validUntil !== "" && values.validUntil < values.validFrom);

  const options = (list: { id: string; label: string }[] | undefined) =>
    (list ?? []).map((o) => (
      <option key={o.id} value={o.id}>
        {o.label}
      </option>
    ));

  return (
    <FormDrawer
      open={open}
      onClose={() => !mutation.isPending && onClose()}
      icon={<CalendarRange size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title={entry ? "Edit timetable entry" : "New timetable entry"}
      subtitle="A regular run: this bus, this route, these weekdays"
      footer={<Footer onCancel={onClose} busy={mutation.isPending} label="Save" onSubmit={() => mutation.mutate()} disabled={invalid} />}
    >
      <form className={styles.form} onSubmit={(e) => { e.preventDefault(); if (!invalid) mutation.mutate(); }} noValidate>
        <FormField label="Route">
          <Select aria-label="Route" value={values.routeId} onChange={(e) => setValues({ ...values, routeId: e.target.value })}>
            <option value="">Choose…</option>
            {options(routes.data)}
          </Select>
        </FormField>
        <div className={styles.formRow}>
          <FormField label="Bus">
            <Select aria-label="Bus" value={values.vehicleId} onChange={(e) => setValues({ ...values, vehicleId: e.target.value })}>
              <option value="">Choose…</option>
              {options(vehicles.data)}
            </Select>
          </FormField>
          <FormField label="Period">
            <Select aria-label="Period" value={values.tripType} onChange={(e) => setValues({ ...values, tripType: e.target.value as TripPeriod })}>
              <option value="morning">Morning</option>
              <option value="afternoon">Afternoon</option>
            </Select>
          </FormField>
        </div>
        <FormField label="Weekdays" error={values.weekdays.length === 0 ? "Choose at least one day" : undefined}>
          <div className={styles.weekdays} role="group" aria-label="Weekdays">
            {WEEKDAYS.map((d) => (
              <label key={d.value} className={styles.weekday}>
                <input type="checkbox" checked={values.weekdays.includes(d.value)} onChange={() => toggleDay(d.value)} />
                {d.short}
              </label>
            ))}
          </div>
        </FormField>
        <div className={styles.formRow}>
          <FormField label="Default driver" hint="Required: every trip has a driver">
            <Select aria-label="Default driver" value={values.defaultDriverId} onChange={(e) => setValues({ ...values, defaultDriverId: e.target.value })}>
              <option value="">Choose…</option>
              {options(drivers.data)}
            </Select>
          </FormField>
          <FormField label="Departure" hint="Optional">
            <Input type="time" aria-label="Departure" value={values.plannedDeparture} onChange={(e) => setValues({ ...values, plannedDeparture: e.target.value })} />
          </FormField>
        </div>
        <div className={styles.formRow}>
          <FormField label="From">
            <Input type="date" aria-label="Valid from" value={values.validFrom} onChange={(e) => setValues({ ...values, validFrom: e.target.value })} />
          </FormField>
          <FormField label="Until" hint="Optional">
            <Input type="date" aria-label="Valid until" value={values.validUntil} onChange={(e) => setValues({ ...values, validUntil: e.target.value })} />
          </FormField>
        </div>
        {entry && (
          <label className={styles.weekday}>
            <input type="checkbox" checked={values.isActive} onChange={(e) => setValues({ ...values, isActive: e.target.checked })} />
            Active (generates trips)
          </label>
        )}
      </form>
    </FormDrawer>
  );
}
