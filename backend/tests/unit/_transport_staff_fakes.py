"""Shared in-memory fakes for the ADR-0049/0050/0051 repositories, used by every
`transport_ops` unit test whose Unit of Work touches staff: the driver service (a new driver is
a staff member first), the trip tests, and the staff service's own tests. One set of fakes, so
the tests cannot drift into two different ideas of what a staff query returns.

Mirrors the SQLAlchemy repositories' ordering: assignments newest start first, documents newest
first, current documents with an expiry soonest first.
"""

from __future__ import annotations

from raad.core.pagination import FilterCondition, OffsetPage, OffsetPageRequest, SortSpec
from raad.modules.transport_ops.domain.entities import (
    StaffDocument,
    StaffDocumentType,
    TransportStaff,
    TransportStaffRole,
    VehicleStaffAssignment,
)
from raad.modules.transport_ops.domain.repositories import (
    OperatingClosureRepository,
    RouteTimetableEntryRepository,
    StaffCoverRepository,
    StaffUnavailabilityRepository,
    StaffDocumentRepository,
    StaffDocumentTypeRepository,
    TransportStaffRepository,
    TransportStaffRoleRepository,
    VehicleStaffAssignmentRepository,
)


class InMemoryTransportStaffRoleRepository(TransportStaffRoleRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, TransportStaffRole] = {}

    async def get(self, role_id):
        return self.by_id.get(str(role_id))

    def add(self, role: TransportStaffRole) -> None:
        self.by_id[str(role.id)] = role

    async def list_for_organization(self, organization_id: str) -> list[TransportStaffRole]:
        return sorted(
            (r for r in self.by_id.values() if str(r.organization_id) == organization_id),
            key=lambda r: (r.sort_order, r.name),
        )


class InMemoryTransportStaffRepository(TransportStaffRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, TransportStaff] = {}

    async def get(self, staff_id):
        return self.by_id.get(str(staff_id))

    def add(self, staff: TransportStaff) -> None:
        self.by_id[str(staff.id)] = staff

    async def get_by_employee_ref(self, *, organization_id: str, employee_ref: str):
        return next(
            (
                s
                for s in self.by_id.values()
                if str(s.organization_id) == organization_id and s.employee_ref == employee_ref
            ),
            None,
        )

    async def list_by_ids(self, staff_ids: list[str]) -> list[TransportStaff]:
        return [self.by_id[i] for i in dict.fromkeys(staff_ids) if i in self.by_id]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[TransportStaff]:
        rows = sorted(self.by_id.values(), key=lambda s: s.full_name)
        for condition in filters:
            rows = [
                s
                for s in rows
                if str(getattr(getattr(s, condition.field), "value", getattr(s, condition.field)))
                == str(condition.value)
            ]
        if search:
            rows = [s for s in rows if search.casefold() in s.full_name.casefold()]
        start = (page_request.page - 1) * page_request.page_size
        return OffsetPage(
            data=rows[start : start + page_request.page_size],
            total=len(rows),
            page=page_request.page,
            page_size=page_request.page_size,
        )


class InMemoryVehicleStaffAssignmentRepository(VehicleStaffAssignmentRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, VehicleStaffAssignment] = {}

    async def get(self, assignment_id):
        return self.by_id.get(str(assignment_id))

    def add(self, assignment: VehicleStaffAssignment) -> None:
        self.by_id[str(assignment.id)] = assignment

    async def list_between(self, start, end, *, vehicle_id=None) -> list[VehicleStaffAssignment]:
        return [
            a
            for a in self.by_id.values()
            if a.starts_on <= end
            and (a.ends_on is None or a.ends_on >= start)
            and (vehicle_id is None or a.vehicle_id == vehicle_id)
        ]

    async def list_for(self, *, staff_id=None, vehicle_id=None) -> list[VehicleStaffAssignment]:
        rows = [
            a
            for a in self.by_id.values()
            if (staff_id is None or a.staff_id == staff_id)
            and (vehicle_id is None or a.vehicle_id == vehicle_id)
        ]
        return sorted(rows, key=lambda a: (a.starts_on, a.created_at), reverse=True)


class InMemoryStaffDocumentTypeRepository(StaffDocumentTypeRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, StaffDocumentType] = {}

    async def get(self, type_id):
        return self.by_id.get(str(type_id))

    def add(self, doc_type: StaffDocumentType) -> None:
        self.by_id[str(doc_type.id)] = doc_type

    async def list_for_organization(self, organization_id: str) -> list[StaffDocumentType]:
        return sorted(
            (t for t in self.by_id.values() if str(t.organization_id) == organization_id),
            key=lambda t: t.name,
        )

    async def list_by_ids(self, type_ids: list[str]) -> list[StaffDocumentType]:
        return [self.by_id[i] for i in dict.fromkeys(type_ids) if i in self.by_id]


class InMemoryStaffDocumentRepository(StaffDocumentRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, StaffDocument] = {}

    async def get(self, document_id):
        return self.by_id.get(str(document_id))

    def add(self, document: StaffDocument) -> None:
        self.by_id[str(document.id)] = document

    async def list_for_staff(self, staff_id) -> list[StaffDocument]:
        return sorted(
            (d for d in self.by_id.values() if d.staff_id == staff_id),
            key=lambda d: d.created_at,
            reverse=True,
        )

    async def list_current_with_expiry(self) -> list[StaffDocument]:
        return sorted(
            (
                d
                for d in self.by_id.values()
                if d.replaced_by_id is None and d.expires_on is not None
            ),
            key=lambda d: d.expires_on,
        )


class InMemoryRouteTimetableEntryRepository(RouteTimetableEntryRepository):
    def __init__(self) -> None:
        self.by_id: dict = {}

    async def get(self, entry_id):
        return self.by_id.get(str(entry_id))

    def add(self, entry) -> None:
        self.by_id[str(entry.id)] = entry

    async def list_all(self, *, route_id=None):
        return [e for e in self.by_id.values() if route_id is None or e.route_id == route_id]


class _Dated:
    def __init__(self) -> None:
        self.by_id: dict = {}

    async def get(self, item_id):
        return self.by_id.get(str(item_id))

    def add(self, item) -> None:
        self.by_id[str(item.id)] = item

    def _overlapping(self, start, end):
        return sorted(
            (
                i
                for i in self.by_id.values()
                if i.withdrawn_at is None and i.starts_on <= end and i.ends_on >= start
            ),
            key=lambda i: i.starts_on,
        )


class InMemoryOperatingClosureRepository(_Dated, OperatingClosureRepository):
    async def list_overlapping(self, start, end):
        return self._overlapping(start, end)


class InMemoryStaffUnavailabilityRepository(_Dated, StaffUnavailabilityRepository):
    async def list_overlapping(self, start, end, *, staff_id=None):
        return [i for i in self._overlapping(start, end) if staff_id is None or i.staff_id == staff_id]

    async def list_for_staff(self, staff_id):
        return sorted(
            (i for i in self.by_id.values() if i.staff_id == staff_id),
            key=lambda i: i.starts_on,
            reverse=True,
        )


class InMemoryStaffCoverRepository(_Dated, StaffCoverRepository):
    async def list_overlapping(self, start, end):
        return self._overlapping(start, end)

    async def list_for_unavailability(self, unavailability_id):
        return [c for c in self.by_id.values() if c.unavailability_id == unavailability_id]


def attach_staff_repositories(uow) -> None:
    """Gives a fake `TransportOpsUnitOfWork` empty staff repositories."""
    uow.staff_roles = InMemoryTransportStaffRoleRepository()
    uow.staff = InMemoryTransportStaffRepository()
    uow.staff_assignments = InMemoryVehicleStaffAssignmentRepository()
    uow.staff_document_types = InMemoryStaffDocumentTypeRepository()
    uow.staff_documents = InMemoryStaffDocumentRepository()
    uow.timetable = InMemoryRouteTimetableEntryRepository()
    uow.closures = InMemoryOperatingClosureRepository()
    uow.unavailability = InMemoryStaffUnavailabilityRepository()
    uow.covers = InMemoryStaffCoverRepository()
