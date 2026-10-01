# ADR-0061: Mobile self-service API for parents and drivers

- **Status:** Accepted
- **Date:** 2026-10-02
- **Extends:** ADR-0023 (`/me`), ADR-0060 (`/me/transport`)
- **Touches:** ADR-0053 (unavailability), ADR-0056 (incident log), ADR-0014 (geofences)

## Context

The Parent and Driver mobile app (Phase 5 of the transport roadmap) needs data neither role can
reach. Every existing transport route is an organization-wide read behind a permission the
`parent` and `driver` roles do not hold, and should not hold. `GET /trips` already lets a
driver list every trip in their organization, which is more than a driver needs.

Two notification defects also stood between a parent and a useful alert: "approaching stop"
went to every parent on the bus, and one stop with no radius, or one stop the bus skipped,
silenced every later stop for the rest of the trip.

## Decision

### 1. Self-scoped routes, owned by `transport_ops`

New routes under `/api/v1/me`, served by `SelfServiceApplicationService`. Like ADR-0023 they
depend on `get_current_user` only. No permission and no grant is added. No route takes a
parent, driver, staff or student id. The two path ids that exist (a trip, an unavailability)
are checked for ownership and answer 404 when they are someone else's.

| Route | Caller | Returns |
|---|---|---|
| `GET /me/trips?from&to` | driver | the trips they drive (default: today to +7 days) |
| `GET /me/trips?from&to` | parent | trips on each child's bus and route (default: −30 to +7 days), with the caller's own children on each |
| `GET /me/trips/{trip_id}` | driver | own trip: stops, crew that day, passengers |
| `GET /me/crew?date` | driver | who works on the buses they drive or are assigned to |
| `GET /me/documents` | driver | own current documents and compliance status |
| `GET/POST /me/unavailability`, `DELETE /me/unavailability/{id}` | driver | own days off |
| `GET/POST /me/incidents` | driver | incidents they reported, and their status |

The window of `/me/trips` is at most 92 days. Starting and ending a trip stay on the existing
`POST /trips/{id}/start|end`, which already refuse another driver's trip.

They live in `transport_ops` because the data is its own; only the bus's plate and label come
from `fleet_device`, through a new `VehicleSummaryPort` whose adapter sits in the composition
root (`.claude/rules/backend.md` #3).

### 2. What a parent's trip history can and cannot say

A parent sees the trips of the bus and route their child is assigned to, from the day of that
assignment. Each has a status: scheduled, in progress, completed, cancelled (with the reason).
RAAD has no boarding record, so the app says "trip completed", never "your child boarded", and
shows nothing as "missed". `StudentAssignment` has no effective dates, so history before the
current assignment is not shown.

### 3. Passengers on a driver's trip

The driver sees each child's name and the names of their pickup and dropoff stops. That is
what the job needs. No parent, phone number or address is returned.

### 4. Unavailability is reported, not requested

ADR-0053 stays: no request, no approval, nothing reassigned automatically. A driver states the
days (today or later, at most 31, not overlapping one already recorded). The office is told by
an in-app notification, and the daily board and uncovered-trip alerts show the gap. A driver
can withdraw it only until a substitute is arranged; after that it is the office's to change.
The reason and the note never enter a notification.

### 5. Incidents reported from the app

A driver's report is an ordinary `Incident` in the office's log, with the driver as the member
of staff involved and as its reporter. `incidents.reported_by_staff_id` (nullable, additive)
records the reporter. A named trip must be the driver's own; it supplies the bus and the
route. The reporter sees their own title and description and the status. The office's
resolution, notes and the other people named stay Org Admin only (ADR-0056 §5).

### 6. Notifications

- **Approaching stop** now goes only to the parents whose child uses that stop on that trip:
  the pickup stop on a morning trip, the dropoff stop on an afternoon trip, and only on the
  trip's route. Trip started, trip ended and arrived still go to every family on the bus.
- **Trip cancelled** also goes to the trip's driver.
- **Cover created** goes to the substitute, if they have a login (only drivers do).
- **Self-reported unavailability** goes to every active Org Admin.

The app tells transport messages from the office's own by `type` and `data.kind`; no new
notification category is stored.

### 7. Geofence stop sequencing (amends ADR-0014)

The evaluator still targets one stop at a time, in route order. Two changes:

- A stop with no radius is passed over instead of holding the evaluator on itself.
- When the bus is away from the target stop and within reach of a later stop, that later stop
  becomes the target. A skipped stop is never returned to.

### 8. Push delivery

No Firebase project or credential exists, so no sender is built. Notifications are stored and
delivered over `/ws/notifications`; the app keeps its push code behind one interface so a
Firebase implementation can be added without touching a screen.

## Consequences

- A driver's phone can run a working day without any organization-wide read.
- `transport_ops.trips.list` and `.read` remain granted to `driver` for now. Removing them is
  safe once the app no longer calls `GET /trips`, and needs a migration.
- A parent whose child changed bus this month sees history only from the change.
- A bus that doubles back to a skipped stop will not announce it. That is the accepted cost of
  never letting one stop silence the rest of the route.
- Background push needs a Firebase project before it can exist.
