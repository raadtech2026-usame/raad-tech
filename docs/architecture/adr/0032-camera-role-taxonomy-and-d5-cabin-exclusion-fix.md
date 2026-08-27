# ADR-0032: Camera Role Taxonomy Widening + D5 Cabin-Facing Exclusion Fix

## Status

**Accepted** (user directive, 2026-08-27: bench-test-first, then implement camera roles laying
the groundwork for ADAS-safety and a future-ready DMS position, without inventing hardware
capabilities). Implemented same session.

## Context

The current bench unit has an ADAS-relevant road-facing camera and an internal/cabin camera
connected; **no DMS (Driver Monitoring System / driver-facing) camera is currently connected**.
`CameraPosition` (Database Design §5.3) had exactly three values — `in_cabin`, `road_facing`,
`other` — with no way to record *which direction* a road-facing camera actually points (front,
rear, left, right), and no reserved value for a driver-facing DMS camera that isn't installed
yet. ADR-0030's automatic-discovery workflow already defaults every discovered channel to
`OTHER`/"Channel N" and deliberately does not guess semantics from a vendor's own channel-
numbering convention (ADR-0030 Decision §2) — that stays unchanged; this ADR only widens the set
of values an admin can *correct* a channel to once discovered, and gives future ADAS/DMS-adjacent
work a taxonomy to build on without fabricating alarm-detection logic that no approved document
describes for this hardware (`docs/vendor/HARDWARE_ANALYSIS.md` §"Not documented": ADAS/DSM alarm
capability is explicitly undocumented for the confirmed `LSZ-C5804DG-Q-F` spec; the device-plane
architecture draft marks `AdasEventDetected`-style ingestion **[PROPOSED]**, not approved).

**A real, pre-existing D5 gap found while widening the taxonomy, not introduced by it.**
`CameraPosition`'s own docstring has always claimed `IN_CABIN` "is never exposed to parents,"
attributing that exclusion to the `video` context's `VideoAccessPolicy` — but reading
`interfaces/http/policy_guards.resolve_d5_decision` (the actual D5 enforcement point,
`.claude/rules/jt1078.md` #1) shows it never took a camera/position argument at all. A parent
granted `has_video_live_access`/`has_video_playback_access` (ADR-0026) and owning the right child
could request a stream from *any* camera on the vehicle's device, including the in-cabin one —
the documented exclusion was aspirational, never enforced in code. `.claude/rules/security.md` #5
and `#backend.md` #7 both require this to be closed, not left as a silent gap.

## Decision

### 1. `CameraPosition` widened with five directional/role values, purely additive

`FRONT`, `REAR`, `LEFT`, `RIGHT` (ADAS-relevant directional roles an admin can assign to a
discovered road-facing camera) and `DRIVER_FACING` (the DMS role — reserved for when a DMS camera
is actually connected). The original three values (`in_cabin`, `road_facing`, `other`) are
unchanged and still valid — this is a widening, not a migration of existing data (migration
`a6682ad19581` adds enum values only, remaps nothing on upgrade; every existing `cameras` row on
the bench device keeps its current `other` value unchanged).

**No camera is assigned `driver_facing` by this ADR or by ADR-0030's discovery workflow** — the
bench has no DMS camera connected, and RAAD does not fabricate a camera assignment for hardware
that isn't there. The value exists so that when a DMS camera is later connected and discovered
(as channel N, `position=other`, per ADR-0030's existing default), an admin has a real taxonomy
value to correct it to via `update_camera` (Decision §3) — future-ready, not physically verified.

### 2. `is_cabin_facing` — one property, the single source of truth for D5's exclusion set

`CameraPosition.is_cabin_facing` returns `True` for `IN_CABIN` and `DRIVER_FACING` (the two
positions that show the vehicle's interior/occupants), backed by a module-level
`_CABIN_FACING_POSITIONS` frozenset. A future position value only needs to be added to that one
set, not re-derived at every call site — the same "single source of truth" shape
`Camera.is_active`/`devices.is_online` already establish elsewhere in this module.

### 3. `Device.update_camera` — admin correction of a discovered channel's role/label

A new aggregate method (`camera_id`, optional `position`, optional `label`) lets an Org
Admin/RAAD-staff correct ADR-0030's auto-discovery default after the fact — e.g. reassigning
discovered "Channel 2" from `other` to `front` once its physical mounting is confirmed.
`channel_no` is never editable (it is the wire identity `ux_cameras__device_channel` is keyed
on). Both fields are "leave unchanged when omitted"; a missing `camera_id` raises `DomainError`
(a missing child within an already-loaded aggregate), not `NotFoundError` — the same convention
`transport_ops.Route.remove_stop` already established. Records a new `CameraUpdated` domain
event, mirroring `CameraRegistered`'s exact shape.

**No HTTP route is added this phase** — `UpdateCameraCommand`/`DeviceApplicationService.
update_camera` exist at the application layer only, mirroring `RegisterCameraCommand`'s own
identical "use-case-exists-no-endpoint-yet" posture (`fleet_device/api/routers.py`'s own
documented precedent) until a camera-editing surface is approved.

### 4. D5 cabin-facing exclusion — closes the real gap, absolute for `Role.PARENT` only

`resolve_d5_decision`/`enforce_d5` gain a `camera_position: str | None` parameter. When the
caller is `Role.PARENT` and `camera_position` is given and `CameraPosition(camera_position).
is_cabin_facing`, the decision is denied outright — evaluated *before* the existing
child/device-ownership resolution, so a parent never even reaches that check for a cabin-facing
camera. This exclusion applies **only to `Role.PARENT`** — Org Admin and permitted RAAD staff are
unaffected, matching Database Design §5.3's own "never exposed to *parents*" wording, not a
blanket camera-position restriction.

`POST /video/live`/`/playback` (`video/api/routers.py`) pass the real, resolved `camera.position`
— new visibility being granted. `POST /video/sessions/{id}/stop` passes `camera_position=None`
deliberately: tearing down an already-authorized session grants no new visibility, so re-resolving
a device+camera purely to re-check a fact that cannot change the teardown decision would be
unjustified scope. `None` is a deliberate opt-out, not a default-to-allow — every call site must
pass an explicit value or explicitly opt out, so a future new call site can't silently inherit a
wrong default.

## What this ADR does not do

- **Does not implement ADAS/DSM alarm detection or ingestion.** `docs/vendor/
  HARDWARE_ANALYSIS.md` confirms this is undocumented for the confirmed `LSZ-C5804DG-Q-F` spec;
  `RAAD_DevicePlane_Architecture_v0_1_draft.md`'s own `AdasEventDetected`/Su-biao T/JSATL12
  extended-alarm ingestion remains **[PROPOSED]**, not approved. This ADR only gives a camera a
  directional *role* an admin can assign — it adds no alarm bit parsing, no new JT808 message,
  and no new domain event beyond `CameraUpdated`.
- **Does not assign `driver_facing` to any camera.** No DMS camera is connected on the bench; the
  value is reserved, not physically verified in use.
- **Does not build a camera-editing UI/API.** `update_camera` is application-layer only
  (Decision §3), the same disclosed gap ADR-0030 already carried forward.
- **Does not change `VideoAccessPolicy`'s own evaluate() signature** — the fix lives entirely in
  `policy_guards.resolve_d5_decision`, the module that actually orchestrates D5 today (confirmed
  by reading the code, not assumed from the pre-existing docstring's claim).

## Consequences

- **New PostgreSQL enum values**, additive migration `a6682ad19581` (`ALTER TYPE ... ADD VALUE`)
  — no column, no table, no data backfill. Downgrade rebuilds the type (Postgres has no
  `ALTER TYPE ... DROP VALUE`), remapping any row using a new value back to `other` first, a
  disclosed downgrade data-loss point matching ADR-0030's own discovery-default fallback.
- **A real, previously-silent D5 gap is now closed** — a granted, owning parent can no longer
  reach an `in_cabin`/`driver_facing` camera, regardless of permission grants. This is a security
  fix, not new hardening scope creep: the exclusion was already documented as existing before
  this ADR, just never enforced.
- **`resolve_d5_decision`/`enforce_d5`'s signature widens** — all three `/video/*` routes and
  every existing test call site are updated in the same change (confirmed by search before
  changing the signature, mirroring ADR-0030's own precedent for signature changes).

## Verification

- Backend: `tests/unit/test_fleet_device_domain.py` (`CameraPositionCabinFacingTests`,
  `update_camera` position/label/omitted-field/unknown-camera-id cases), `tests/unit/
  test_fleet_device_application.py` (`update_camera` round-trips through the application
  service), `tests/unit/test_policy_guards.py` (`ResolveAndEnforceD5Tests` — granted parent
  denied for `in_cabin`/`driver_facing`, allowed for `road_facing`, Org Admin unaffected by
  `in_cabin`, `camera_position=None` opt-out for every pre-existing test call site).
- Full backend `tests/unit` + `tests/architecture` suite: 1458 passed, 15 subtests passed.
- Full backend `tests/integration` suite (real PostgreSQL): the enum-widening migration applied
  cleanly; no fleet_device round-trip failure attributable to this ADR.
- **Never tested against the physical MDVR for a real `front`/`rear`/`left`/`right`/
  `driver_facing` assignment** — no camera has been reassigned off `other` on the bench device;
  this ADR adds the taxonomy and the enforcement fix, not a live reassignment.

## References

- `docs/vendor/HARDWARE_ANALYSIS.md` — confirms ADAS/DSM alarm capability is undocumented for
  the confirmed hardware, grounding "taxonomy only, no alarm logic" as this ADR's scope boundary.
- `docs/architecture/RAAD_DevicePlane_Architecture_v0_1_draft.md` §10/§12 — `AdasEventDetected`/
  AI-alarm-dialect ingestion, marked **[PROPOSED]**, out of scope here.
- `docs/architecture/adr/0026-parent-video-access-authorization.md` — the D5 authorization chain
  (`resolve_d5_decision`) this ADR extends with the cabin-facing check.
- `docs/architecture/adr/0030-automatic-camera-channel-discovery.md` — the discovery default
  (`position=other`) this ADR's `update_camera` corrects after the fact.
- `.claude/rules/jt1078.md` #1, `.claude/rules/security.md` #5, `.claude/rules/backend.md` #7 —
  the D5 invariant this ADR closes a real gap in.
- `backend/raad/modules/fleet_device/domain/value_objects.py` (`CameraPosition`,
  `is_cabin_facing`), `domain/entities.py` (`Device.update_camera`), `domain/events.py`
  (`camera_updated`), `application/commands.py`/`services.py` (`UpdateCameraCommand`),
  `interfaces/http/policy_guards.py` (`resolve_d5_decision`/`enforce_d5`), `modules/video/api/
  routers.py`.
- `backend/migrations/versions/20260827_1452_a6682ad19581_fleet_device_camera_role_taxonomy.py`.
