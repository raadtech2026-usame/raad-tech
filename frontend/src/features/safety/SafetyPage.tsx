import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardList, Plus, ShieldAlert } from "lucide-react";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { useAuthStore } from "../../shared/stores/authStore";
import { useToast } from "../../shared/components/Toast/toastStore";
import { Badge } from "../../shared/components/Badge/Badge";
import { Button } from "../../shared/components/Button/Button";
import { ConfirmDialog } from "../../shared/components/ConfirmDialog/ConfirmDialog";
import { FormDrawer } from "../../shared/components/Drawer/FormDrawer";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { Tabs } from "../../shared/components/Tabs/Tabs";
import {
  actOnAlert,
  addIncidentNote,
  getIncident,
  listAlerts,
  listIncidents,
  listVehicleOptions,
  recordIncidentFromAlert,
  type AlertAction,
  type AlertStatus,
  type Incident,
  type IncidentStatus,
  type SafetyAlert,
} from "./api";
import { IncidentForm, NotifyParentsDialog, StatusDialog, errorText, invalidateSafety } from "./IncidentForms";
import {
  ALERT_STATUS,
  INCIDENT_STATUS,
  NEXT_STATUSES,
  NOTE_KIND,
  alarmLabel,
  categoryLabel,
  formatDateTime,
  severity,
} from "./labels";
import styles from "./Safety.module.css";

function useVehicleLabels() {
  const query = useQuery({ queryKey: ["safety", "vehicle-options"], queryFn: listVehicleOptions, staleTime: 60_000 });
  return useMemo(() => new Map((query.data ?? []).map((o) => [o.id, o.label])), [query.data]);
}

/** The recorder keeps the video; this opens a search around the alarm on the Recordings page
 * (ADR-0044). Ten minutes either side, in the viewer's own time. */
export function recordingLink(deviceId: string, at: string): string {
  return `/org/recordings?device=${encodeURIComponent(deviceId)}&at=${encodeURIComponent(at)}`;
}

// ---- alerts -----------------------------------------------------------------------------------

const ALERT_FILTERS: Record<string, AlertStatus[]> = {
  attention: ["open", "acknowledged"],
  closed: ["resolved", "false_alarm"],
  all: [],
};

function AlertsPanel({ canManage, onOpenIncident }: { canManage: boolean; onOpenIncident: (id: string) => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const vehicleLabel = useVehicleLabels();
  const [filter, setFilter] = useState("attention");
  const [closingAsFalse, setClosingAsFalse] = useState<SafetyAlert | null>(null);
  const query = useQuery({ queryKey: ["safety", "alerts", filter], queryFn: () => listAlerts({ statuses: ALERT_FILTERS[filter] }) });

  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: AlertAction }) => actOnAlert(id, action),
    onSuccess: (alert, { action }) => {
      invalidateSafety(queryClient);
      setClosingAsFalse(null);
      if (action === "acknowledge" && alert.alarmType === "sos") {
        toast.success(
          "SOS acknowledged",
          alert.deviceConfirmation === "requested"
            ? "The bus terminal has been asked to clear its SOS."
            : "The bus terminal could not be reached; the SOS may stay on until it clears itself.",
        );
      } else {
        toast.success(action === "acknowledge" ? "Acknowledged" : action === "resolve" ? "Resolved" : "Closed as a false alarm");
      }
    },
    onError: (error) => toast.error("Could not update the alert", errorText(error)),
  });
  const toIncident = useMutation({
    mutationFn: (alertId: string) => recordIncidentFromAlert(alertId),
    onSuccess: (incident) => {
      invalidateSafety(queryClient);
      toast.success("Incident recorded", "The alert is resolved and linked to it.");
      onOpenIncident(incident.id);
    },
    onError: (error) => toast.error("Could not record the incident", errorText(error)),
  });

  const alerts = query.data ?? [];
  return (
    <div className={styles.page}>
      <p className={styles.notice}>
        Alerts come from the bus terminal's own alarms. They are not yet verified against real hardware: treat the first
        ones with care and tell RAAD support if an alert looks wrong.
      </p>
      <div className={styles.toolbar}>
        <FormField label="Show">
          <Select aria-label="Alert filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="attention">Needs attention</option>
            <option value="closed">Closed</option>
            <option value="all">All</option>
          </Select>
        </FormField>
      </div>
      <section className={styles.section} aria-label="Safety alerts">
        {query.isLoading ? (
          <Skeleton height={80} />
        ) : query.isError ? (
          <EmptyState icon={<ShieldAlert size={22} />} title="Could not load alerts" description={errorText(query.error)} />
        ) : alerts.length === 0 ? (
          <p className={styles.empty}>{filter === "attention" ? "No alert needs attention." : "No alerts."}</p>
        ) : (
          <ul className={styles.list}>
            {alerts.map((alert) => {
              const status = ALERT_STATUS[alert.status];
              const isClosed = alert.status === "resolved" || alert.status === "false_alarm";
              return (
                <li key={alert.id} className={styles.item}>
                  <div className={styles.itemMain}>
                    <span className={styles.itemTitle}>
                      {alarmLabel(alert.alarmType)}
                      {alert.isCritical && <Badge variant="danger">Critical</Badge>}
                      <Badge variant={status.variant} dot>
                        {status.label}
                      </Badge>
                      {alert.isLate && <Badge variant="neutral">Arrived late</Badge>}
                    </span>
                    <span className={styles.itemMeta}>
                      {vehicleLabel.get(alert.vehicleId) ?? alert.vehicleId} · {formatDateTime(alert.raisedAt)}
                      {alert.occurrences > 1 ? ` · repeated ${alert.occurrences} times, last ${formatDateTime(alert.lastRaisedAt)}` : ""}
                      {alert.speedKph !== null ? ` · ${Math.round(alert.speedKph)} km/h` : ""}
                      {alert.tripId ? " · during a trip" : ""}
                    </span>
                    {alert.latitude !== null && alert.longitude !== null && (
                      <span className={styles.itemMeta}>
                        Location {alert.latitude.toFixed(5)}, {alert.longitude.toFixed(5)}
                      </span>
                    )}
                    {alert.deviceConfirmation && (
                      <span className={styles.itemMeta}>
                        {alert.deviceConfirmation === "requested"
                          ? "Terminal asked to clear the SOS (not confirmed by hardware yet)"
                          : "Terminal could not be asked to clear the SOS"}
                      </span>
                    )}
                    {canManage && alert.deviceId && (
                      <Link className={styles.link} to={recordingLink(alert.deviceId, alert.raisedAt)}>
                        Open the recording at that time
                      </Link>
                    )}
                  </div>
                  <div className={styles.itemActions}>
                    {alert.incidentId && (
                      <Button size="sm" variant="ghost" onClick={() => onOpenIncident(alert.incidentId!)}>
                        View incident
                      </Button>
                    )}
                    {canManage && !isClosed && (
                      <>
                        {alert.status === "open" && (
                          <Button size="sm" variant="secondary" loading={act.isPending && act.variables?.id === alert.id && act.variables.action === "acknowledge"} onClick={() => act.mutate({ id: alert.id, action: "acknowledge" })}>
                            Acknowledge
                          </Button>
                        )}
                        <Button size="sm" variant="secondary" onClick={() => act.mutate({ id: alert.id, action: "resolve" })}>
                          Resolve
                        </Button>
                        {!alert.incidentId && (
                          <Button size="sm" variant="secondary" loading={toIncident.isPending && toIncident.variables === alert.id} onClick={() => toIncident.mutate(alert.id)}>
                            Record incident
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" onClick={() => setClosingAsFalse(alert)}>
                          False alarm
                        </Button>
                      </>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <ConfirmDialog
        open={closingAsFalse !== null}
        title="Close as a false alarm?"
        description="The alert is closed and kept, marked as a false alarm. If the bus raises it again, a new alert opens."
        confirmLabel="False alarm"
        loading={act.isPending}
        onConfirm={() => closingAsFalse && act.mutate({ id: closingAsFalse.id, action: "false-alarm" })}
        onCancel={() => setClosingAsFalse(null)}
      />
    </div>
  );
}

// ---- incident detail --------------------------------------------------------------------------

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className={styles.field}>
      <span className={styles.sectionTitle}>{label}</span>
      <span className={styles.fieldValue}>{value}</span>
    </div>
  );
}

function IncidentDrawer({ incidentId, canManage, onClose }: { incidentId: string | null; canManage: boolean; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const vehicleLabel = useVehicleLabels();
  const [editing, setEditing] = useState(false);
  const [changingStatus, setChangingStatus] = useState<Incident | null>(null);
  const [notifying, setNotifying] = useState<Incident | null>(null);
  const [note, setNote] = useState("");
  const query = useQuery({ queryKey: ["safety", "incident", incidentId], queryFn: () => getIncident(incidentId!), enabled: incidentId !== null });
  const addNote = useMutation({
    mutationFn: () => addIncidentNote(incidentId!, note.trim()),
    onSuccess: () => {
      invalidateSafety(queryClient);
      setNote("");
    },
    onError: (error) => toast.error("Could not add the note", errorText(error)),
  });

  const incident = query.data;
  const isClosed = incident?.status === "closed";
  const sev = incident ? severity(incident.severity) : null;
  return (
    <>
      <FormDrawer
        open={incidentId !== null && !editing}
        onClose={onClose}
        icon={<ClipboardList size={22} />}
        iconTint="var(--color-warning-tint)"
        iconColor="var(--color-warning)"
        title={incident ? incident.title ?? categoryLabel(incident.category) : "Incident"}
        subtitle={incident ? `${categoryLabel(incident.category)} · ${formatDateTime(incident.occurredAt)}` : undefined}
      >
        {query.isLoading || !incident ? (
          <Skeleton height={120} />
        ) : (
          <div className={styles.detail}>
            <div className={styles.itemTitle}>
              <Badge variant={INCIDENT_STATUS[incident.status].variant} dot>
                {INCIDENT_STATUS[incident.status].label}
              </Badge>
              {sev && <Badge variant={sev.variant}>{sev.label} severity</Badge>}
              {incident.recordedInError && <Badge variant="neutral">Recorded in error</Badge>}
              {incident.sourceAlertId && <Badge variant="info">From a device alarm</Badge>}
            </div>
            <Field label="Bus" value={incident.vehicleId ? vehicleLabel.get(incident.vehicleId) ?? incident.vehicleId : null} />
            {!incident.privateFieldsVisible ? (
              <p className={styles.notice}>The description, people involved and timeline are visible to the school's Org Admins only.</p>
            ) : (
              <>
                <Field label="What happened" value={incident.description} />
                <Field label="Actions taken" value={incident.actionsTaken} />
                <Field label="Resolution" value={incident.resolution} />
                <Field label="Staff involved" value={incident.staffNames.join(", ") || null} />
                <Field label="Students involved" value={incident.studentNames.join(", ") || null} />
                {canManage && !isClosed && (
                  <div className={styles.itemActions}>
                    <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
                      Edit
                    </Button>
                    {NEXT_STATUSES[incident.status].length > 0 && (
                      <Button size="sm" variant="secondary" onClick={() => setChangingStatus(incident)}>
                        Change status
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={incident.studentIds.length === 0}
                      title={incident.studentIds.length === 0 ? "Link the students involved first" : undefined}
                      onClick={() => setNotifying(incident)}
                    >
                      Notify parents
                    </Button>
                  </div>
                )}
                <span className={styles.sectionTitle}>Timeline</span>
                {incident.notes.length === 0 ? (
                  <p className={styles.empty}>No notes yet.</p>
                ) : (
                  <ul className={styles.timeline}>
                    {incident.notes.map((n) => (
                      <li key={n.id} className={styles.timelineItem}>
                        <span className={styles.itemMeta}>
                          {NOTE_KIND[n.kind]} · {formatDateTime(n.createdAt)}
                        </span>
                        <span className={styles.fieldValue}>{n.body}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {canManage && !isClosed && (
                  <form
                    className={styles.inlineForm}
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (note.trim()) addNote.mutate();
                    }}
                  >
                    <FormField label="Add a note">
                      <Input aria-label="New note" value={note} maxLength={4000} onChange={(e) => setNote(e.target.value)} />
                    </FormField>
                    <Button type="submit" size="sm" loading={addNote.isPending} disabled={!note.trim()}>
                      Add
                    </Button>
                  </form>
                )}
              </>
            )}
          </div>
        )}
      </FormDrawer>
      <IncidentForm open={editing} incident={incident ?? null} onClose={() => setEditing(false)} />
      <StatusDialog incident={changingStatus} onClose={() => setChangingStatus(null)} />
      <NotifyParentsDialog incident={notifying} onClose={() => setNotifying(null)} />
    </>
  );
}

// ---- incident log -----------------------------------------------------------------------------

const INCIDENT_FILTERS: Record<string, IncidentStatus[]> = {
  active: ["open", "investigating", "resolved"],
  closed: ["closed"],
  all: [],
};

function IncidentsPanel({ canManage, onOpen }: { canManage: boolean; onOpen: (id: string) => void }) {
  const vehicleLabel = useVehicleLabels();
  const [filter, setFilter] = useState("active");
  const [recording, setRecording] = useState(false);
  const query = useQuery({ queryKey: ["safety", "incidents", filter], queryFn: () => listIncidents({ statuses: INCIDENT_FILTERS[filter] }) });
  const incidents = query.data ?? [];
  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <FormField label="Show">
          <Select aria-label="Incident filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="active">Not closed</option>
            <option value="closed">Closed</option>
            <option value="all">All</option>
          </Select>
        </FormField>
        {canManage && (
          <Button leadingIcon={<Plus size={15} />} onClick={() => setRecording(true)}>
            Record an incident
          </Button>
        )}
      </div>
      <section className={styles.section} aria-label="Incidents">
        {query.isLoading ? (
          <Skeleton height={80} />
        ) : query.isError ? (
          <EmptyState icon={<ClipboardList size={22} />} title="Could not load incidents" description={errorText(query.error)} />
        ) : incidents.length === 0 ? (
          <p className={styles.empty}>No incidents.</p>
        ) : (
          <ul className={styles.list}>
            {incidents.map((incident) => {
              const sev = severity(incident.severity);
              return (
                <li key={incident.id} className={styles.item}>
                  <div className={styles.itemMain}>
                    <button type="button" className={styles.itemButton} onClick={() => onOpen(incident.id)}>
                      {incident.title ?? categoryLabel(incident.category)}
                    </button>
                    <span className={styles.itemMeta}>
                      {categoryLabel(incident.category)} · {formatDateTime(incident.occurredAt)}
                      {incident.vehicleId ? ` · ${vehicleLabel.get(incident.vehicleId) ?? incident.vehicleId}` : ""}
                    </span>
                  </div>
                  <div className={styles.itemActions}>
                    <Badge variant={sev.variant}>{sev.label}</Badge>
                    <Badge variant={INCIDENT_STATUS[incident.status].variant} dot>
                      {INCIDENT_STATUS[incident.status].label}
                    </Badge>
                    {incident.recordedInError && <Badge variant="neutral">In error</Badge>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <IncidentForm open={recording} incident={null} onClose={() => setRecording(false)} onSaved={(saved) => onOpen(saved.id)} />
    </div>
  );
}

/**
 * `/org/safety` and `/platform/safety` (ADR-0055, ADR-0056, ADR-0057): device alarms that need a
 * person, and the incident log. The Org Admin acts; Founder, Regional Manager and Support Staff
 * read, without the incident text, people or timeline (the server withholds them).
 * `canManage` is presentation only (`.claude/rules/frontend.md` #2).
 */
export function SafetyPage() {
  usePageHeader("Safety & Incidents", "Device alarms and what happened on the buses");
  const principal = useAuthStore((s) => s.principal);
  const canManage = principal?.role === "org_admin";
  const [tab, setTab] = useState("alerts");
  const [openIncident, setOpenIncident] = useState<string | null>(null);
  const tabs = [
    { id: "alerts", label: "Alerts" },
    { id: "incidents", label: "Incident log" },
  ];
  return (
    <div className={styles.page}>
      <Tabs options={tabs} activeId={tab} onSelect={setTab} />
      {tab === "alerts" && <AlertsPanel canManage={canManage} onOpenIncident={setOpenIncident} />}
      {tab === "incidents" && <IncidentsPanel canManage={canManage} onOpen={setOpenIncident} />}
      <IncidentDrawer incidentId={openIncident} canManage={canManage} onClose={() => setOpenIncident(null)} />
    </div>
  );
}
