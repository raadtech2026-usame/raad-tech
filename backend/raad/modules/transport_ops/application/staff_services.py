"""Transport staff, bus crew and staff documents (ADR-0049, ADR-0050, ADR-0051).

Kept apart from `services.py` because the three aggregates here share one surface (the staff
page) and none of `services.py`'s use-cases. The shape is the same: load, call the aggregate,
record its events, commit, return a DTO.

Two rules from the ADRs are enforced here, not in the domain:

* **Cross-aggregate organization checks.** A job title, route or document type must belong to
  the same organization as the staff member; the bus must too, and it belongs to `fleet_device`,
  so it is resolved through `VehicleDirectoryPort` rather than read (`.claude/rules/backend.md`
  #3). A bus in another organization answers 404, as if it did not exist.
* **Leaving is one transaction** (ADR-0049 §4): marking someone `left` ends every current or
  future crew assignment and deactivates their driver profile in the same commit, so no bus
  keeps a crew member who is gone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from raad.core.errors.exceptions import (
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import OffsetPage
from raad.core.tenancy.principal import Role
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    AddDefaultStaffSetupCommand,
    AssignStaffToVehicleCommand,
    ChangeTransportStaffStatusCommand,
    EndStaffAssignmentCommand,
    GrantDriverAccessCommand,
    RecordStaffDocumentCommand,
    RegisterTransportStaffCommand,
    SaveStaffDocumentTypeCommand,
    SaveStaffRoleCommand,
    UpdateStaffDocumentCommand,
    UpdateTransportStaffCommand,
)
from raad.modules.transport_ops.application.ports import (
    TransportOpsUnitOfWork,
    UserProvisioningPort,
    VehicleDirectoryPort,
)
from raad.modules.transport_ops.application.queries import (
    DriverDTO,
    DueExpiryAlertDTO,
    ListTransportStaffQuery,
    StaffDocumentDTO,
    StaffDocumentTypeDTO,
    StaffDriverProfileDTO,
    TransportStaffDTO,
    TransportStaffRoleDTO,
    TransportStaffSummaryDTO,
    VehicleStaffAssignmentDTO,
    driver_to_dto,
)
from raad.modules.transport_ops.application.services import _enforce_own_organization
from raad.modules.transport_ops.domain.entities import (
    Driver,
    StaffDocument,
    StaffDocumentType,
    TransportStaff,
    TransportStaffRole,
    VehicleStaffAssignment,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    OrganizationId,
    PhoneNumber,
    RouteId,
    StaffAssignmentKind,
    StaffDocumentId,
    StaffDocumentTypeId,
    TransportStaffId,
    TransportStaffRoleId,
    TransportStaffStatus,
    UserId,
    VehicleId,
    VehicleStaffAssignmentId,
)

#: ADR-0049 §2: the titles "Add default titles" creates. Existing organizations were seeded with
#: the same list by the migration.
DEFAULT_STAFF_ROLES: tuple[str, ...] = (
    "Driver",
    "Attendant",
    "Assistant",
    "Conductor",
    "Supervisor",
)
#: The title a new `POST /drivers` staff record gets, when the organization has it.
DRIVER_ROLE_NAME = "Driver"

#: ADR-0051 §1: the document types "Add default types" creates, all alerting at 30 and 7 days.
DEFAULT_STAFF_DOCUMENT_TYPES: tuple[str, ...] = (
    "Driving licence",
    "National ID/Passport",
    "Medical certificate",
    "Police clearance",
    "First-aid certificate",
    "Other",
)
DEFAULT_ALERT_LEAD_DAYS: tuple[int, ...] = (30, 7)

_PHONE_FIELDS = ("phone", "alternate_phone", "emergency_contact_phone")


def _phone(value: str | None) -> PhoneNumber | None:
    return PhoneNumber(value) if value else None


def _clean(value: str | None) -> str | None:
    """Blank form fields mean "not set"."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _role_to_dto(role: TransportStaffRole) -> TransportStaffRoleDTO:
    return TransportStaffRoleDTO(
        id=str(role.id),
        organization_id=str(role.organization_id),
        name=role.name,
        sort_order=role.sort_order,
        is_archived=role.is_archived,
    )


def _type_to_dto(doc_type: StaffDocumentType) -> StaffDocumentTypeDTO:
    return StaffDocumentTypeDTO(
        id=str(doc_type.id),
        organization_id=str(doc_type.organization_id),
        name=doc_type.name,
        alert_lead_days=list(doc_type.alert_lead_days),
        is_archived=doc_type.is_archived,
    )


def _driver_profile(driver: Driver | None) -> StaffDriverProfileDTO | None:
    if driver is None:
        return None
    return StaffDriverProfileDTO(
        driver_id=str(driver.id),
        user_id=str(driver.user_id),
        license_no=driver.license_no,
        status=driver.status.value,
    )


def _str_or_none(value: object | None) -> str | None:
    return str(value) if value is not None else None


@dataclass(frozen=True)
class _DueAlert:
    document: StaffDocument
    threshold_days: int


class TransportStaffApplicationService:
    """Every use-case behind the Transport Staff page: job titles, staff records, driver access,
    bus crew assignments, document types and documents, plus the two reads the expiry-alert job
    needs."""

    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        user_provisioning: UserProvisioningPort,
        vehicle_directory: VehicleDirectoryPort,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._user_provisioning = user_provisioning
        self._vehicle_directory = vehicle_directory

    def _today(self) -> date:
        return self._clock.now().date()

    # ---- job titles -----------------------------------------------------------------------

    async def list_roles(
        self, organization_id: str, *, uow: TransportOpsUnitOfWork
    ) -> list[TransportStaffRoleDTO]:
        async with uow:
            roles = await uow.staff_roles.list_for_organization(organization_id)
            return [_role_to_dto(role) for role in roles]

    async def save_role(
        self, command: SaveStaffRoleCommand, *, uow: TransportOpsUnitOfWork
    ) -> TransportStaffRoleDTO:
        _enforce_own_organization(actor=command.actor, organization_id=command.organization_id)
        async with uow:
            existing = await uow.staff_roles.list_for_organization(command.organization_id)
            self._ensure_unique_name(
                [(str(r.id), r.name) for r in existing],
                command.name,
                exclude_id=command.role_id,
                what="job title",
            )
            if command.role_id is None:
                role = TransportStaffRole.create(
                    id=TransportStaffRoleId(self._id_generator.new_id()),
                    organization_id=OrganizationId(command.organization_id),
                    name=command.name,
                    sort_order=command.sort_order,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                uow.staff_roles.add(role)
            else:
                role = await self._get_role(uow, command.role_id, command.organization_id)
                role.update(
                    name=command.name,
                    sort_order=command.sort_order,
                    is_archived=command.is_archived,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
            uow.record_events(role.pull_domain_events())
            await uow.commit()
            return _role_to_dto(role)

    async def add_default_roles(
        self, command: AddDefaultStaffSetupCommand, *, uow: TransportOpsUnitOfWork
    ) -> list[TransportStaffRoleDTO]:
        """Adds whichever default titles the organization does not already have (by name,
        ignoring case). Safe to press twice."""
        _enforce_own_organization(actor=command.actor, organization_id=command.organization_id)
        async with uow:
            existing = await uow.staff_roles.list_for_organization(command.organization_id)
            have = {role.name.casefold() for role in existing}
            next_order = max((role.sort_order for role in existing), default=0)
            for name in DEFAULT_STAFF_ROLES:
                if name.casefold() in have:
                    continue
                next_order += 10
                role = TransportStaffRole.create(
                    id=TransportStaffRoleId(self._id_generator.new_id()),
                    organization_id=OrganizationId(command.organization_id),
                    name=name,
                    sort_order=next_order,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                uow.staff_roles.add(role)
                uow.record_events(role.pull_domain_events())
                existing.append(role)
            await uow.commit()
            return [_role_to_dto(role) for role in existing]

    # ---- document types -------------------------------------------------------------------

    async def list_document_types(
        self, organization_id: str, *, uow: TransportOpsUnitOfWork
    ) -> list[StaffDocumentTypeDTO]:
        async with uow:
            types = await uow.staff_document_types.list_for_organization(organization_id)
            return [_type_to_dto(t) for t in types]

    async def save_document_type(
        self, command: SaveStaffDocumentTypeCommand, *, uow: TransportOpsUnitOfWork
    ) -> StaffDocumentTypeDTO:
        _enforce_own_organization(actor=command.actor, organization_id=command.organization_id)
        async with uow:
            existing = await uow.staff_document_types.list_for_organization(
                command.organization_id
            )
            self._ensure_unique_name(
                [(str(t.id), t.name) for t in existing],
                command.name,
                exclude_id=command.type_id,
                what="document type",
            )
            if command.type_id is None:
                doc_type = StaffDocumentType.create(
                    id=StaffDocumentTypeId(self._id_generator.new_id()),
                    organization_id=OrganizationId(command.organization_id),
                    name=command.name,
                    alert_lead_days=command.alert_lead_days,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                uow.staff_document_types.add(doc_type)
            else:
                doc_type = await self._get_document_type(
                    uow, command.type_id, command.organization_id
                )
                doc_type.update(
                    name=command.name,
                    alert_lead_days=command.alert_lead_days,
                    is_archived=command.is_archived,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
            uow.record_events(doc_type.pull_domain_events())
            await uow.commit()
            return _type_to_dto(doc_type)

    async def add_default_document_types(
        self, command: AddDefaultStaffSetupCommand, *, uow: TransportOpsUnitOfWork
    ) -> list[StaffDocumentTypeDTO]:
        _enforce_own_organization(actor=command.actor, organization_id=command.organization_id)
        async with uow:
            existing = await uow.staff_document_types.list_for_organization(
                command.organization_id
            )
            have = {t.name.casefold() for t in existing}
            for name in DEFAULT_STAFF_DOCUMENT_TYPES:
                if name.casefold() in have:
                    continue
                doc_type = StaffDocumentType.create(
                    id=StaffDocumentTypeId(self._id_generator.new_id()),
                    organization_id=OrganizationId(command.organization_id),
                    name=name,
                    alert_lead_days=DEFAULT_ALERT_LEAD_DAYS,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                uow.staff_document_types.add(doc_type)
                uow.record_events(doc_type.pull_domain_events())
                existing.append(doc_type)
            await uow.commit()
            return [_type_to_dto(t) for t in sorted(existing, key=lambda t: t.name.casefold())]

    # ---- staff records --------------------------------------------------------------------

    async def register_staff(
        self, command: RegisterTransportStaffCommand, *, uow: TransportOpsUnitOfWork
    ) -> TransportStaffDTO:
        _enforce_own_organization(actor=command.actor, organization_id=command.organization_id)
        async with uow:
            role_id = await self._usable_role_id(uow, command.role_id, command.organization_id)
            employee_ref = _clean(command.employee_ref)
            await self._ensure_employee_ref_free(uow, command.organization_id, employee_ref)
            staff = TransportStaff.register(
                id=TransportStaffId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                full_name=command.full_name,
                phone=_phone(_clean(command.phone)),
                alternate_phone=_phone(_clean(command.alternate_phone)),
                role_id=role_id,
                employee_ref=employee_ref,
                start_date=command.start_date,
                emergency_contact_name=_clean(command.emergency_contact_name),
                emergency_contact_phone=_phone(_clean(command.emergency_contact_phone)),
                notes=_clean(command.notes),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.staff.add(staff)
            uow.record_events(staff.pull_domain_events())
            await uow.commit()
            return await self._staff_dto(uow, staff)

    async def update_staff(
        self, command: UpdateTransportStaffCommand, *, uow: TransportOpsUnitOfWork
    ) -> TransportStaffDTO:
        async with uow:
            staff = await self._get_staff(uow, command.staff_id)
            values: dict[str, object] = {}
            for field_name, raw in command.changes.items():
                if field_name in _PHONE_FIELDS:
                    values[field_name] = _phone(_clean(raw))
                elif field_name == "role_id":
                    values[field_name] = await self._usable_role_id(
                        uow, raw, str(staff.organization_id), current=staff.role_id
                    )
                elif field_name == "start_date":
                    values[field_name] = raw
                else:
                    values[field_name] = _clean(raw)
            if "employee_ref" in values and values["employee_ref"] != staff.employee_ref:
                await self._ensure_employee_ref_free(
                    uow, str(staff.organization_id), values["employee_ref"]  # type: ignore[arg-type]
                )
            staff.update_profile(clock=self._clock, actor_id=command.actor.user_id, **values)
            uow.record_events(staff.pull_domain_events())
            await uow.commit()
            return await self._staff_dto(uow, staff)

    async def change_status(
        self, command: ChangeTransportStaffStatusCommand, *, uow: TransportOpsUnitOfWork
    ) -> TransportStaffDTO:
        try:
            status = TransportStaffStatus(command.status)
        except ValueError as exc:
            raise ValidationError(f"Unknown staff status {command.status!r}.") from exc
        async with uow:
            staff = await self._get_staff(uow, command.staff_id)
            changed = staff.change_status(
                status, clock=self._clock, actor_id=command.actor.user_id
            )
            uow.record_events(staff.pull_domain_events())
            if changed and status is TransportStaffStatus.LEFT:
                today = self._today()
                for assignment in await uow.staff_assignments.list_for(staff_id=staff.id):
                    if assignment.ends_on is None or assignment.ends_on >= today:
                        assignment.end(today, clock=self._clock, actor_id=command.actor.user_id)
                        uow.record_events(assignment.pull_domain_events())
                driver = await uow.drivers.get_by_staff_id(staff.id)
                if driver is not None:
                    driver.disable(clock=self._clock, actor_id=command.actor.user_id)
                    uow.record_events(driver.pull_domain_events())
            await uow.commit()
            return await self._staff_dto(uow, staff)

    async def get_staff(self, staff_id: str, *, uow: TransportOpsUnitOfWork) -> TransportStaffDTO:
        async with uow:
            return await self._staff_dto(uow, await self._get_staff(uow, staff_id))

    async def list_staff(
        self, query: ListTransportStaffQuery, *, uow: TransportOpsUnitOfWork
    ) -> OffsetPage[TransportStaffSummaryDTO]:
        async with uow:
            page = await uow.staff.list_page(
                query.page_request, sort=query.sort, filters=query.filters, search=query.search
            )
            role_names = await self._role_names(uow, [s.role_id for s in page.data])
            drivers = await uow.drivers.list_by_staff_ids([str(s.id) for s in page.data])
            driver_staff = {str(d.staff_id) for d in drivers}
            return OffsetPage(
                data=[
                    TransportStaffSummaryDTO(
                        id=str(s.id),
                        organization_id=str(s.organization_id),
                        full_name=s.full_name,
                        phone=_str_or_none(s.phone),
                        role_id=_str_or_none(s.role_id),
                        role_name=role_names.get(str(s.role_id)) if s.role_id else None,
                        employee_ref=s.employee_ref,
                        status=s.status.value,
                        is_driver=str(s.id) in driver_staff,
                    )
                    for s in page.data
                ],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    async def get_staff_names(
        self, staff_ids: list[str], *, uow: TransportOpsUnitOfWork
    ) -> dict[str, str]:
        """Names for a set of staff ids (the Drivers page shows a name, not a licence)."""
        async with uow:
            return {str(s.id): s.full_name for s in await uow.staff.list_by_ids(staff_ids)}

    # ---- driver access --------------------------------------------------------------------

    async def grant_driver_access(
        self, command: GrantDriverAccessCommand, *, uow: TransportOpsUnitOfWork
    ) -> tuple[DriverDTO, str]:
        """ADR-0049 §3: a login plus a driver profile for someone already on the staff list.
        Provisioning happens before the driver row, as in `register_driver`, with the same
        accepted orphan-login gap on a failure between the two (ADR-0003). The unique index on
        `drivers.staff_id` turns a double submission into a 409."""
        async with uow:
            staff = await self._get_staff(uow, command.staff_id)
            if staff.status is not TransportStaffStatus.ACTIVE:
                raise DomainError("Only an active staff member can be given driver access.")
            if await uow.drivers.get_by_staff_id(staff.id) is not None:
                raise ConflictError(f"{staff.full_name} already has driver access.")
            organization_id = str(staff.organization_id)
            full_name = staff.full_name
            phone = _clean(command.phone) or _str_or_none(staff.phone)
        _enforce_own_organization(actor=command.actor, organization_id=organization_id)
        user_id, temporary_password = (
            await self._user_provisioning.create_user_with_temporary_password(
                organization_id=organization_id,
                role=Role.DRIVER,
                email=_clean(command.email),
                phone=phone,
                full_name=full_name,
                actor=command.actor,
            )
        )
        async with uow:
            driver = Driver.register(
                id=DriverId(self._id_generator.new_id()),
                organization_id=OrganizationId(organization_id),
                user_id=UserId(user_id),
                license_no=command.license_no,
                staff_id=TransportStaffId(command.staff_id),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.drivers.add(driver)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            return driver_to_dto(driver), temporary_password

    # ---- bus crew -------------------------------------------------------------------------

    async def assign_to_vehicle(
        self, command: AssignStaffToVehicleCommand, *, uow: TransportOpsUnitOfWork
    ) -> VehicleStaffAssignmentDTO:
        try:
            kind = StaffAssignmentKind(command.kind)
        except ValueError as exc:
            raise ValidationError(f"Unknown assignment kind {command.kind!r}.") from exc
        async with uow:
            staff = await self._get_staff(uow, command.staff_id)
            organization_id = str(staff.organization_id)
            if staff.status is not TransportStaffStatus.ACTIVE:
                raise DomainError("Only an active staff member can be assigned to a bus.")
            vehicle_organization = await self._vehicle_directory.organization_of_vehicle(
                command.vehicle_id
            )
            if vehicle_organization != organization_id:
                raise NotFoundError(f"Vehicle {command.vehicle_id} not found.")
            route_id: RouteId | None = None
            if command.route_id:
                route = await uow.routes.get(RouteId(command.route_id))
                if route is None or str(route.organization_id) != organization_id:
                    raise NotFoundError(f"Route {command.route_id} not found.")
                route_id = route.id
            role_id = (
                await self._usable_role_id(uow, command.role_id, organization_id)
                if command.role_id
                else staff.role_id
            )
            starts_on = command.starts_on or self._today()
            ends_on = command.ends_on
            vehicle_id = VehicleId(command.vehicle_id)
            for other in await uow.staff_assignments.list_for(
                staff_id=staff.id, vehicle_id=vehicle_id
            ):
                if other.overlaps(starts_on, ends_on):
                    raise ConflictError(
                        f"{staff.full_name} is already on this bus for part of that period."
                    )
            assignment = VehicleStaffAssignment.assign(
                id=VehicleStaffAssignmentId(self._id_generator.new_id()),
                organization_id=OrganizationId(organization_id),
                staff_id=staff.id,
                vehicle_id=vehicle_id,
                role_id=role_id,
                route_id=route_id,
                starts_on=starts_on,
                ends_on=ends_on,
                kind=kind,
                reason=_clean(command.reason),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.staff_assignments.add(assignment)
            uow.record_events(assignment.pull_domain_events())
            await uow.commit()
            return (await self._assignment_dtos(uow, [assignment]))[0]

    async def end_assignment(
        self, command: EndStaffAssignmentCommand, *, uow: TransportOpsUnitOfWork
    ) -> VehicleStaffAssignmentDTO:
        async with uow:
            assignment = await uow.staff_assignments.get(
                VehicleStaffAssignmentId(command.assignment_id)
            )
            if assignment is None:
                raise NotFoundError(f"Assignment {command.assignment_id} not found.")
            assignment.end(
                command.ends_on or self._today(),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(assignment.pull_domain_events())
            await uow.commit()
            return (await self._assignment_dtos(uow, [assignment]))[0]

    async def list_assignments(
        self,
        *,
        uow: TransportOpsUnitOfWork,
        staff_id: str | None = None,
        vehicle_id: str | None = None,
        current_only: bool = False,
    ) -> list[VehicleStaffAssignmentDTO]:
        if staff_id is None and vehicle_id is None:
            raise ValidationError("Filter by a staff member or a vehicle.")
        async with uow:
            assignments = await uow.staff_assignments.list_for(
                staff_id=TransportStaffId(staff_id) if staff_id else None,
                vehicle_id=VehicleId(vehicle_id) if vehicle_id else None,
            )
            if current_only:
                today = self._today()
                assignments = [a for a in assignments if a.is_current(today)]
            return await self._assignment_dtos(uow, assignments)

    # ---- documents ------------------------------------------------------------------------

    async def record_document(
        self, command: RecordStaffDocumentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StaffDocumentDTO:
        async with uow:
            staff = await self._get_staff(uow, command.staff_id)
            doc_type = await self._get_document_type(
                uow, command.type_id, str(staff.organization_id)
            )
            if doc_type.is_archived:
                raise DomainError(f"Document type {doc_type.name!r} is archived.")
            replaced: StaffDocument | None = None
            if command.replaces_id:
                replaced = await uow.staff_documents.get(StaffDocumentId(command.replaces_id))
                if replaced is None or replaced.staff_id != staff.id:
                    raise NotFoundError(f"Document {command.replaces_id} not found.")
                if replaced.type_id != doc_type.id:
                    raise DomainError("A renewal must be the same type of document.")
            document = StaffDocument.record(
                id=StaffDocumentId(self._id_generator.new_id()),
                organization_id=staff.organization_id,
                staff_id=staff.id,
                type_id=doc_type.id,
                number=_clean(command.number),
                issued_on=command.issued_on,
                expires_on=command.expires_on,
                notes=_clean(command.notes),
                replaces_id=replaced.id if replaced else None,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.staff_documents.add(document)
            uow.record_events(document.pull_domain_events())
            if replaced is not None:
                replaced.mark_replaced(document.id, clock=self._clock, actor_id=command.actor.user_id)
                uow.record_events(replaced.pull_domain_events())
            await uow.commit()
            return (await self._document_dtos(uow, [document]))[0]

    async def update_document(
        self, command: UpdateStaffDocumentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StaffDocumentDTO:
        async with uow:
            document = await uow.staff_documents.get(StaffDocumentId(command.document_id))
            if document is None:
                raise NotFoundError(f"Document {command.document_id} not found.")
            values = {
                key: (_clean(value) if key in ("number", "notes") else value)
                for key, value in command.changes.items()
            }
            document.update(clock=self._clock, actor_id=command.actor.user_id, **values)
            uow.record_events(document.pull_domain_events())
            await uow.commit()
            return (await self._document_dtos(uow, [document]))[0]

    async def list_documents_for_staff(
        self, staff_id: str, *, uow: TransportOpsUnitOfWork
    ) -> list[StaffDocumentDTO]:
        async with uow:
            staff = await self._get_staff(uow, staff_id)
            return await self._document_dtos(uow, await uow.staff_documents.list_for_staff(staff.id))

    async def list_expiring_documents(
        self, *, uow: TransportOpsUnitOfWork, organization_id: str | None = None
    ) -> list[StaffDocumentDTO]:
        """Current documents that are expiring or expired, soonest first — the dashboard card.
        Scope limits it to the caller's organizations; `organization_id` narrows further."""
        async with uow:
            documents = await uow.staff_documents.list_current_with_expiry()
            if organization_id is not None:
                documents = [d for d in documents if str(d.organization_id) == organization_id]
            dtos = await self._document_dtos(uow, documents)
            return [d for d in dtos if d.status in ("expiring", "expired")]

    # ---- expiry alerts (ADR-0051 §3) -------------------------------------------------------

    async def collect_due_expiry_alerts(
        self, *, uow: TransportOpsUnitOfWork
    ) -> list[DueExpiryAlertDTO]:
        """Alerts owed today, across every organization the UoW's scope reaches (the job runs
        unscoped). Nothing is marked here: the job marks each one only after its notifications
        were written, so a crash in between re-sends rather than loses an alert."""
        today = self._today()
        async with uow:
            documents = await uow.staff_documents.list_current_with_expiry()
            types = {
                str(t.id): t
                for t in await uow.staff_document_types.list_by_ids(
                    [str(d.type_id) for d in documents]
                )
            }
            due: list[_DueAlert] = []
            for document in documents:
                doc_type = types.get(str(document.type_id))
                if doc_type is None or doc_type.is_archived:
                    continue
                threshold = document.due_alert_threshold(today, doc_type.alert_lead_days)
                if threshold is not None:
                    due.append(_DueAlert(document, threshold))
            staff = await uow.staff.list_by_ids([str(d.document.staff_id) for d in due])
            by_id = {str(s.id): s for s in staff}
            alerts: list[DueExpiryAlertDTO] = []
            for item in due:
                person = by_id.get(str(item.document.staff_id))
                # Someone who has left no longer needs their licence chased.
                if person is None or person.status is TransportStaffStatus.LEFT:
                    continue
                alerts.append(
                    DueExpiryAlertDTO(
                        organization_id=str(item.document.organization_id),
                        document_id=str(item.document.id),
                        staff_id=str(person.id),
                        staff_name=person.full_name,
                        type_name=types[str(item.document.type_id)].name,
                        expires_on=item.document.expires_on,  # type: ignore[arg-type]
                        threshold_days=item.threshold_days,
                    )
                )
            return alerts

    async def mark_expiry_alerted(
        self, document_id: str, threshold_days: int, *, uow: TransportOpsUnitOfWork
    ) -> None:
        async with uow:
            document = await uow.staff_documents.get(StaffDocumentId(document_id))
            if document is None:
                return
            document.mark_alerted(threshold_days, clock=self._clock)
            uow.record_events(document.pull_domain_events())
            await uow.commit()

    # ---- helpers --------------------------------------------------------------------------

    @staticmethod
    def _ensure_unique_name(
        existing: list[tuple[str, str]], name: str, *, exclude_id: str | None, what: str
    ) -> None:
        wanted = name.strip().casefold()
        for item_id, item_name in existing:
            if item_id != exclude_id and item_name.casefold() == wanted:
                raise ConflictError(f"A {what} named {name.strip()!r} already exists.")

    @staticmethod
    async def _get_staff(uow: TransportOpsUnitOfWork, staff_id: str) -> TransportStaff:
        staff = await uow.staff.get(TransportStaffId(staff_id))
        if staff is None:
            raise NotFoundError(f"Staff member {staff_id} not found.")
        return staff

    @staticmethod
    async def _get_role(
        uow: TransportOpsUnitOfWork, role_id: str, organization_id: str
    ) -> TransportStaffRole:
        role = await uow.staff_roles.get(TransportStaffRoleId(role_id))
        if role is None or str(role.organization_id) != organization_id:
            raise NotFoundError(f"Job title {role_id} not found.")
        return role

    @staticmethod
    async def _get_document_type(
        uow: TransportOpsUnitOfWork, type_id: str, organization_id: str
    ) -> StaffDocumentType:
        doc_type = await uow.staff_document_types.get(StaffDocumentTypeId(type_id))
        if doc_type is None or str(doc_type.organization_id) != organization_id:
            raise NotFoundError(f"Document type {type_id} not found.")
        return doc_type

    async def _usable_role_id(
        self,
        uow: TransportOpsUnitOfWork,
        role_id: str | None,
        organization_id: str,
        *,
        current: TransportStaffRoleId | None = None,
    ) -> TransportStaffRoleId | None:
        """A title from the same organization. An archived title cannot be newly chosen, but a
        record already holding one keeps it when other fields are edited."""
        if not role_id:
            return None
        role = await self._get_role(uow, role_id, organization_id)
        if role.is_archived and role.id != current:
            raise DomainError(f"Job title {role.name!r} is archived.")
        return role.id

    @staticmethod
    async def _ensure_employee_ref_free(
        uow: TransportOpsUnitOfWork, organization_id: str, employee_ref: str | None
    ) -> None:
        if employee_ref is None:
            return
        if await uow.staff.get_by_employee_ref(
            organization_id=organization_id, employee_ref=employee_ref
        ):
            raise ConflictError(f"Employee reference {employee_ref!r} is already in use.")

    @staticmethod
    async def _role_names(
        uow: TransportOpsUnitOfWork, role_ids: list[TransportStaffRoleId | None]
    ) -> dict[str, str]:
        wanted = {str(r) for r in role_ids if r is not None}
        if not wanted:
            return {}
        names: dict[str, str] = {}
        for role_id in wanted:
            role = await uow.staff_roles.get(TransportStaffRoleId(role_id))
            if role is not None:
                names[role_id] = role.name
        return names

    async def _staff_dto(
        self, uow: TransportOpsUnitOfWork, staff: TransportStaff
    ) -> TransportStaffDTO:
        role_names = await self._role_names(uow, [staff.role_id])
        driver = await uow.drivers.get_by_staff_id(staff.id)
        return TransportStaffDTO(
            id=str(staff.id),
            organization_id=str(staff.organization_id),
            full_name=staff.full_name,
            phone=_str_or_none(staff.phone),
            alternate_phone=_str_or_none(staff.alternate_phone),
            role_id=_str_or_none(staff.role_id),
            role_name=role_names.get(str(staff.role_id)) if staff.role_id else None,
            employee_ref=staff.employee_ref,
            start_date=staff.start_date,
            status=staff.status.value,
            emergency_contact_name=staff.emergency_contact_name,
            emergency_contact_phone=_str_or_none(staff.emergency_contact_phone),
            notes=staff.notes,
            left_on=staff.left_on,
            driver=_driver_profile(driver),
            created_at=staff.created_at,
            updated_at=staff.updated_at,
        )

    async def _assignment_dtos(
        self, uow: TransportOpsUnitOfWork, assignments: list[VehicleStaffAssignment]
    ) -> list[VehicleStaffAssignmentDTO]:
        staff = await uow.staff.list_by_ids([str(a.staff_id) for a in assignments])
        names = {str(s.id): s.full_name for s in staff}
        role_names = await self._role_names(uow, [a.role_id for a in assignments])
        today = self._today()
        return [
            VehicleStaffAssignmentDTO(
                id=str(a.id),
                organization_id=str(a.organization_id),
                staff_id=str(a.staff_id),
                staff_name=names.get(str(a.staff_id), str(a.staff_id)),
                vehicle_id=str(a.vehicle_id),
                role_id=_str_or_none(a.role_id),
                role_name=role_names.get(str(a.role_id)) if a.role_id else None,
                route_id=_str_or_none(a.route_id),
                starts_on=a.starts_on,
                ends_on=a.ends_on,
                kind=a.kind.value,
                reason=a.reason,
                is_current=a.is_current(today),
                created_at=a.created_at,
            )
            for a in assignments
        ]

    async def _document_dtos(
        self, uow: TransportOpsUnitOfWork, documents: list[StaffDocument]
    ) -> list[StaffDocumentDTO]:
        types = {
            str(t.id): t
            for t in await uow.staff_document_types.list_by_ids(
                [str(d.type_id) for d in documents]
            )
        }
        staff = await uow.staff.list_by_ids([str(d.staff_id) for d in documents])
        names = {str(s.id): s.full_name for s in staff}
        today = self._today()
        result: list[StaffDocumentDTO] = []
        for d in documents:
            doc_type = types.get(str(d.type_id))
            lead = doc_type.alert_lead_days if doc_type else DEFAULT_ALERT_LEAD_DAYS
            result.append(
                StaffDocumentDTO(
                    id=str(d.id),
                    organization_id=str(d.organization_id),
                    staff_id=str(d.staff_id),
                    staff_name=names.get(str(d.staff_id), str(d.staff_id)),
                    type_id=str(d.type_id),
                    type_name=doc_type.name if doc_type else str(d.type_id),
                    number=d.number,
                    issued_on=d.issued_on,
                    expires_on=d.expires_on,
                    notes=d.notes,
                    status=d.status(today, lead).value,
                    days_left=d.days_left(today),
                    replaced_by_id=_str_or_none(d.replaced_by_id),
                    created_at=d.created_at,
                )
            )
        return result


__all__ = [
    "DEFAULT_ALERT_LEAD_DAYS",
    "DEFAULT_STAFF_DOCUMENT_TYPES",
    "DEFAULT_STAFF_ROLES",
    "DRIVER_ROLE_NAME",
    "TransportStaffApplicationService",
]
