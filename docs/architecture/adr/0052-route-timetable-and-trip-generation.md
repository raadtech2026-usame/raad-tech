# ADR-0052: Route Timetable, Closed Days and Daily Trip Generation (amends Database Design §6.8)

## Status

**Proposed** (2026-09-30), Phase 2 of the transport-management roadmap ("Daily Transport
Operations"), with ADR-0053 and ADR-0054. Product decisions taken by the user on 2026-09-30
("use your recommended answers").

## Context

Phase-2 Enterprise Architecture §7.4 and Backend LLD §5 name a scheduler job for "daily trip
generation from route schedules… configurable per org calendar, with school-day/holiday
awareness". No approved document defines the schedule or the calendar, so the job was never
built (CLAUDE.md, Known gaps: "Trip generation is deliberately not registered"). Today every trip
is created by hand, one at a time, and nothing stops two trips for the same bus, date and period.

This ADR supplies the missing data model.

## Decision

### 1. `route_timetable_entries`: the weekly plan

One row per regular run:

- `route_id` (FK), `vehicle_id` (cross-module id, organization-checked through
  `VehicleDirectoryPort` like crew assignments, ADR-0050), `trip_type` (`morning`/`afternoon`);
- `weekdays`: ISO weekdays 1–7 (`SMALLINT[]`, at least one);
- `planned_departure`: optional `TIME`, for display and alert timing only;
- `default_driver_id` (FK `drivers`), **required**: `trips.driver_id` is NOT NULL, so an entry
  without a driver could not produce a trip;
- `valid_from`, optional `valid_until`, `is_active`.

Rules, enforced by the service:
- the route, the bus and the default driver belong to the entry's organization;
- two active entries may not put the same bus on the same period and weekday for overlapping
  validity (409);
- editing an entry affects only trips not yet generated. Generated trips are records and are
  changed individually (ADR-0053, ADR-0054).

### 2. `operating_closures`: closed days

`starts_on`, `ends_on` (inclusive) and a `label` ("Eid holidays"). No transport runs on those
days. Only closures are recorded, not full term calendars. Closures may overlap. Adding a closure
never deletes trips already generated inside it. The daily board lists them, and the admin cancels
them (ADR-0054).

### 3. Trips gain their origin and a uniqueness rule

- `trips.timetable_entry_id` (nullable FK) and `trips.planned_departure` (nullable `TIME`, copied
  at generation);
- **`ux_trips__vehicle_date_type`**: one non-cancelled trip per `(vehicle_id, scheduled_date,
  trip_type)`, a partial unique index (`WHERE status <> 'cancelled'`). It applies to hand-made
  trips too: a second morning trip for the same bus and day becomes a 409. A cancelled trip does
  not block a replacement.

### 4. Generation

`TripGenerationService` builds a **plan** for a date range, and one plan serves the scheduled job
and the manual action, the same pattern as ADR-0048's invoice run.
- For each active entry, each date in `[today, today + horizon)` matching a weekday, inside
  validity, not closed: a trip, unless the bus already has **any** trip for that date and period,
  **including a cancelled one**. A cancelled trip is a decision, and generation never undoes it.
- The driver is the entry's default driver, **or the covering substitute** when that driver is
  unavailable that day and a driver cover exists for that bus (ADR-0053). Otherwise the default
  driver is kept and the trip shows as uncovered.
- An inactive route, an inactive default driver or an entry whose bus left the organization is
  skipped and reported, never guessed around.

Surfaces:
- the worker job `generate_daily_trips`: hourly, horizon 7 days
  (`RAAD_WORKERS__TRIP_GENERATION_HORIZON_DAYS`), **opt-in**
  (`RAAD_WORKERS__AUTO_GENERATE_TRIPS`, default false, like automatic invoices);
- `POST /trips/generate` (preview with `dry_run=true`) for "Generate the next 7 days" on demand.
  Running either twice creates nothing new (the unique index is the backstop).

Dates are UTC calendar dates, the same convention as the invoice run. For RAAD's deployment
(UTC+3) the day boundary falls at 03:00 local time, before any morning trip.

### 5. Permissions

`transport_ops.timetable.{list,manage}` and `transport_ops.closures.{list,manage}`, plus
`transport_ops.trips.generate`. Manage and generate go to `org_admin`; list goes to founder,
regional_manager and support_staff. Granted in the same migration.

## Consequences

- The Known gap "trip generation not registered" closes.
- **Migration risk:** existing duplicate trips would block the unique index. The migration counts
  them and refuses, naming them, rather than deleting or cancelling anything.
- Trips remain the unit the driver app, tracking (CR-1) and notifications already use. Nothing
  downstream changes.
- Not built: term calendars, per-stop timings, ETA, and a student roster snapshot (`trip_students`,
  deferred; there is no boarding capture, D1).
