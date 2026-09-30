import { apiRequest } from "../../shared/api/client";
import { buildOffsetListQuery } from "../../shared/api/listParams";
import type { OffsetPageWire } from "../../shared/api/types";

/**
 * Safety alerts (ADR-0055, ADR-0057) and the incident log (ADR-0056).
 *
 * An alert is a device alarm that started; a repeat while it is still open only bumps
 * `occurrences`. Alarms are not hardware-verified yet: the terminal has never raised one on the
 * bench, so everything here is proven against synthetic frames only.
 *
 * Incident text, people and notes come back `null`/empty for everyone but the Org Admin;
 * `privateFieldsVisible` says when that happened.
 */

export type AlertStatus = "open" | "acknowledged" | "resolved" | "false_alarm";
export type IncidentStatus = "open" | "investigating" | "resolved" | "closed";
export type IncidentCategory =
  | "accident"
  | "breakdown"
  | "medical"
  | "behaviour"
  | "near_miss"
  | "delay"
  | "student_left_behind"
  | "other";
export type IncidentSeverity = "low" | "medium" | "high" | "critical";
export type NoteKind = "note" | "status_change" | "parent_notice";

export interface SafetyAlert {
  id: string;
  vehicleId: string;
  deviceId: string | null;
  alarmType: string;
  isCritical: boolean;
  status: AlertStatus;
  raisedAt: string;
  lastRaisedAt: string;
  receivedAt: string;
  isLate: boolean;
  occurrences: number;
  latitude: number | null;
  longitude: number | null;
  speedKph: number | null;
  tripId: string | null;
  incidentId: string | null;
  deviceConfirmation: "requested" | "unavailable" | null;
  acknowledgedAt: string | null;
  closedAt: string | null;
}

export interface IncidentNote {
  id: string;
  kind: NoteKind;
  body: string;
  authorId: string | null;
  createdAt: string;
}

export interface Incident {
  id: string;
  category: IncidentCategory;
  severity: IncidentSeverity;
  status: IncidentStatus;
  occurredAt: string;
  vehicleId: string | null;
  tripId: string | null;
  routeId: string | null;
  title: string | null;
  description: string | null;
  actionsTaken: string | null;
  resolution: string | null;
  recordedInError: boolean;
  staffIds: string[];
  staffNames: string[];
  studentIds: string[];
  studentNames: string[];
  sourceAlertId: string | null;
  closedAt: string | null;
  createdAt: string;
  notes: IncidentNote[];
  privateFieldsVisible: boolean;
}

// ---- wire -----------------------------------------------------------------------------------

/* eslint-disable @typescript-eslint/no-explicit-any */
export function toAlert(w: any): SafetyAlert {
  return {
    id: w.id,
    vehicleId: w.vehicle_id,
    deviceId: w.device_id ?? null,
    alarmType: w.alarm_type,
    isCritical: w.is_critical,
    status: w.status,
    raisedAt: w.raised_at,
    lastRaisedAt: w.last_raised_at,
    receivedAt: w.received_at,
    isLate: w.is_late,
    occurrences: w.occurrences,
    latitude: w.latitude,
    longitude: w.longitude,
    speedKph: w.speed_kph,
    tripId: w.trip_id,
    incidentId: w.incident_id,
    deviceConfirmation: w.device_confirmation,
    acknowledgedAt: w.acknowledged_at,
    closedAt: w.closed_at,
  };
}

export function toIncident(w: any): Incident {
  return {
    id: w.id,
    category: w.category,
    severity: w.severity,
    status: w.status,
    occurredAt: w.occurred_at,
    vehicleId: w.vehicle_id,
    tripId: w.trip_id,
    routeId: w.route_id,
    title: w.title,
    description: w.description,
    actionsTaken: w.actions_taken,
    resolution: w.resolution,
    recordedInError: w.recorded_in_error,
    staffIds: w.staff_ids ?? [],
    staffNames: w.staff_names ?? [],
    studentIds: w.student_ids ?? [],
    studentNames: w.student_names ?? [],
    sourceAlertId: w.source_alert_id,
    closedAt: w.closed_at,
    createdAt: w.created_at,
    notes: (w.notes ?? []).map((n: any) => ({
      id: n.id,
      kind: n.kind,
      body: n.body,
      authorId: n.author_id,
      createdAt: n.created_at,
    })),
    privateFieldsVisible: w.private_fields_visible,
  };
}
/* eslint-enable @typescript-eslint/no-explicit-any */

// ---- alerts -----------------------------------------------------------------------------------

export interface AlertFilter {
  statuses?: AlertStatus[];
  vehicleId?: string;
  /** ISO datetimes. */
  start?: string;
  end?: string;
}

export async function listAlerts(filter: AlertFilter = {}): Promise<SafetyAlert[]> {
  const params = new URLSearchParams();
  for (const s of filter.statuses ?? []) params.append("status", s);
  if (filter.vehicleId) params.set("vehicle_id", filter.vehicleId);
  if (filter.start) params.set("start", filter.start);
  if (filter.end) params.set("end", filter.end);
  const wire = await apiRequest<unknown[]>(`/safety-alerts?${params.toString()}`);
  return wire.map(toAlert);
}

export type AlertAction = "acknowledge" | "resolve" | "false-alarm";

export async function actOnAlert(id: string, action: AlertAction): Promise<SafetyAlert> {
  return toAlert(await apiRequest(`/safety-alerts/${id}/${action}`, { method: "POST", body: {} }));
}

// ---- incidents --------------------------------------------------------------------------------

export interface IncidentFilter {
  statuses?: IncidentStatus[];
  category?: IncidentCategory;
  vehicleId?: string;
  start?: string;
  end?: string;
}

export async function listIncidents(filter: IncidentFilter = {}): Promise<Incident[]> {
  const params = new URLSearchParams();
  for (const s of filter.statuses ?? []) params.append("status", s);
  if (filter.category) params.set("category", filter.category);
  if (filter.vehicleId) params.set("vehicle_id", filter.vehicleId);
  if (filter.start) params.set("start", filter.start);
  if (filter.end) params.set("end", filter.end);
  const wire = await apiRequest<unknown[]>(`/incidents?${params.toString()}`);
  return wire.map(toIncident);
}

export async function getIncident(id: string): Promise<Incident> {
  return toIncident(await apiRequest(`/incidents/${id}`));
}

export interface IncidentInput {
  category: IncidentCategory;
  severity: IncidentSeverity;
  /** ISO datetime. */
  occurredAt: string;
  title: string;
  description: string | null;
  actionsTaken: string | null;
  vehicleId: string | null;
  staffIds: string[];
  studentIds: string[];
}

function incidentBody(input: IncidentInput) {
  return {
    category: input.category,
    severity: input.severity,
    occurred_at: input.occurredAt,
    title: input.title,
    description: input.description,
    actions_taken: input.actionsTaken,
    vehicle_id: input.vehicleId,
    staff_ids: input.staffIds,
    student_ids: input.studentIds,
  };
}

export async function recordIncident(input: IncidentInput): Promise<Incident> {
  return toIncident(await apiRequest("/incidents", { method: "POST", body: incidentBody(input) }));
}

/** Sends every field: the edit form always holds the whole incident. */
export async function updateIncident(id: string, input: IncidentInput): Promise<Incident> {
  return toIncident(await apiRequest(`/incidents/${id}`, { method: "PATCH", body: incidentBody(input) }));
}

/** ADR-0056 §2: records the incident, then resolves the alert with its id. */
export async function recordIncidentFromAlert(alertId: string): Promise<Incident> {
  return toIncident(await apiRequest(`/incidents/from-alert/${alertId}`, { method: "POST", body: {} }));
}

export async function changeIncidentStatus(
  id: string,
  input: { status: IncidentStatus; resolution: string | null; recordedInError: boolean },
): Promise<Incident> {
  return toIncident(
    await apiRequest(`/incidents/${id}/status`, {
      method: "POST",
      body: { status: input.status, resolution: input.resolution, recorded_in_error: input.recordedInError },
    }),
  );
}

export async function addIncidentNote(id: string, body: string): Promise<Incident> {
  return toIncident(await apiRequest(`/incidents/${id}/notes`, { method: "POST", body: { body } }));
}

export async function notifyIncidentParents(id: string, message: string): Promise<Incident> {
  return toIncident(await apiRequest(`/incidents/${id}/notify-parents`, { method: "POST", body: { message } }));
}

// ---- pickers (self-contained copies, `.claude/rules/frontend.md` #1) ------------------------

export interface Option {
  id: string;
  label: string;
}

export async function listVehicleOptions(): Promise<Option[]> {
  const query = buildOffsetListQuery({ page: 1, pageSize: 100, sort: { field: "plate_no", direction: "asc" }, filters: {}, search: "" });
  const wire = await apiRequest<OffsetPageWire<{ id: string; plate_no: string; label: string | null }>>(`/vehicles?${query}`);
  return wire.data.map((v) => ({ id: v.id, label: v.label ? `${v.plate_no} — ${v.label}` : v.plate_no }));
}

export async function listStaffOptions(): Promise<Option[]> {
  const query = buildOffsetListQuery({ page: 1, pageSize: 100, sort: { field: "full_name", direction: "asc" }, filters: {}, search: "" });
  const wire = await apiRequest<OffsetPageWire<{ id: string; full_name: string; role_name: string | null }>>(`/transport-staff?${query}`);
  return wire.data.map((s) => ({ id: s.id, label: s.role_name ? `${s.full_name} — ${s.role_name}` : s.full_name }));
}

/** Searched rather than listed: a school has far more students than one page. */
export async function searchStudentOptions(search: string): Promise<Option[]> {
  const query = buildOffsetListQuery({ page: 1, pageSize: 20, sort: { field: "full_name", direction: "asc" }, filters: {}, search });
  const wire = await apiRequest<OffsetPageWire<{ id: string; full_name: string }>>(`/students?${query}`);
  return wire.data.map((s) => ({ id: s.id, label: s.full_name }));
}
