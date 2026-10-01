"""Document compliance for the application layer (ADR-0058, ADR-0059).

`ComplianceIndex` loads the required document types, the current documents and who has driver
access once, then answers "is this person compliant on this day?" for any number of people and
days without another query. The staff service, the daily-operations coverage rule and the four
planning checks all ask it, so they cannot disagree.

The rule itself is `domain.services.staff_compliance`; this module only loads and shapes.
"""

from __future__ import annotations

from datetime import date

from raad.core.errors.exceptions import RuleViolationError

from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    ComplianceExpiringDTO,
    ComplianceGapDTO,
    StaffComplianceDTO,
)
from raad.modules.transport_ops.domain.entities import (
    StaffDocument,
    StaffDocumentType,
    TransportStaff,
)
from raad.modules.transport_ops.domain.services import StaffCompliance, staff_compliance
from raad.modules.transport_ops.domain.value_objects import (
    ComplianceStatus,
    TransportStaffId,
    TransportStaffStatus,
)


def compliance_to_dto(compliance: StaffCompliance) -> StaffComplianceDTO:
    return StaffComplianceDTO(
        status=compliance.status.value,
        gaps=[
            ComplianceGapDTO(g.type_id, g.type_name, g.reason, g.expired_on, g.blocks)
            for g in compliance.gaps
        ],
        expiring=[
            ComplianceExpiringDTO(e.type_id, e.type_name, e.expires_on) for e in compliance.expiring
        ],
        is_blocked=bool(compliance.blocking_gaps),
    )


_COMPLIANT = StaffCompliance(status=ComplianceStatus.COMPLIANT)


class ComplianceIndex:
    def __init__(
        self,
        *,
        types: list[StaffDocumentType],
        documents: list[StaffDocument],
        driver_staff_ids: set[str],
    ) -> None:
        self._types_by_org: dict[str, list[StaffDocumentType]] = {}
        for doc_type in types:
            self._types_by_org.setdefault(str(doc_type.organization_id), []).append(doc_type)
        self._documents_by_staff: dict[str, list[StaffDocument]] = {}
        for document in documents:
            self._documents_by_staff.setdefault(str(document.staff_id), []).append(document)
        self._driver_staff_ids = driver_staff_ids

    @property
    def has_requirements(self) -> bool:
        return bool(self._types_by_org)

    def is_driver(self, staff: TransportStaff) -> bool:
        return str(staff.id) in self._driver_staff_ids

    def of(self, staff: TransportStaff, day: date) -> StaffCompliance | None:
        """`None` for someone who has left: they have no compliance status (ADR-0058 §2)."""
        if staff.status is TransportStaffStatus.LEFT:
            return None
        types = self._types_by_org.get(str(staff.organization_id))
        if not types:
            return _COMPLIANT
        return staff_compliance(
            is_driver=self.is_driver(staff),
            types=types,
            documents=self._documents_by_staff.get(str(staff.id), ()),
            day=day,
        )


async def load_compliance_index(
    uow: TransportOpsUnitOfWork, staff: list[TransportStaff]
) -> ComplianceIndex:
    """Call inside an open unit of work, before any `add()` (reads first: the Phase 2 lesson).
    Three queries at most, and one when the organization requires nothing."""
    types = await uow.staff_document_types.list_required()
    staff_ids = sorted({str(s.id) for s in staff})
    if not types or not staff_ids:
        return ComplianceIndex(types=types if staff_ids else [], documents=[], driver_staff_ids=set())
    documents = await uow.staff_documents.list_current_of_types(
        [str(t.id) for t in types], staff_ids=staff_ids
    )
    drivers = await uow.drivers.list_by_staff_ids(staff_ids)
    return ComplianceIndex(
        types=types, documents=documents, driver_staff_ids={str(d.staff_id) for d in drivers}
    )


async def planning_compliance_warnings(
    uow: TransportOpsUnitOfWork,
    staff_id: TransportStaffId,
    day: date,
    *,
    refuse_blocked: bool,
) -> list[str]:
    """ADR-0059 §3: the check the four planning actions share. Returns the warning to show, or
    raises `RuleViolationError` (409) when a requirement the person does not meet on `day`
    belongs to a `block` type and this action refuses. Read-only: call it before any `add()`.

    A lapse only ever appears as days go by, so checking the *last* day of a period finds a
    lapse on any day of it."""
    person = await uow.staff.get(staff_id)
    if person is None:
        return []
    compliance = (await load_compliance_index(uow, [person])).of(person, day)
    if compliance is None or compliance.is_compliant:
        return []
    blocking = compliance.blocking_gaps
    if blocking and refuse_blocked:
        raise RuleViolationError(
            f"{person.full_name} cannot be planned on {day.isoformat()}: "
            f"{compliance.describe_gaps(blocking)}."
        )
    return [
        f"{person.full_name} is not compliant on {day.isoformat()}: {compliance.describe_gaps()}."
    ]
