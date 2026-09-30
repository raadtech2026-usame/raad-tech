# ADR-0054: Trip Cancellation (amends Database Design §6.8 and Phase-2 §6.2)

## Status

**Accepted** (2026-09-30), Phase 2, with ADR-0052 and ADR-0053.

## Context

The documented trip state machine is `scheduled → in_progress → (interrupted ↔ in_progress) →
completed`. There is no way to say a trip will not run: a broken-down bus, a closure added after
trips were generated, a school event. Admins today can only leave a trip `scheduled` forever,
which looks like a trip that should be running.

## Decision

### 1. A `cancelled` status

- Allowed **only from `scheduled`**. A trip that has started ends or is interrupted as today.
- A reason is required (1–255 characters). `cancelled_at`, `cancelled_reason` and the actor are
  kept; the `TripCancelled` event carries the reason.
- Final: a cancelled trip is never un-cancelled. The admin creates a new trip, which the partial
  unique index of ADR-0052 allows.
- Generation never recreates a cancelled trip (ADR-0052 §4).
- A cancelled trip is never "active", so live tracking for parents (CR-1) and the driver's start
  action are unavailable, with no change to either policy.

`trip_status` gains `cancelled` (`ALTER TYPE … ADD VALUE`). The downgrade refuses while any
cancelled trip exists, rather than rewriting history.

### 2. Parents are told

Cancellation is transport information about the child's bus, not staff information, so parents
are notified (the Phase 1 rule, "parents see nothing about staff", is unaffected).
- **Recipients:** parents linked (`student_parents`) to students whose **active**
  `StudentAssignment` is on the trip's route **and** bus.
- **Content:** "Morning bus <plate> on <date> is cancelled: <reason>". The reason is the admin's
  text, so the form tells them parents will read it.
- **Delivery:** in-app `system` notification with `data.kind = "trip_cancelled"`. No
  `NotificationType` change. Push follows whatever the notification pipeline already does.
- Sent by a subscriber on the `TripCancelled` event, after the cancellation is committed (the
  outbox, ADR-0007), in the interfaces layer, composing `transport_ops` (recipients) and
  `notifications` through their application services.

### 3. Permission

`transport_ops.trips.cancel`, to `org_admin` only.

## Consequences

- Database Design §6.8's status list and Phase-2 §6.2's diagram are amended by this ADR.
- The driver app receives `cancelled` as a status value it has never seen. The mobile client is
  unverified here and must be checked when a Flutter SDK is available (disclosed).
