"""Domain services for the `transport_ops` module (Backend LLD §5.1).

None are defined in this phase. `Student`'s own constructor already enforces everything that's
a pure function of its own fields (non-empty/length-bounded `full_name`/`external_ref`). The
one candidate that might look like a domain service — "does this student already exist" /
uniqueness checking — needs a repository query (I/O) to check existing rows, which makes it an
*application*-layer concern (orchestration via the repository), not a domain service (domain
services are stateless operations over already-loaded entities, LLD §5.1), mirroring
`organization.domain.services`'s identical reasoning for region-name uniqueness. Add a domain
service here only if a future rule genuinely needs to span two loaded aggregates without I/O —
e.g. once `StudentAssignment` (a later phase, deliberately out of this phase's scope per
`entities.py`'s module docstring) exists alongside `Student`.

**Phase 11 (`Route`/`Stop`):** same reasoning again. `Route`'s own constructor/`add_stop`/
`move_stop` already enforce everything that's a pure function of already-loaded state
(sequence uniqueness, coordinate bounds, name length) directly on the aggregate — no separate
domain service needed. Per-tenant route-name uniqueness needs a repository query (I/O), so it
is an application-layer concern (`application/validators.py`'s `ensure_route_name_available`),
mirroring `fleet_device.application.validators.ensure_plate_no_available`'s identical
reasoning.

**Phase 12 (`Trip`):** same reasoning again. `Trip.schedule`'s cross-organization check
compares two already-loaded aggregates' `organization_id`s with no I/O of its own (mirroring
`StudentParent.link`'s identical placement) — a pure aggregate-constructor concern, not a
domain service. `Trip`'s one genuinely I/O-dependent rule, one-active-trip-per-vehicle, needs a
repository query, so it lives in the application layer instead
(`application/validators.py`'s `ensure_vehicle_has_no_active_trip`).

**Phase 13 (`StudentAssignment`):** same reasoning again. `StudentAssignment.assign`'s
cross-organization checks are pure, no-I/O comparisons of already-loaded aggregates, mirroring
`Trip.schedule`'s identical placement. The one I/O-dependent rule, one-active-assignment-per-
student, lives in the application layer (`application/validators.py`'s
`ensure_student_has_no_active_assignment`), and pickup/dropoff stop existence-checking is a
repository-query concern too (`ensure_pickup_and_dropoff_stops_exist`) — neither is a domain
service.

**Phase 4 (ADR-0058 §2):** `staff_compliance` is the first one. It spans loaded
`StaffDocumentType`s and `StaffDocument`s without I/O, and is the single place that decides
whether a person meets their document requirements on a day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from raad.modules.transport_ops.domain.entities import StaffDocument, StaffDocumentType
from raad.modules.transport_ops.domain.value_objects import (
    ComplianceStatus,
    StaffDocumentEnforcement,
)


@dataclass(frozen=True)
class RequirementGap:
    """A requirement the person does not meet. Never carries a document number."""

    type_id: str
    type_name: str
    #: `missing` (no current document of the type) or `expired`.
    reason: str
    expired_on: date | None
    #: The type's enforcement is `block` (ADR-0059 §3).
    blocks: bool


@dataclass(frozen=True)
class ExpiringRequirement:
    type_id: str
    type_name: str
    expires_on: date


@dataclass(frozen=True)
class StaffCompliance:
    status: ComplianceStatus
    gaps: tuple[RequirementGap, ...] = ()
    expiring: tuple[ExpiringRequirement, ...] = ()

    @property
    def is_compliant(self) -> bool:
        return self.status is not ComplianceStatus.NOT_COMPLIANT

    @property
    def blocking_gaps(self) -> tuple[RequirementGap, ...]:
        return tuple(g for g in self.gaps if g.blocks)

    def describe_gaps(self, gaps: Iterable[RequirementGap] | None = None) -> str:
        """"Driving licence expired on 2026-10-03; Medical certificate missing"."""
        parts = [
            f"{g.type_name} expired on {g.expired_on.isoformat()}"
            if g.reason == "expired" and g.expired_on is not None
            else f"{g.type_name} missing"
            for g in (self.gaps if gaps is None else gaps)
        ]
        return "; ".join(parts)


def staff_compliance(
    *,
    is_driver: bool,
    types: Iterable[StaffDocumentType],
    documents: Iterable[StaffDocument],
    day: date,
) -> StaffCompliance:
    """ADR-0058 §2. `types` are the organization's document types and `documents` that person's
    documents; types that do not apply and superseded documents are ignored here, so callers
    need not pre-filter. A document is valid through its expiry date; one with no expiry date
    always meets its requirement."""
    documents = [d for d in documents if d.replaced_by_id is None]
    gaps: list[RequirementGap] = []
    expiring: list[ExpiringRequirement] = []
    for doc_type in sorted(types, key=lambda t: t.name.lower()):
        if not doc_type.applies_to(is_driver=is_driver):
            continue
        held = [d for d in documents if d.type_id == doc_type.id]
        valid = [d for d in held if d.expires_on is None or d.expires_on >= day]
        if not valid:
            gaps.append(
                RequirementGap(
                    type_id=str(doc_type.id),
                    type_name=doc_type.name,
                    reason="expired" if held else "missing",
                    expired_on=max(d.expires_on for d in held) if held else None,  # type: ignore[type-var]
                    blocks=doc_type.enforcement is StaffDocumentEnforcement.BLOCK,
                )
            )
            continue
        if all(d.expires_on is not None for d in valid):
            furthest = max(d.expires_on for d in valid)  # type: ignore[type-var]
            if (furthest - day).days <= max(doc_type.alert_lead_days, default=0):
                expiring.append(ExpiringRequirement(str(doc_type.id), doc_type.name, furthest))
    if gaps:
        status = ComplianceStatus.NOT_COMPLIANT
    elif expiring:
        status = ComplianceStatus.EXPIRING
    else:
        status = ComplianceStatus.COMPLIANT
    return StaffCompliance(status=status, gaps=tuple(gaps), expiring=tuple(expiring))
