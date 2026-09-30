# ADR-0056: Incident Log

## Status

**Proposed** (2026-09-30), Phase 3, with ADR-0055 and ADR-0057.

## Context

Operators need to be "responding quickly to operational incidents" (Project Brief §2.4), and no
approved document defines an incident. Accidents, breakdowns, medical events, behaviour problems
and a child left behind are today recorded nowhere RAAD can link to the bus, trip, staff and date
they concern.

**This is an operational record, not an HR or legal system.** No disciplinary records, driver
scoring, insurance claims or case management.

## Decision

### 1. `Incident` in `transport_ops`

An incident links to the things `transport_ops` owns (trips, routes, staff, students), so it
lives there.

- `category`: `accident`, `breakdown`, `medical`, `behaviour`, `near_miss`, `delay`,
  `student_left_behind`, `other`.
- `severity`: `low`, `medium`, `high`, `critical`. Fixed, not configurable.
- `occurred_at`; optional `vehicle_id` (cross-module id, organization-checked through
  `VehicleDirectoryPort`), `trip_id`, `route_id`.
- `title`, `description`, `actions_taken`.
- `status`: `open → investigating → resolved → closed`. Closing needs a resolution note; an entry
  made by mistake is closed as `recorded_in_error`. **Never deleted.**
- Links: staff involved (`incident_staff`) and, optionally, students involved
  (`incident_students`), both in the same organization.
- `source_alert_id` when created from a safety alert (ADR-0055).

Picking a trip fills in its bus, route and driver as defaults the admin can change.

### 2. Timeline

`incident_notes`: dated follow-up notes (who, when, text), append-only. Status changes also
appear on the timeline, from the audit trail.

### 3. From alert to incident

"Create incident" on a safety alert creates an incident with category `accident` for collision or
rollover, `other` otherwise, severity `critical` for critical alert types, the alert's bus, time
and trip, and marks the alert `resolved` with the incident's id. This is composed at the
interfaces layer from `tracking`'s and `transport_ops`'s application services, never a
cross-module table read.

### 4. Parents

Not automatic. On an incident with linked students, the Org Admin may send "notify parents"
with a message they write. It goes to those students' linked parents as an in-app `system`
notification (`data.kind = "incident_notice"`), and the timeline records that it was sent.

### 5. Visibility

- Org Admin: everything.
- Founder, Regional Manager, Support Staff: category, severity, status, dates and bus only. The
  title, description, actions, linked staff and students, and notes are nulled at the API edge,
  and the response says so (`private_fields_visible`). Incidents can involve children and
  medical details.
- Finance Staff, driver, parent: nothing. (A parent receives only a notice the admin chose to
  send.)

Events carry ids, category, severity and status only, never the text or the people.

### 6. Surfaces and permissions

`/incidents` (list, create, get, update, status, notes, notify-parents) and
`POST /safety-alerts/{id}/incident`. `transport_ops.incidents.{list,read}` to org_admin, founder,
regional_manager and support_staff; `transport_ops.incidents.manage` to org_admin. From an alert
or an incident, the bus's recording at that time opens in the existing playback page (ADR-0044,
Org Admin only). No file is stored. The Daily Operations board shows a badge on a bus with an
alert or incident that day.

## Consequences

- Operators get one place to record and follow incidents, linked to everything they concern.
- Not built: photos and documents (no file store), drivers reporting from the app (Phase 5),
  safety reports and dashboards (Phase 6).
