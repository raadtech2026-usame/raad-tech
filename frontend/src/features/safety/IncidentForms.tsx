import { useEffect, useState, type FormEvent, type TextareaHTMLAttributes } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardPlus, X } from "lucide-react";
import { Button } from "../../shared/components/Button/Button";
import { ConfirmDialog } from "../../shared/components/ConfirmDialog/ConfirmDialog";
import { FormDrawer } from "../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { Toggle } from "../../shared/components/Toggle/Toggle";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import {
  changeIncidentStatus,
  listStaffOptions,
  listVehicleOptions,
  notifyIncidentParents,
  recordIncident,
  searchStudentOptions,
  updateIncident,
  type Incident,
  type IncidentCategory,
  type IncidentSeverity,
  type IncidentStatus,
  type Option,
} from "./api";
import { CATEGORIES, INCIDENT_STATUS, NEXT_STATUSES, SEVERITIES, toLocalInput } from "./labels";
import styles from "./Safety.module.css";

export function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Please try again.";
}

export function invalidateSafety(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["safety"] });
  queryClient.invalidateQueries({ queryKey: ["daily-operations"] });
}

function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={styles.textarea} {...props} />;
}

// ---- people pickers -----------------------------------------------------------------------------

function Chips({ items, onRemove }: { items: Option[]; onRemove: (id: string) => void }) {
  if (items.length === 0) return null;
  return (
    <div className={styles.chips}>
      {items.map((item) => (
        <span key={item.id} className={styles.chip}>
          {item.label}
          <button type="button" className={styles.chipRemove} aria-label={`Remove ${item.label}`} onClick={() => onRemove(item.id)}>
            <X size={12} />
          </button>
        </span>
      ))}
    </div>
  );
}

function StudentPicker({ value, onChange }: { value: Option[]; onChange: (next: Option[]) => void }) {
  const [search, setSearch] = useState("");
  const term = search.trim();
  const query = useQuery({
    queryKey: ["safety", "student-search", term],
    queryFn: () => searchStudentOptions(term),
    enabled: term.length >= 2,
    staleTime: 30_000,
  });
  const chosen = new Set(value.map((v) => v.id));
  const suggestions = (query.data ?? []).filter((s) => !chosen.has(s.id));
  return (
    <FormField label="Students involved" hint="Optional. Their parents can be sent a notice from the incident.">
      <Chips items={value} onRemove={(id) => onChange(value.filter((v) => v.id !== id))} />
      <Input aria-label="Search students" placeholder="Type a name…" value={search} onChange={(e) => setSearch(e.target.value)} />
      {term.length >= 2 && suggestions.length > 0 && (
        <ul className={styles.suggestions}>
          {suggestions.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                className={styles.suggestion}
                onClick={() => {
                  onChange([...value, s]);
                  setSearch("");
                }}
              >
                {s.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </FormField>
  );
}

function StaffPicker({ value, onChange, enabled }: { value: Option[]; onChange: (next: Option[]) => void; enabled: boolean }) {
  const query = useQuery({ queryKey: ["safety", "staff-options"], queryFn: listStaffOptions, enabled, staleTime: 60_000 });
  const chosen = new Set(value.map((v) => v.id));
  return (
    <FormField label="Staff involved" hint="Optional.">
      <Chips items={value} onRemove={(id) => onChange(value.filter((v) => v.id !== id))} />
      <Select
        aria-label="Add staff member"
        value=""
        onChange={(e) => {
          const picked = (query.data ?? []).find((o) => o.id === e.target.value);
          if (picked) onChange([...value, picked]);
        }}
      >
        <option value="">Add a staff member…</option>
        {(query.data ?? [])
          .filter((o) => !chosen.has(o.id))
          .map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
      </Select>
    </FormField>
  );
}

// ---- record / edit ------------------------------------------------------------------------------

interface FormValues {
  category: IncidentCategory;
  severity: IncidentSeverity;
  occurredAt: string;
  title: string;
  description: string;
  actionsTaken: string;
  vehicleId: string;
  staff: Option[];
  students: Option[];
}

function initialValues(incident: Incident | null): FormValues {
  if (!incident) {
    return {
      category: "other",
      severity: "medium",
      occurredAt: toLocalInput(new Date()),
      title: "",
      description: "",
      actionsTaken: "",
      vehicleId: "",
      staff: [],
      students: [],
    };
  }
  return {
    category: incident.category,
    severity: incident.severity,
    occurredAt: toLocalInput(new Date(incident.occurredAt)),
    title: incident.title ?? "",
    description: incident.description ?? "",
    actionsTaken: incident.actionsTaken ?? "",
    vehicleId: incident.vehicleId ?? "",
    staff: incident.staffIds.map((id, i) => ({ id, label: incident.staffNames[i] ?? id })),
    students: incident.studentIds.map((id, i) => ({ id, label: incident.studentNames[i] ?? id })),
  };
}

export interface IncidentFormProps {
  open: boolean;
  /** `null` records a new incident. */
  incident: Incident | null;
  onClose: () => void;
  onSaved?: (incident: Incident) => void;
}

/**
 * ADR-0056: an operational record of what happened on a bus. Not an insurance claim, a legal
 * case or a disciplinary record — the form asks only what an operator needs to follow up.
 */
export function IncidentForm({ open, incident, onClose, onSaved }: IncidentFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<FormValues>(() => initialValues(incident));
  const vehicles = useQuery({ queryKey: ["safety", "vehicle-options"], queryFn: listVehicleOptions, enabled: open, staleTime: 60_000 });

  useEffect(() => {
    if (open) setValues(initialValues(incident));
  }, [open, incident]);

  const mutation = useMutation({
    mutationFn: () => {
      const input = {
        category: values.category,
        severity: values.severity,
        occurredAt: new Date(values.occurredAt).toISOString(),
        title: values.title.trim(),
        description: values.description.trim() || null,
        actionsTaken: values.actionsTaken.trim() || null,
        vehicleId: values.vehicleId || null,
        staffIds: values.staff.map((s) => s.id),
        studentIds: values.students.map((s) => s.id),
      };
      return incident ? updateIncident(incident.id, input) : recordIncident(input);
    },
    onSuccess: (saved) => {
      invalidateSafety(queryClient);
      toast.success(incident ? "Incident updated" : "Incident recorded", saved.title ?? "");
      onSaved?.(saved);
      onClose();
    },
    onError: (error) => toast.error("Could not save", errorText(error)),
  });

  const invalid = !values.title.trim() || !values.occurredAt;
  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!invalid) mutation.mutate();
  };
  const set = <K extends keyof FormValues>(key: K, value: FormValues[K]) => setValues((v) => ({ ...v, [key]: value }));

  return (
    <FormDrawer
      open={open}
      onClose={() => !mutation.isPending && onClose()}
      icon={<ClipboardPlus size={22} />}
      iconTint="var(--color-warning-tint)"
      iconColor="var(--color-warning)"
      title={incident ? "Edit incident" : "Record an incident"}
      subtitle="Visible in full to Org Admins only"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" loading={mutation.isPending} disabled={invalid} onClick={() => submit()}>
            {incident ? "Save" : "Record"}
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={submit} noValidate>
        <FormField label="Title">
          <Input aria-label="Title" value={values.title} maxLength={200} placeholder="What happened, in a few words" onChange={(e) => set("title", e.target.value)} />
        </FormField>
        <div className={styles.formRow}>
          <FormField label="Category">
            <Select aria-label="Category" value={values.category} onChange={(e) => set("category", e.target.value as IncidentCategory)}>
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Severity">
            <Select aria-label="Severity" value={values.severity} onChange={(e) => set("severity", e.target.value as IncidentSeverity)}>
              {SEVERITIES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
          </FormField>
        </div>
        <div className={styles.formRow}>
          <FormField label="When">
            <Input type="datetime-local" aria-label="When" value={values.occurredAt} onChange={(e) => set("occurredAt", e.target.value)} />
          </FormField>
          <FormField label="Bus">
            <Select aria-label="Bus" value={values.vehicleId} onChange={(e) => set("vehicleId", e.target.value)}>
              <option value="">No bus</option>
              {(vehicles.data ?? []).map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </Select>
          </FormField>
        </div>
        <FormField label="What happened">
          <Textarea aria-label="What happened" value={values.description} maxLength={4000} onChange={(e) => set("description", e.target.value)} />
        </FormField>
        <FormField label="Actions taken">
          <Textarea aria-label="Actions taken" value={values.actionsTaken} maxLength={4000} onChange={(e) => set("actionsTaken", e.target.value)} />
        </FormField>
        <StaffPicker value={values.staff} onChange={(next) => set("staff", next)} enabled={open} />
        <StudentPicker value={values.students} onChange={(next) => set("students", next)} />
      </form>
    </FormDrawer>
  );
}

// ---- status -----------------------------------------------------------------------------------

export function StatusDialog({ incident, onClose }: { incident: Incident | null; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const options = incident ? NEXT_STATUSES[incident.status] : [];
  const [status, setStatus] = useState<IncidentStatus | "">("");
  const [resolution, setResolution] = useState("");
  const [inError, setInError] = useState(false);

  useEffect(() => {
    if (incident) {
      setStatus(NEXT_STATUSES[incident.status][0] ?? "");
      setResolution("");
      setInError(false);
    }
  }, [incident]);

  const closing = status === "closed";
  const mutation = useMutation({
    mutationFn: () =>
      changeIncidentStatus(incident!.id, {
        status: status as IncidentStatus,
        resolution: resolution.trim() || null,
        recordedInError: closing && inError,
      }),
    onSuccess: () => {
      invalidateSafety(queryClient);
      toast.success("Status changed", INCIDENT_STATUS[status as IncidentStatus].label);
      onClose();
    },
    onError: (error) => toast.error("Could not change the status", errorText(error)),
  });

  return (
    <ConfirmDialog
      open={incident !== null}
      title="Move this incident on"
      description={closing ? "Closing is final: a closed incident can no longer be edited." : undefined}
      confirmLabel="Change status"
      loading={mutation.isPending}
      confirmDisabled={!status || (closing && !resolution.trim())}
      onConfirm={() => mutation.mutate()}
      onCancel={onClose}
    >
      <div className={styles.form}>
        <FormField label="New status">
          <Select aria-label="New status" value={status} onChange={(e) => setStatus(e.target.value as IncidentStatus)}>
            {options.map((s) => (
              <option key={s} value={s}>
                {INCIDENT_STATUS[s].label}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label={closing ? "Resolution (required to close)" : "Resolution"}>
          <Textarea aria-label="Resolution" value={resolution} maxLength={4000} onChange={(e) => setResolution(e.target.value)} />
        </FormField>
        {closing && (
          <Toggle
            label="Recorded in error"
            description="Keeps the entry, marked as a mistake, instead of deleting it."
            checked={inError}
            onChange={(e) => setInError(e.target.checked)}
          />
        )}
      </div>
    </ConfirmDialog>
  );
}

// ---- parent notice ------------------------------------------------------------------------------

export function NotifyParentsDialog({ incident, onClose }: { incident: Incident | null; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (incident) setMessage("");
  }, [incident]);

  const mutation = useMutation({
    mutationFn: () => notifyIncidentParents(incident!.id, message.trim()),
    onSuccess: () => {
      invalidateSafety(queryClient);
      toast.success("Notice sent", "The parents of the linked students are being notified.");
      onClose();
    },
    onError: (error) => toast.error("Could not send", errorText(error)),
  });

  const count = incident?.studentIds.length ?? 0;
  return (
    <ConfirmDialog
      open={incident !== null}
      title="Notify parents"
      description={`Sent to the parents of ${count} linked student${count === 1 ? "" : "s"}, and kept on the timeline.`}
      confirmLabel="Send notice"
      tone="danger"
      loading={mutation.isPending}
      confirmDisabled={!message.trim()}
      onConfirm={() => mutation.mutate()}
      onCancel={onClose}
    >
      <FormField label="Message" hint="Parents will read this exactly as written.">
        <Textarea aria-label="Message to parents" value={message} maxLength={1000} onChange={(e) => setMessage(e.target.value)} />
      </FormField>
    </ConfirmDialog>
  );
}
