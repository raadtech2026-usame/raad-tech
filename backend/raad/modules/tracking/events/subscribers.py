"""Tracking event subscribers — closes the consumer half of roadmap track B2 (`docs/architecture/
frontend-flutter-master-roadmap.md` §4A). Consumes `DevicePositionReported` (published by the
device-plane service, `services/device-gateway/src/vendors/lsz/` per ADR-0009/ADR-0010 — this
docstring previously referenced the pre-rename `services/jt808/src/vendors/lsz_mdvr/` path,
corrected below) and persists it via `TrackingApplicationService.record_vehicle_position`/
`record_backfill_position` — the exact "Business API-side tracking consumer"
`services/device-gateway/src/vendors/lsz/handlers/position_handler.py`'s own module docstring
already names as a later phase's job, and `docs/vendor/HARDWARE_INTEGRATION_PLAN.md` §12's
"Required refactoring" step 3.

**Wire envelope this subscriber expects:** a `core.events.base.DomainEvent` with
`event_type="DevicePositionReported"`, `aggregate_type="Vehicle"`, `aggregate_id=vehicle_id`,
`org_id=organization_id`, and a `payload` carrying every field of `services/device-gateway/src/
events/device_position_reported.DevicePositionReported` by the same names (`vehicle_id`,
`device_id`, `terminal_id`, `trip_id`, `latitude`, `longitude`, `speed_kph`, `heading_deg`,
`alarm_flags`, `event_time` as an ISO-8601 string, `is_backfill`) — deliberately the same field set
`RecordVehiclePositionCommand`/`RecordBackfillPositionCommand` already expect, so this processor
does no renaming or unit conversion of its own, mirroring the device-plane event's own module
docstring ("a future Business API-side consumer can build one of those commands from this event
with no field renaming or unit conversion of its own").

**Now live-verified, end-to-end, against a real Redis and a real Postgres (ADR-0012 follow-up
verification pass).** This paragraph previously said the producer-side Redis dependency was
"proposed, not yet approved" and that the whole path was "not yet wired to a real broker
consumer" — both stale as of this correction: `services/device-gateway/pyproject.toml` marks
`redis>=5.0` **APPROVED** (user-confirmed), `RedisEventPublisher` is wired into
`vendors/lsz/server.py`, and `core/di/bootstrap.py` binds this module's `DevicePositionReportedProcessor`
onto the same `notification-worker` consumer group `NotificationWorker` already ticks (a single
shared `EventProcessorRegistry`, not a dedicated tracking worker). A real LSZ registration+position
frame, sent over a real TCP socket through a real `MdvrServer` → `RedisEventPublisher` → `raad:
events` Stream → this exact processor → a real `TrackingApplicationService` → a real, committed
`vehicle_positions` row was proven in this pass (`services/device-gateway/scripts/
verify_redis_e2e.py`, plus a direct processor invocation against a live Postgres instance).
**A real bug was found and fixed during this same pass**, not just a missing-infrastructure
gap: `position_handler.py` was passing the vendor's raw, out-of-spec `heading_deg`/`alarm_flags`
values straight through to `RecordVehiclePositionCommand` without range-checking them first, so
`tracking.domain.value_objects.HeadingDegrees`/`AlarmFlags` correctly rejected them with a
`DomainError` — silently failing *every* real position event from this vendor forever (both of
the vendor's own documented worked examples fall outside the valid ranges, so this was not a rare
edge case). Fixed at the source (`position_handler.py`'s own range-clamp, see its module
docstring) — this file needed no change, since the bug was in what the producer sent, not in how
this processor consumes it.

**Still not proven "live at rest"**, distinct from the above: the standing worker process
(`python -m raad.interfaces.workers.bootstrap`, the same consumer group) has a large pre-existing
`outbox` backlog from prior, unrelated integration-test runs (700+ historical domain events,
newly draining now that a broker is reachable for the first time) — a running worker will reach
and correctly process new live position events once it works through that backlog, but this was
proven directly (a single processor invocation against the newest published event, not by
observing the standing worker specifically clear that backlog and reach it live). Also still
genuinely unbuilt: `vehicle:{id}:last`'s direct Redis cache write (B2's own scope,
`GET /tracking/vehicles/{id}/latest`'s instant-read source) — no code in `services/device-gateway`
writes this key yet; grepped for and confirmed absent in this same pass. This processor is not
gated on anything in this codebase changing further.

**Idempotency:** `record_vehicle_position`/`record_backfill_position` each insert a new
`VehiclePosition` row with a freshly generated id — replaying the same `DevicePositionReported`
event (at-least-once delivery, Backend LLD §10.3) produces a harmless duplicate history row, not
a domain-rule violation or a crash. No de-duplication key exists for this event type in the
current schema; accepted as-is, matching `vehicle_positions`' own append-only, high-frequency,
retention-pruned design (`.claude/rules/database.md` #6) — a duplicate row ages out with the rest.

**Active-trip resolution (`docs/architecture/post-f7-production-readiness-roadmap.md` Phase A
item A4).** Every device-plane vendor adapter today publishes `DevicePositionReported` with
`trip_id=None` — confirmed for LSZ (`services/device-gateway/src/vendors/lsz/handlers/
position_handler.py`'s own docstring: "no active-trip Redis read-model exists in this
deployable... the Business API's consumer resolves/repairs it", `device_position_reported.py`).
**This processor is that consumer.** For a live (non-backfill) position, `trip_id` is resolved
fresh, on every event, via `transport_ops`'s own `TripApplicationService.
get_active_trip_for_vehicle` — a cross-module *application-service* call (`.claude/rules/
backend.md` #3: never a direct repository/DB read into another module's tables) — and that
resolved value is used **unconditionally**, not merely as a fallback when the payload's own
`trip_id` is absent: the device plane has no visibility into `transport_ops`'s trip state at all
(by architecture, `.claude/rules/architecture.md` #2/#3), so a backend-resolved value is always
more authoritative than anything a vendor adapter could have attached. This closes a real,
previously-silent gap the audit itself did not spell out to its actual consequence: without it,
`GET /tracking/trips/{id}/positions` returns an empty page for every trip a real device ever
drives, forever, since no real position was ever persisted with a non-null `trip_id`.

**Backfilled positions are deliberately exempted from this resolution** — `payload.get("trip_id")`
is used as-is (today, always `None`, since no vendor adapter publishes backfill events yet).
Resolving "the vehicle's *currently* active trip" for a late-arriving, past-dated position would
misattribute it: the currently active trip (if any) is very likely not the trip that was active
at the buffered position's own `event_time`. No historical trip-lookup capability exists to do
this correctly for backfill, so it is left unresolved rather than resolved wrong — the same
"backfilled points are excluded" carve-out Phase 2 §22.2 already establishes for geofence
evaluation, applied here to trip attribution instead.

**Live geofence evaluation (post-F7 roadmap item A5; ADR-0014).** For a live position with a
resolved trip, this processor also evaluates Phase 2 §22's stop/organization geofences and
records any crossings via `TrackingApplicationService.record_geofence_crossing` — the wiring
that finally invokes `GeofenceEvaluationService`'s previously-built-but-never-called primitives
and the two notification triggers (`VehicleApproachingStopNotifier`/
`VehicleArrivedAtOrganizationNotifier`) that have been dormant since they were built. Evaluation
never runs for a backfilled position (Phase 2 §22.2: "backfilled points are excluded to prevent
false historical triggers") or when no active trip was resolved (the evaluator is explicitly
trip-scoped).

Two real config gaps were found while scoping this (see ADR-0014 for the full record). The
"approaching" radius gap is now closed for real (ADR-0014 amendment): `organizations.
approaching_distance_m` (an organization-level, non-nullable, user-configurable meters value,
default 300m) is used directly as the absolute "approaching" radius for every stop on that
organization's routes — replacing the originally-temporary `_APPROACH_RADIUS_MULTIPLIER` stand-in
(`stop.geofence_radius_m * 3`) this module previously used. The approach radius is therefore now
fully decoupled from a stop's own arrival radius (`stop.geofence_radius_m`), which continues to
govern `ENTERED_STOP`/`EXITED` only. Designed for a future per-stop override: a later phase could
add a nullable `stops.approaching_distance_m` that takes precedence over the organization default
when set, with the resolution point isolated to `_evaluate_stop_geofence` below. `organizations`
originally had no geographic location at all either (closed by adding `latitude`/`longitude`/
`geofence_radius_m` columns, ADR-0014, unrelated to `approaching_distance_m` — that trio governs
the organization's own "arrived at organization" evaluation, not stop-approach). A stop with no
`geofence_radius_m` configured gets no evaluation performed against it at all, ever — never a
hardcoded fallback distance; an organization's own arrival geofence follows the identical rule for
its own three (still-nullable) fields.

**Hysteresis + sequence + cooldown state lives in Redis** (`GeofenceStatePort`,
`application/ports.py`), one `GeofenceHysteresisState` per trip: which single stop is currently
being approached/entered (Phase 2 §22.3: "'approaching' fires for the *next* assigned stop in
route order, not stops already passed" — evaluated one stop at a time, never the whole
remaining list), the previous-position inside/outside reading for that stop's approach/arrival
radii and the organization's own radius (feeding `GeofenceEvaluationService.detect_transition`'s
flip-detection, which already prevents re-firing while continuously inside a radius), and a
per-(event-type, stop-or-org) `last_fired_at` timestamp. `_EVENT_COOLDOWN_SECONDS` (a flagged
120s default, ADR-0014) additionally suppresses re-firing the same event within that window —
approximating §22.3's "minimum dwell"/"cooldown" intent without implementing literal
N-consecutive-reading debounce, which no document specifies the parameters of. Advancing past a
stop (its arrival-radius `EXITED` transition) happens regardless of whether that specific
`EXITED` event was itself cooldown-suppressed — the vehicle has genuinely left the radius either
way, so the evaluator must move on to the next stop.

**Best-effort, isolated from the position write that already succeeded above:** geofence
evaluation is wrapped so a failure here (a missing route, an unbound `GeofenceStatePort` when no
Redis is configured, anything else) is logged and swallowed, never propagated — the same "one
failure is logged, never left to crash the surrounding loop" principle
`interfaces/http/realtime.handle_subscribe` already established (WebSocket phase). The
already-committed `VehiclePosition` row is unaffected either way.
"""

from __future__ import annotations

import logging
from datetime import datetime

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.core.events.processor import EventProcessor, EventProcessorRegistry
from raad.core.time.clock import Clock
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.application.queries import (
    GetOrganizationByIdQuery,
    OrganizationDTO,
)
from raad.modules.organization.application.services import OrganizationApplicationService
from raad.modules.tracking.application.commands import (
    RecordBackfillPositionCommand,
    RecordGeofenceCrossingCommand,
    RecordVehiclePositionCommand,
)
from raad.modules.tracking.application.ports import (
    GeofenceHysteresisState,
    GeofenceStatePort,
    TrackingUnitOfWork,
)
from raad.modules.tracking.application.services import TrackingApplicationService
from raad.modules.tracking.domain.services import GeofenceEvaluationService
from raad.modules.tracking.domain.value_objects import (
    GeofenceEventType,
    GeofenceTransition,
    GeoPoint,
    TripId,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    GetActiveTripForVehicleQuery,
    GetRouteByIdQuery,
    RouteDTO,
    StopDTO,
    TripDTO,
)
from raad.modules.transport_ops.application.services import (
    RouteApplicationService,
    TripApplicationService,
)

_logger = logging.getLogger(__name__)

# ADR-0014: Phase 2 §22.3 asks for a "cooldown... duplicate suppression window per (trip, stop,
# event-type)" but specifies no duration - a flagged fixed window.
_EVENT_COOLDOWN_SECONDS = 120


class DevicePositionReportedProcessor(EventProcessor):
    event_type = "DevicePositionReported"

    def __init__(self, container: Container) -> None:
        self._container = container

    async def process(self, event: DomainEvent) -> None:
        payload = event.payload
        organization_id = event.org_id or payload["organization_id"]
        event_time = _parse_iso(payload["event_time"])

        service = self._container.resolve(TrackingApplicationService)
        uow = self._container.resolve(TrackingUnitOfWork)

        if payload.get("is_backfill", False):
            await service.record_backfill_position(
                RecordBackfillPositionCommand(
                    organization_id=organization_id,
                    vehicle_id=payload["vehicle_id"],
                    device_id=payload["device_id"],
                    latitude=payload["latitude"],
                    longitude=payload["longitude"],
                    event_time=event_time,
                    trip_id=payload.get("trip_id"),
                    speed_kph=payload.get("speed_kph"),
                    heading_deg=payload.get("heading_deg"),
                    alarm_flags=payload.get("alarm_flags"),
                ),
                uow=uow,
            )
        else:
            trip = await self._resolve_active_trip(payload["vehicle_id"])
            await service.record_vehicle_position(
                RecordVehiclePositionCommand(
                    organization_id=organization_id,
                    vehicle_id=payload["vehicle_id"],
                    device_id=payload["device_id"],
                    latitude=payload["latitude"],
                    longitude=payload["longitude"],
                    event_time=event_time,
                    trip_id=trip.id if trip is not None else None,
                    speed_kph=payload.get("speed_kph"),
                    heading_deg=payload.get("heading_deg"),
                    alarm_flags=payload.get("alarm_flags"),
                ),
                uow=uow,
            )
            if trip is not None:
                await self._evaluate_geofence(
                    organization_id=organization_id,
                    trip=trip,
                    latitude=payload["latitude"],
                    longitude=payload["longitude"],
                )

    async def _resolve_active_trip(self, vehicle_id: str) -> TripDTO | None:
        trip_service = self._container.resolve(TripApplicationService)
        transport_ops_uow = self._container.resolve(TransportOpsUnitOfWork)
        return await trip_service.get_active_trip_for_vehicle(
            GetActiveTripForVehicleQuery(vehicle_id=vehicle_id), uow=transport_ops_uow
        )

    async def _evaluate_geofence(
        self, *, organization_id: str, trip: TripDTO, latitude: float, longitude: float
    ) -> None:
        """See module docstring — best-effort, never raises. No-ops entirely when
        `GeofenceStatePort` is unbound (no `RAAD_REDIS__URL` configured), the same posture
        `TrackingApplicationService.get_current_vehicle_position` already establishes for its
        own optional Redis dependency."""
        try:
            geofence_state_port = self._container.resolve(GeofenceStatePort)
        except LookupError:
            return

        try:
            await self._do_evaluate_geofence(
                organization_id=organization_id,
                trip=trip,
                position=GeoPoint(latitude=latitude, longitude=longitude),
                geofence_state_port=geofence_state_port,
            )
        except Exception:
            _logger.exception(
                "Geofence evaluation failed for trip %s - the position was already recorded; "
                "no crossing events were emitted for this position.",
                trip.id,
            )

    async def _do_evaluate_geofence(
        self,
        *,
        organization_id: str,
        trip: TripDTO,
        position: GeoPoint,
        geofence_state_port: GeofenceStatePort,
    ) -> None:
        clock = self._container.resolve(Clock)
        now = clock.now()
        trip_id = TripId(trip.id)
        state = await geofence_state_port.get_state(trip_id) or GeofenceHysteresisState()

        route_service = self._container.resolve(RouteApplicationService)
        transport_ops_uow = self._container.resolve(TransportOpsUnitOfWork)
        route = await route_service.get_route_by_id(
            GetRouteByIdQuery(route_id=trip.route_id), uow=transport_ops_uow
        )

        org_service = self._container.resolve(OrganizationApplicationService)
        organization_uow = self._container.resolve(OrganizationUnitOfWork)
        organization = await org_service.get_organization_by_id(
            GetOrganizationByIdQuery(organization_id=organization_id), uow=organization_uow
        )

        crossings = _evaluate_stop_geofence(
            state=state, route=route, organization=organization, position=position, now=now
        )
        crossings.extend(
            _evaluate_org_geofence(
                state=state, organization=organization, position=position, now=now
            )
        )

        if crossings:
            tracking_service = self._container.resolve(TrackingApplicationService)
            tracking_uow = self._container.resolve(TrackingUnitOfWork)
            for crossing_event_type, stop_id in crossings:
                await tracking_service.record_geofence_crossing(
                    RecordGeofenceCrossingCommand(
                        organization_id=organization_id,
                        trip_id=trip.id,
                        event_type=crossing_event_type,
                        stop_id=stop_id,
                    ),
                    uow=tracking_uow,
                )

        await geofence_state_port.save_state(trip_id, state)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _cooldown_key(event_type: GeofenceEventType, stop_id: str | None) -> str:
    """Namespaced per (event-type, stop-or-org) — without this, `EXITED` firing for stop N's
    cooldown would incorrectly suppress `EXITED` firing for stop N+1 (or the organization
    geofence) within the same window, since both share the same `GeofenceEventType`."""
    return f"{event_type.value}:{stop_id or 'org'}"


def _cooldown_elapsed(
    last_fired_at: dict[str, str],
    event_type: GeofenceEventType,
    stop_id: str | None,
    *,
    now: datetime,
) -> bool:
    raw = last_fired_at.get(_cooldown_key(event_type, stop_id))
    if raw is None:
        return True
    return (now - datetime.fromisoformat(raw)).total_seconds() >= _EVENT_COOLDOWN_SECONDS


def _mark_fired(
    last_fired_at: dict[str, str],
    event_type: GeofenceEventType,
    stop_id: str | None,
    *,
    now: datetime,
) -> None:
    last_fired_at[_cooldown_key(event_type, stop_id)] = now.isoformat()


def _next_stop_after(ordered_stops: list[StopDTO], current: StopDTO) -> StopDTO | None:
    for stop in ordered_stops:
        if stop.sequence_no > current.sequence_no:
            return stop
    return None


def _evaluate_stop_geofence(
    *,
    state: GeofenceHysteresisState,
    route: RouteDTO,
    organization: OrganizationDTO,
    position: GeoPoint,
    now: datetime,
) -> list[tuple[GeofenceEventType, str | None]]:
    """Mutates `state` in place (target/flags/cooldown timestamps); returns the crossings to
    record. See module docstring for the one-stop-at-a-time sequence-awareness design."""
    crossings: list[tuple[GeofenceEventType, str | None]] = []
    if state.stops_exhausted:
        return crossings

    ordered_stops = sorted(route.stops, key=lambda stop: stop.sequence_no)
    if not ordered_stops:
        state.stops_exhausted = True
        return crossings

    if state.stop_target_id is None:
        target = ordered_stops[0]
    else:
        target = next(
            (stop for stop in ordered_stops if stop.id == state.stop_target_id), None
        )
        if target is None:
            # The previously-targeted stop no longer exists on this route (edited/removed
            # mid-trip) - fall back to the first stop rather than getting permanently stuck.
            target = ordered_stops[0]

    if target.geofence_radius_m is None:
        # ADR-0014: a stop with no configured radius is invisible to the evaluator entirely -
        # never advanced past, never given a hardcoded fallback radius.
        state.stop_target_id = target.id
        return crossings

    center = GeoPoint(latitude=target.latitude, longitude=target.longitude)
    # ADR-0014 amendment: an absolute, organization-configurable distance - no longer derived
    # from the stop's own arrival radius. See module docstring for the future per-stop-override
    # design this is left open for.
    approach_radius_m = organization.approaching_distance_m

    is_inside_approach = GeofenceEvaluationService.is_within_radius(
        position=position, center=center, radius_m=approach_radius_m
    )
    approach_transition = GeofenceEvaluationService.detect_transition(
        was_inside=state.stop_is_inside_approach, is_inside=is_inside_approach
    )
    state.stop_is_inside_approach = is_inside_approach
    if approach_transition == GeofenceTransition.ENTERED and _cooldown_elapsed(
        state.last_fired_at, GeofenceEventType.APPROACHING_STOP, target.id, now=now
    ):
        crossings.append((GeofenceEventType.APPROACHING_STOP, target.id))
        _mark_fired(state.last_fired_at, GeofenceEventType.APPROACHING_STOP, target.id, now=now)

    is_inside_arrival = GeofenceEvaluationService.is_within_radius(
        position=position, center=center, radius_m=target.geofence_radius_m
    )
    arrival_transition = GeofenceEvaluationService.detect_transition(
        was_inside=state.stop_is_inside_arrival, is_inside=is_inside_arrival
    )
    state.stop_is_inside_arrival = is_inside_arrival
    if arrival_transition == GeofenceTransition.ENTERED:
        if _cooldown_elapsed(
            state.last_fired_at, GeofenceEventType.ENTERED_STOP, target.id, now=now
        ):
            crossings.append((GeofenceEventType.ENTERED_STOP, target.id))
            _mark_fired(
                state.last_fired_at, GeofenceEventType.ENTERED_STOP, target.id, now=now
            )
        state.stop_target_id = target.id
    elif arrival_transition == GeofenceTransition.EXITED:
        if _cooldown_elapsed(state.last_fired_at, GeofenceEventType.EXITED, target.id, now=now):
            crossings.append((GeofenceEventType.EXITED, target.id))
            _mark_fired(state.last_fired_at, GeofenceEventType.EXITED, target.id, now=now)
        # Sequence advancement happens regardless of the EXITED event's own cooldown outcome
        # above - the vehicle has genuinely left this stop's radius either way, so evaluation
        # must move on to the next stop (module docstring).
        next_stop = _next_stop_after(ordered_stops, target)
        state.stop_target_id = next_stop.id if next_stop is not None else None
        state.stops_exhausted = next_stop is None
        state.stop_is_inside_arrival = False
        state.stop_is_inside_approach = False
    else:
        state.stop_target_id = target.id

    return crossings


def _evaluate_org_geofence(
    *,
    state: GeofenceHysteresisState,
    organization: OrganizationDTO,
    position: GeoPoint,
    now: datetime,
) -> list[tuple[GeofenceEventType, str | None]]:
    crossings: list[tuple[GeofenceEventType, str | None]] = []
    if (
        organization.latitude is None
        or organization.longitude is None
        or organization.geofence_radius_m is None
    ):
        # ADR-0014: an organization that hasn't configured its geofence yet gets no
        # organization-geofence evaluation performed for it, ever - never a zero-island
        # fallback.
        return crossings

    center = GeoPoint(latitude=organization.latitude, longitude=organization.longitude)
    is_inside = GeofenceEvaluationService.is_within_radius(
        position=position, center=center, radius_m=organization.geofence_radius_m
    )
    transition = GeofenceEvaluationService.detect_transition(
        was_inside=state.org_is_inside, is_inside=is_inside
    )
    state.org_is_inside = is_inside
    if transition == GeofenceTransition.ENTERED and _cooldown_elapsed(
        state.last_fired_at, GeofenceEventType.ARRIVED_ORG, None, now=now
    ):
        crossings.append((GeofenceEventType.ARRIVED_ORG, None))
        _mark_fired(state.last_fired_at, GeofenceEventType.ARRIVED_ORG, None, now=now)
    elif transition == GeofenceTransition.EXITED and _cooldown_elapsed(
        state.last_fired_at, GeofenceEventType.EXITED, None, now=now
    ):
        crossings.append((GeofenceEventType.EXITED, None))
        _mark_fired(state.last_fired_at, GeofenceEventType.EXITED, None, now=now)

    return crossings


def register_tracking_processors(
    registry: EventProcessorRegistry, container: Container
) -> None:
    """Called from `core/di/bootstrap.py` when wiring a broker consumer — mirrors `notifications
    .events.subscribers.register_notification_processors`'s identical shape exactly."""
    registry.register(DevicePositionReportedProcessor(container))
