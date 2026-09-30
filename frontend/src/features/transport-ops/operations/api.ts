import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery } from "../../../shared/api/listParams";
import type { OffsetPageWire } from "../../../shared/api/types";

/**
 * Daily transport operations (ADR-0052, ADR-0053, ADR-0054): the weekly timetable, closed days,
 * trip generation, staff unavailability and cover, the daily board, and trip cancellation.
 *
 * Unavailability notes come back `null` for everyone but the Org Admin; `privateFieldsVisible`
 * says when that happened.
 */

export type TripPeriod = "morning" | "afternoon";
export type UnavailabilityReason = "sick" | "personal" | "training" | "other";
export type UncoveredReason = "driver_inactive" | "driver_not_active" | "driver_unavailable";

export interface TimetableEntry {
  id: string;
  routeId: string;
  routeName: string | null;
  vehicleId: string;
  tripType: TripPeriod;
  weekdays: number[];
  plannedDeparture: string | null;
  defaultDriverId: string;
  defaultDriverName: string | null;
  validFrom: string;
  validUntil: string | null;
  isActive: boolean;
}

export interface Closure {
  id: string;
  startsOn: string;
  endsOn: string;
  label: string;
  withdrawnAt: string | null;
}

export interface Cover {
  id: string;
  unavailabilityId: string;
  absentStaffId: string;
  absentStaffName: string;
  substituteStaffId: string;
  substituteStaffName: string;
  vehicleId: string;
  startsOn: string;
  endsOn: string;
  withdrawnAt: string | null;
  tripsReassigned: number;
  warnings: string[];
}

export interface Unavailability {
  id: string;
  staffId: string;
  staffName: string;
  startsOn: string;
  endsOn: string;
  reason: UnavailabilityReason;
  note: string | null;
  withdrawnAt: string | null;
  covers: Cover[];
  privateFieldsVisible: boolean;
}

export interface BoardTrip {
  id: string;
  tripType: TripPeriod;
  routeId: string;
  routeName: string | null;
  plannedDeparture: string | null;
  driverId: string;
  driverName: string | null;
  status: string;
  cancelledReason: string | null;
  uncoveredReason: UncoveredReason | null;
}

export interface BoardCrew {
  staffId: string;
  staffName: string;
  roleName: string | null;
  isSubstitute: boolean;
  isUnavailable: boolean;
  coveredBy: string | null;
}

export interface BoardVehicle {
  vehicleId: string;
  trips: BoardTrip[];
  crew: BoardCrew[];
  crewGaps: number;
}

export interface DailyBoard {
  date: string;
  closures: string[];
  vehicles: BoardVehicle[];
  uncoveredTrips: number;
}

export interface GenerationResult {
  start: string;
  days: number;
  dryRun: boolean;
  toCreate: { timetableEntryId: string; scheduledDate: string; tripType: TripPeriod; vehicleId: string; isSubstitute: boolean }[];
  skipped: { timetableEntryId: string; scheduledDate: string | null; reason: string }[];
  closedDays: string[];
  created: number;
}

// ---- wire -----------------------------------------------------------------------------------

/* eslint-disable @typescript-eslint/no-explicit-any */
function toTimetableEntry(w: any): TimetableEntry {
  return {
    id: w.id,
    routeId: w.route_id,
    routeName: w.route_name,
    vehicleId: w.vehicle_id,
    tripType: w.trip_type,
    weekdays: w.weekdays,
    plannedDeparture: w.planned_departure,
    defaultDriverId: w.default_driver_id,
    defaultDriverName: w.default_driver_name,
    validFrom: w.valid_from,
    validUntil: w.valid_until,
    isActive: w.is_active,
  };
}

function toClosure(w: any): Closure {
  return { id: w.id, startsOn: w.starts_on, endsOn: w.ends_on, label: w.label, withdrawnAt: w.withdrawn_at };
}

export function toCover(w: any): Cover {
  return {
    id: w.id,
    unavailabilityId: w.unavailability_id,
    absentStaffId: w.absent_staff_id,
    absentStaffName: w.absent_staff_name,
    substituteStaffId: w.substitute_staff_id,
    substituteStaffName: w.substitute_staff_name,
    vehicleId: w.vehicle_id,
    startsOn: w.starts_on,
    endsOn: w.ends_on,
    withdrawnAt: w.withdrawn_at,
    tripsReassigned: w.trips_reassigned ?? 0,
    warnings: w.warnings ?? [],
  };
}

export function toUnavailability(w: any): Unavailability {
  return {
    id: w.id,
    staffId: w.staff_id,
    staffName: w.staff_name,
    startsOn: w.starts_on,
    endsOn: w.ends_on,
    reason: w.reason,
    note: w.note,
    withdrawnAt: w.withdrawn_at,
    covers: (w.covers ?? []).map(toCover),
    privateFieldsVisible: w.private_fields_visible,
  };
}

export function toBoard(w: any): DailyBoard {
  return {
    date: w.date,
    closures: w.closures,
    uncoveredTrips: w.uncovered_trips,
    vehicles: w.vehicles.map((v: any) => ({
      vehicleId: v.vehicle_id,
      crewGaps: v.crew_gaps,
      trips: v.trips.map((t: any) => ({
        id: t.id,
        tripType: t.trip_type,
        routeId: t.route_id,
        routeName: t.route_name,
        plannedDeparture: t.planned_departure,
        driverId: t.driver_id,
        driverName: t.driver_name,
        status: t.status,
        cancelledReason: t.cancelled_reason,
        uncoveredReason: t.uncovered_reason,
      })),
      crew: v.crew.map((c: any) => ({
        staffId: c.staff_id,
        staffName: c.staff_name,
        roleName: c.role_name,
        isSubstitute: c.is_substitute,
        isUnavailable: c.is_unavailable,
        coveredBy: c.covered_by,
      })),
    })),
  };
}

function toGeneration(w: any): GenerationResult {
  return {
    start: w.start,
    days: w.days,
    dryRun: w.dry_run,
    created: w.created,
    closedDays: w.closed_days,
    skipped: w.skipped.map((s: any) => ({ timetableEntryId: s.timetable_entry_id, scheduledDate: s.scheduled_date, reason: s.reason })),
    toCreate: w.to_create.map((p: any) => ({
      timetableEntryId: p.timetable_entry_id,
      scheduledDate: p.scheduled_date,
      tripType: p.trip_type,
      vehicleId: p.vehicle_id,
      isSubstitute: p.is_substitute,
    })),
  };
}
/* eslint-enable @typescript-eslint/no-explicit-any */

// ---- calls ----------------------------------------------------------------------------------

export async function getDailyBoard(date: string): Promise<DailyBoard> {
  return toBoard(await apiRequest(`/daily-operations?date=${encodeURIComponent(date)}`));
}

export async function listTimetable(): Promise<TimetableEntry[]> {
  const wire = await apiRequest<unknown[]>("/route-timetable");
  return wire.map(toTimetableEntry);
}

export interface TimetableInput {
  routeId: string;
  vehicleId: string;
  tripType: TripPeriod;
  weekdays: number[];
  defaultDriverId: string;
  validFrom: string;
  validUntil: string | null;
  plannedDeparture: string | null;
  isActive: boolean;
}

function timetableBody(input: TimetableInput) {
  return {
    route_id: input.routeId,
    vehicle_id: input.vehicleId,
    trip_type: input.tripType,
    weekdays: input.weekdays,
    default_driver_id: input.defaultDriverId,
    valid_from: input.validFrom,
    valid_until: input.validUntil,
    planned_departure: input.plannedDeparture,
    is_active: input.isActive,
  };
}

export async function saveTimetableEntry(input: TimetableInput, id?: string): Promise<TimetableEntry> {
  const wire = await apiRequest(id ? `/route-timetable/${id}` : "/route-timetable", {
    method: id ? "PUT" : "POST",
    body: timetableBody(input),
  });
  return toTimetableEntry(wire);
}

export async function listClosures(start: string, end: string): Promise<Closure[]> {
  const wire = await apiRequest<unknown[]>(`/operating-closures?start=${start}&end=${end}`);
  return wire.map(toClosure);
}

export async function recordClosure(input: { startsOn: string; endsOn: string; label: string }): Promise<Closure> {
  return toClosure(
    await apiRequest("/operating-closures", {
      method: "POST",
      body: { starts_on: input.startsOn, ends_on: input.endsOn, label: input.label },
    }),
  );
}

export async function withdrawClosure(id: string): Promise<Closure> {
  return toClosure(await apiRequest(`/operating-closures/${id}/withdraw`, { method: "POST", body: {} }));
}

export async function listUnavailability(filter: { staffId?: string; start?: string; end?: string }): Promise<Unavailability[]> {
  const params = new URLSearchParams();
  if (filter.staffId) params.set("staff_id", filter.staffId);
  if (filter.start) params.set("start", filter.start);
  if (filter.end) params.set("end", filter.end);
  const wire = await apiRequest<unknown[]>(`/staff-unavailability?${params.toString()}`);
  return wire.map(toUnavailability);
}

export interface UnavailabilityInput {
  staffId: string;
  startsOn: string;
  endsOn: string;
  reason: UnavailabilityReason;
  note: string | null;
}

export async function recordUnavailability(input: UnavailabilityInput): Promise<Unavailability> {
  return toUnavailability(
    await apiRequest("/staff-unavailability", {
      method: "POST",
      body: { staff_id: input.staffId, starts_on: input.startsOn, ends_on: input.endsOn, reason: input.reason, note: input.note },
    }),
  );
}

export async function withdrawUnavailability(id: string): Promise<Unavailability> {
  return toUnavailability(await apiRequest(`/staff-unavailability/${id}/withdraw`, { method: "POST", body: {} }));
}

export async function createCover(input: {
  unavailabilityId: string;
  substituteStaffId: string;
  vehicleId: string;
  startsOn: string | null;
  endsOn: string | null;
}): Promise<Cover> {
  return toCover(
    await apiRequest("/staff-covers", {
      method: "POST",
      body: {
        unavailability_id: input.unavailabilityId,
        substitute_staff_id: input.substituteStaffId,
        vehicle_id: input.vehicleId,
        starts_on: input.startsOn,
        ends_on: input.endsOn,
      },
    }),
  );
}

export async function withdrawCover(id: string): Promise<Cover> {
  return toCover(await apiRequest(`/staff-covers/${id}/withdraw`, { method: "POST", body: {} }));
}

export async function generateTrips(days: number, dryRun: boolean): Promise<GenerationResult> {
  return toGeneration(await apiRequest("/trips/generate", { method: "POST", body: { days, dry_run: dryRun } }));
}

export async function cancelTrip(tripId: string, reason: string): Promise<void> {
  await apiRequest(`/trips/${tripId}/cancel`, { method: "POST", body: { reason } });
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

export async function listRouteOptions(): Promise<Option[]> {
  const query = buildOffsetListQuery({ page: 1, pageSize: 100, sort: { field: "name", direction: "asc" }, filters: { status: "active" }, search: "" });
  const wire = await apiRequest<OffsetPageWire<{ id: string; name: string }>>(`/routes?${query}`);
  return wire.data.map((r) => ({ id: r.id, label: r.name }));
}

export async function listDriverOptions(): Promise<Option[]> {
  const query = buildOffsetListQuery({ page: 1, pageSize: 100, sort: { field: "license_no", direction: "asc" }, filters: { status: "active" }, search: "" });
  const wire = await apiRequest<OffsetPageWire<{ id: string; license_no: string; full_name: string | null }>>(`/drivers?${query}`);
  return wire.data.map((d) => ({ id: d.id, label: d.full_name ? `${d.full_name} (${d.license_no})` : d.license_no }));
}

export async function listStaffOptions(): Promise<Option[]> {
  const query = buildOffsetListQuery({ page: 1, pageSize: 100, sort: { field: "full_name", direction: "asc" }, filters: { status: "active" }, search: "" });
  const wire = await apiRequest<OffsetPageWire<{ id: string; full_name: string; role_name: string | null }>>(`/transport-staff?${query}`);
  return wire.data.map((s) => ({ id: s.id, label: s.role_name ? `${s.full_name} — ${s.role_name}` : s.full_name }));
}
