# ADR-0059: Compliance in Daily Operations

## Status

**Accepted** (2026-10-01). Phase 4, with ADR-0058. Extends ADR-0053 §3 (the coverage rule).

## Context

ADR-0058 defines when a staff member is compliant. Today no operation looks at a document:

| Operation | What it checks |
|---|---|
| Daily board, generation preview, uncovered-trip alerts (one rule, ADR-0053 §3) | driver active, staff active, not unavailable |
| Naming a substitute | substitute active, has driver access, not unavailable |
| Assigning crew to a bus | staff active |
| Setting a timetable entry's default driver | driver exists |
| Scheduling a trip by hand | driver exists |
| Starting a trip | trip is scheduled; the bus has no other active trip |

The safety trade-off cuts both ways. A driver whose licence has lapsed should not be planned onto
a bus. But refusing to start the 06:45 trip, because a licence lapsed overnight, leaves children
at their stops with no bus.

## Decision

### 1. One more reason in the one coverage rule

`_Coverage.driver_problem` gains a fourth reason, checked after the existing three:
`driver_not_compliant`, when the trip's driver is `not_compliant` on the trip's date (ADR-0058
§2). It applies whatever the type's enforcement is.

Because the board, the generation plan and the uncovered-trip alerts all ask this rule, all three
gain it together:

- **Daily board:** the trip shows as uncovered, with the reason.
- **Trip generation:** unchanged in what it creates. The trip is generated with its driver, as it
  already is for an unavailable driver with no cover, and it is flagged. A licence that expires on
  Wednesday flags Thursday's trip when the week is generated on Monday.
- **Uncovered-trip alerts:** the existing job (ADR-0053 §5) tells the Org Admins, once per trip
  and reason.

A substitute is checked the same way: a cover puts the substitute on the trip, and the rule then
looks at the substitute.

### 2. Non-driver crew never make a trip uncovered

A crew member who is not compliant shows a badge on the board. The trip's coverage and the bus's
crew-gap count are unchanged.

### 3. Planning warns, and a `block` type refuses

Four planning actions check the person on the dates involved:

| Action | Dates checked | `warn` type not met | `block` type not met |
|---|---|---|---|
| Naming a substitute | every day of the cover | warning | refused |
| Setting or changing a timetable entry's default driver | today, or the entry's start if later | warning | refused |
| Scheduling a trip by hand | the trip's date | warning | refused |
| Assigning crew to a bus | the assignment's start date | warning | warning |

- A warning is returned with the saved result (`warnings`, as covers already do) and shown to the
  Org Admin. The action succeeds.
- A refusal is `409 RULE_VIOLATION`, naming the document type and whether it is missing or
  expired. Nothing is saved.
- Saving a timetable entry without changing its driver is never refused.
- Assigning crew is never refused: only a driver makes a trip uncovered (§2).

### 4. What is never blocked or changed

- **Starting, ending or cancelling a trip.** A scheduled trip whose driver is not compliant can
  still be started. It is flagged on the board and the Org Admins have been alerted (§1).
- **A trip in progress.** Nothing is done to it.
- **Trips that already exist.** RAAD never reassigns or cancels automatically (ADR-0053 §1). The
  Org Admin names a substitute or cancels.
- **Trip generation.** It never skips a trip because of a document.

So the driver app receives no new refusal and needs no change.

### 5. Surfaces

- The board trip reason and the generation preview gain `driver_not_compliant`.
- Each crew member on the board carries a compliance status.
- The four planning forms show the warning or the refusal.

No new permission and no new scheduled job.

## Consequences

- An organization that marks nothing as required sees no change at all.
- An organization that marks "Driving licence" required for drivers, before recording licences,
  sees every trip flagged at once. ADR-0058 §3's impact figure is shown before that is saved.
- `block` stops a non-compliant driver from being newly planned. It does not stop them driving a
  trip already planned. That is deliberate (Context); the board and the alerts are what catch it.
- An expiry date typed wrongly flags or refuses a driver until it is corrected. Compliance is
  recomputed on every read, so the correction takes effect at once.
- Not built: blocking trip start, automatic substitute suggestions, compliance for vehicles,
  staff self-service (Phase 5), compliance reports (Phase 6).
