"""Domain services for the `tracking` module (Backend LLD §5.1, which names "geofence
crossing evaluation primitives" verbatim as a domain-service example; Phase 2 §22).

`GeofenceEvaluationService` is the one domain service this phase defines: stateless
computation over already-loaded values — no I/O, no Redis reads, no repository access. Per
Phase 2 §22.2's architecture, the *state* this computation needs (per-trip inside/outside
flags, loaded from Redis) and the *configuration* it needs (stop/org geofence radii, read from
`transport_ops`/`organization` data) are both supplied by the caller; this service never
fetches either itself, which is exactly what keeps it a domain service instead of an
application-layer use-case (the same "no I/O" line `fleet_device.domain.services` draws around
reassignment).

**Debounce/cooldown timing (Phase 2 §22.3: "minimum dwell", "cooldown... per (trip, stop,
event-type)") is deliberately not implemented here.** Both require comparing "now" against a
last-fired-at timestamp read from state (Redis) or the `GeofenceCrossingRepository` — I/O —
so that bookkeeping is an application-layer concern built on top of `detect_transition`, not a
pure primitive. This mirrors `fleet_device.domain.services`'s placement of the reassignment
use-case: the pure step lives here, the orchestration with I/O lives one layer up.
"""

from __future__ import annotations

import math

from raad.modules.tracking.domain.value_objects import GeofenceTransition, GeoPoint

_EARTH_RADIUS_M = 6_371_000.0


class GeofenceEvaluationService:
    """Stateless geofence primitives (see module docstring). Both methods are pure functions
    of their arguments — safe to call from either the domain or application layer without a
    clock, repository, or Redis connection."""

    @staticmethod
    def distance_m(a: GeoPoint, b: GeoPoint) -> float:
        """Great-circle distance between two points in meters (haversine formula, standard
        library `math` only — no new dependency for a well-specified calculation)."""
        lat1, lon1, lat2, lon2 = (
            math.radians(a.latitude),
            math.radians(a.longitude),
            math.radians(b.latitude),
            math.radians(b.longitude),
        )
        delta_lat = lat2 - lat1
        delta_lon = lon2 - lon1
        h = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
        )
        return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, h)))

    @classmethod
    def is_within_radius(
        cls, *, position: GeoPoint, center: GeoPoint, radius_m: float
    ) -> bool:
        """Containment test against a geofence circle. `radius_m` is supplied by the caller
        (`stops.geofence_radius_m` or the org default, Database Design §4.7/§6.6) — this
        service does not own or look up geofence configuration (module docstring / Phase 2
        §22.1). The same primitive serves both the stop's arrival radius and its larger
        "approaching" radius — callers pass whichever radius they are testing."""
        if radius_m < 0:
            raise ValueError("radius_m must not be negative")
        return cls.distance_m(position, center) <= radius_m

    @staticmethod
    def detect_transition(*, was_inside: bool, is_inside: bool) -> GeofenceTransition:
        """Given a previous and current containment reading (both already resolved by the
        caller — the "was inside" flag is per-trip state Phase 2 §22.2 keeps in Redis), decide
        whether a crossing occurred. Hysteresis against boundary jitter (§22.3) is the
        caller's job: this only compares the two booleans it is given."""
        if not was_inside and is_inside:
            return GeofenceTransition.ENTERED
        if was_inside and not is_inside:
            return GeofenceTransition.EXITED
        return GeofenceTransition.NONE
