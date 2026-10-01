# ADR-0060: Parent transport read model (`GET /me/transport`)

- **Status:** Accepted
- **Date:** 2026-10-01
- **Extends:** ADR-0023 (canonical `/me` identity resolution)

## Context

A Parent can list their children (`GET /me/students`) but cannot learn which bus, route or stop
a child uses. The `parent` role holds no `transport_ops.student_assignments.*`, `.routes.*`,
`.trips.*` or `fleet_device.vehicles.*` permission, and must not: each of those is an
organization-wide read. Without a `vehicle_id` the Parent mobile app cannot call
`GET /tracking/vehicles/{id}/latest` or subscribe on `/ws/tracking`, so live tracking is
unreachable even though the server would authorize it.

## Decision

Add `GET /api/v1/me/transport`, owned by `iam` (`MeApplicationService`), composing the
application services of `transport_ops` and `fleet_device` only.

1. **Self-scoped, like every `/me` route.** `Depends(get_current_user)` only: no permission, no
   migration. The route accepts no parameter naming a parent, student, vehicle or route;
   everything derives from `principal.user_id`. A caller with no linked `Parent` gets 404, the
   same as `GET /me/students`.
2. **One item per linked child**, in the order `GET /me/students` returns them:
   `student_id`, `full_name`, `status`, `assignment`, `current_trip`.
3. **`assignment`** is the child's active `StudentAssignment`, or `null`. It carries the route
   (`id`, `name`), the bus (`id`, `plate_no`, `label`) and **only the child's own pickup and
   dropoff stop** (`id`, `name`, `latitude`, `longitude`).
4. **Other families' stops never appear.** The route's stop list, stop sequence and
   `geofence_radius_m` are not part of the response.
5. **`current_trip`** is the in-progress trip on the child's assigned bus, and only when that
   trip runs the child's assigned route. `scheduled`, `interrupted`, `completed` and `cancelled`
   trips are not reported. It carries `id`, `trip_type`, `status`, `scheduled_date`,
   `started_at`.
6. **A reference that no longer resolves is `null`, not an error.** Cross-module ids are not
   foreign keys (`.claude/rules/database.md` #3), so a missing route, stop or vehicle yields a
   `null` field and the rest of the item is still returned.
7. **No driver data.** A driver's name and phone are personal data and need their own decision.

## Consequences

- The Parent app can go from login to a tracked bus with two calls and no client-supplied id.
- A parent sees the bus's plate number, which is painted on the bus.
- The read costs a few queries per child. Families are small; no caching is added.
- `current_trip` is `null` while a trip is interrupted, matching the tracking time-window rule
  (`interfaces/http/policy_guards.resolve_vehicle_tracking_context`).
- Nothing here grants tracking access: `TrackingVisibilityPolicy` still decides every tracking
  request independently.
