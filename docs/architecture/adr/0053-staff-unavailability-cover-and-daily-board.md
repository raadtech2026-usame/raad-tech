# ADR-0053: Staff Unavailability, Cover and the Daily Operations Board

## Status

**Accepted** (2026-09-30), Phase 2, with ADR-0052 and ADR-0054.

## Context

Phase 1 (ADR-0049/0050) records who works on which bus. It cannot record that someone is
unavailable, so RAAD cannot tell that a trip has no driver who can drive it. Admins need one view
answering "today, is every bus covered?" and a way to put a substitute in place.

**This is not leave management.** There are no requests, approvals, balances, entitlements or
accruals, and no attendance or timesheets. An unavailability is an operational fact entered by
the Org Admin: "Amina cannot work 3–5 October".

## Decision

### 1. `staff_unavailability`

`staff_id`, `starts_on`, `ends_on` (both inclusive, required), `reason`
(`sick`/`personal`/`training`/`other`) and an optional `note`. It can be withdrawn
(`withdrawn_at`), never deleted.
- Recorded by the Org Admin only. Staff self-service is Phase 5.
- The **note is Org Admin only**, nulled for other readers like the Phase 1 private fields. The
  reason category is visible to every reader. Events carry ids, dates and the category, never
  the note.
- Recording it changes **nothing else**. Trips and crew stay as they are and are flagged
  (§3). RAAD never reassigns automatically.

### 2. Cover: `staff_covers`

A cover names the substitute for one unavailability on one bus for a period inside it:
`unavailability_id`, `substitute_staff_id`, `vehicle_id`, `starts_on`, `ends_on`.
- Creating a cover creates a **temporary crew assignment** for the substitute (ADR-0050,
  reason "Covering for <name>"). It is the same history row, not a parallel one.
- **If the unavailable person is a driver**, the substitute must be an active staff member with
  active driver access (hard rule, 400). The cover then switches the driver on that person's
  **scheduled** trips on that bus within the period, through `Trip.change_driver`. Trips already
  started or finished are never touched.
- A different job title only produces a warning.
- **Per-trip override:** the existing `PATCH /trips/{id}/driver` stays available for one trip.
- Withdrawing a cover ends the substitute's temporary assignment. It restores the original driver
  on still-scheduled trips that still have the substitute, provided the original driver is
  available that day.
- Withdrawing an unavailability withdraws its covers the same way.

### 3. Coverage: one rule, computed on read

A non-cancelled, not-yet-completed trip is **uncovered** when its driver:
- is inactive, or their staff record is not active; or
- is unavailable on the trip's date.

(A substitute already on the trip is its driver, so a covered trip is not uncovered.) Crew
members other than the driver who are unavailable without a cover are shown as **crew gaps**,
a warning that does not make the trip uncovered. One function computes both, and the board and
the alert job share it.

### 4. Daily operations board

`GET /daily-operations?date=YYYY-MM-DD` returns, per bus:
- that day's trips (period, route, planned departure, driver, status, coverage);
- the crew on the bus that day;
- who is unavailable and who covers;
- the day's closure label, if any.

Buses with no trips but with crew are included. Pages: `/org/operations` (manage) and
`/platform/operations` (read-only).

### 5. Uncovered-trip alerts

The worker job `notify_uncovered_trips` runs hourly, looking at trips from today to tomorrow:
- **As detected:** one in-app `system` notification to every active Org Admin per trip and per
  cause. The last alerted cause is stored on the trip (`coverage_alert_key`), so a changed cause
  alerts again and the same cause never repeats.
- **Morning summary:** the run in the configured hour
  (`RAAD_WORKERS__UNCOVERED_SUMMARY_HOUR_UTC`, default 4, 07:00 in UTC+3) sends each
  organization with uncovered trips one summary. Its only guard is the job's one-run-per-hour
  lock: a worker restart inside that hour could send a second summary. That is disclosed, not
  hidden.

On by default, off with `RAAD_WORKERS__UNCOVERED_TRIP_ALERTS=false`.

### 6. Permissions

`transport_ops.unavailability.{list,manage}`, `transport_ops.covers.manage`,
`transport_ops.daily_operations.read`. Manage goes to `org_admin`; list and read go to founder,
regional_manager and support_staff. Nothing goes to finance_staff, driver or parent.

## Consequences

- Admins see gaps before a bus leaves, and a substitute is one action that updates crew and
  trips together.
- The driver app sees a substitute's trips because they now carry the substitute's `driver_id`.
  The mobile app has never been compiled or run here, so that path is unverified until it is.
- Not built: availability calendars, recurring unavailability, staff requesting time off,
  automatic substitute suggestions.
