"""Application-layer tests for `organization`'s `OrganizationApplicationService`/
`RegionApplicationService`. Stdlib `unittest` — no `pytest`, matching established precedent.
In-memory fake `OrganizationUnitOfWork`/repositories. Covers: DTO mapping, service
orchestration, validator behavior (region-must-exist, parent-org-must-exist, duplicate region
name rejection), and status-transition regression protection.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import ConflictError, DomainError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.organization.application.commands import (
    ActivateRegionCommand,
    CreateRegionCommand,
    DeactivateOrganizationCommand,
    DeactivateRegionCommand,
    OnboardOrganizationCommand,
    ReactivateOrganizationCommand,
    RegisterOrganizationCommand,
    SuspendOrganizationCommand,
    UpdateOrganizationApproachingDistanceCommand,
    UpdateOrganizationGeofenceCommand,
)
from raad.modules.organization.application.ports import (
    IamProvisioningPort,
    OrganizationUnitOfWork,
)
from raad.modules.organization.application.queries import (
    GetOrganizationByIdQuery,
    GetRegionByIdQuery,
    ListOrganizationsQuery,
    ListRegionsQuery,
)
from raad.modules.organization.application.services import (
    OrganizationApplicationService,
    RegionApplicationService,
)
from raad.modules.organization.domain.entities import Organization, Region
from raad.modules.organization.domain.repositories import (
    OrganizationRepository,
    RegionRepository,
    ScopeAssignmentRepository,
)
from raad.modules.organization.domain.value_objects import (
    OrgType,
    OrganizationId,
    RegionId,
)

VALID_REGION_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
NON_EXISTENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class SequentialIdGenerator(IdGenerator):
    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


def _field_text(item: object, field_name: str) -> str:
    value = getattr(item, field_name)
    value = getattr(value, "value", value)
    return "" if value is None else str(value)


def _matches_filter(item: object, condition: FilterCondition) -> bool:
    text = _field_text(item, condition.field)
    if condition.op == "eq":
        return text == condition.value
    if condition.op == "in":
        return text in {part.strip() for part in condition.value.split(",")}
    if condition.op == "gte":
        return text >= condition.value
    if condition.op == "lte":
        return text <= condition.value
    if condition.op == "gt":
        return text > condition.value
    if condition.op == "lt":
        return text < condition.value
    return True


def _paginate_in_memory(
    items: list,
    page_request: OffsetPageRequest,
    *,
    sort: list[SortSpec],
    filters: list[FilterCondition],
    search: str | None,
    search_field: str = "name",
) -> OffsetPage:
    """Shared in-memory equivalent of `SqlAlchemyRepositoryBase.list_page` (`core/db/
    repository.py`), for fake repositories that can't run real SQL — duplicated per module's
    own test file rather than a shared test helper, mirroring this codebase's own established
    "duplicated per module" precedent (e.g. domain-event buffering)."""
    for condition in filters:
        items = [item for item in items if _matches_filter(item, condition)]
    if search:
        items = [
            item
            for item in items
            if search.lower() in _field_text(item, search_field).lower()
        ]
    for spec in reversed(sort):
        items = sorted(
            items, key=lambda item: _field_text(item, spec.field), reverse=spec.descending
        )
    if not sort:
        items = sorted(items, key=lambda item: str(item.id))
    total = len(items)
    start = page_request.offset
    end = start + page_request.page_size
    return OffsetPage(
        data=items[start:end], total=total, page=page_request.page, page_size=page_request.page_size
    )


class InMemoryOrganizationRepository(OrganizationRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Organization] = {}

    async def get(self, organization_id: OrganizationId) -> Organization | None:
        return self.by_id.get(str(organization_id))

    def add(self, organization: Organization) -> None:
        self.by_id[str(organization.id)] = organization

    async def list_ids_by_region_ids(
        self, region_ids: frozenset[str]
    ) -> frozenset[str]:
        return frozenset(
            org_id
            for org_id, org in self.by_id.items()
            if str(org.region_id) in region_ids
        )

    async def list_all(self) -> list[Organization]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Organization]:
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )

    async def count_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for org in self.by_id.values():
            counts[org.status.value] = counts.get(org.status.value, 0) + 1
        return counts

    async def count_created_since(self, since) -> int:
        return sum(1 for org in self.by_id.values() if org.created_at >= since)


class InMemoryScopeAssignmentRepository(ScopeAssignmentRepository):
    def __init__(self) -> None:
        self.region_assignments: set[tuple[str, str]] = set()
        self.support_assignments: set[tuple[str, str]] = set()

    async def list_assigned_region_ids(self, user_id: str) -> frozenset[str]:
        return frozenset(
            region_id for uid, region_id in self.region_assignments if uid == user_id
        )

    async def list_assigned_organization_ids(self, user_id: str) -> frozenset[str]:
        return frozenset(
            org_id for uid, org_id in self.support_assignments if uid == user_id
        )

    async def grant_region(
        self, user_id: str, region_id: str, *, granted_by: str | None
    ) -> None:
        self.region_assignments.add((user_id, region_id))

    async def revoke_region(self, user_id: str, region_id: str) -> None:
        self.region_assignments.discard((user_id, region_id))

    async def grant_organization(
        self, user_id: str, organization_id: str, *, granted_by: str | None
    ) -> None:
        self.support_assignments.add((user_id, organization_id))

    async def revoke_organization(self, user_id: str, organization_id: str) -> None:
        self.support_assignments.discard((user_id, organization_id))


class InMemoryRegionRepository(RegionRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Region] = {}

    async def get(self, region_id: RegionId) -> Region | None:
        return self.by_id.get(str(region_id))

    async def get_by_name(self, name: str) -> Region | None:
        for region in self.by_id.values():
            if region.name == name:
                return region
        return None

    def add(self, region: Region) -> None:
        self.by_id[str(region.id)] = region

    async def list_all(self) -> list[Region]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Region]:
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )


class FakeOrganizationUnitOfWork(OrganizationUnitOfWork):
    def __init__(
        self,
        organizations: InMemoryOrganizationRepository,
        regions: InMemoryRegionRepository,
        scope_assignments: InMemoryScopeAssignmentRepository | None = None,
    ) -> None:
        self.organizations = organizations
        self.regions = regions
        self.scope_assignments = scope_assignments or InMemoryScopeAssignmentRepository()
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def make_actor() -> Principal:
    return Principal(user_id="admin-1", role=Role.FOUNDER, org_id=None)


VALID_ADMIN_USER_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MF"
FAKE_ADMIN_TEMPORARY_PASSWORD = "Fake-Temp-Pw9!"


class FakeIamProvisioningPort(IamProvisioningPort):
    """ADR-0017: stands in for the real `IamUserProvisioningAdapter` — see
    `test_transport_ops_parent_application.py`'s identical fake (ADR-0003) for the full
    rationale. Records every call for assertions."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_user_with_temporary_password(
        self,
        *,
        organization_id: str,
        role: Role,
        email: str | None,
        phone: str | None,
        full_name: str,
        actor: Principal,
    ) -> tuple[str, str]:
        self.calls.append(
            {
                "organization_id": organization_id,
                "role": role,
                "email": email,
                "phone": phone,
                "full_name": full_name,
                "actor": actor,
            }
        )
        return VALID_ADMIN_USER_ULID, FAKE_ADMIN_TEMPORARY_PASSWORD


def make_services() -> tuple[
    OrganizationApplicationService,
    RegionApplicationService,
    FakeOrganizationUnitOfWork,
    FakeIamProvisioningPort,
]:
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    id_generator = SequentialIdGenerator()
    iam_provisioning = FakeIamProvisioningPort()
    org_service = OrganizationApplicationService(
        clock=clock, id_generator=id_generator, iam_provisioning=iam_provisioning
    )
    region_service = RegionApplicationService(clock=clock, id_generator=id_generator)
    uow = FakeOrganizationUnitOfWork(
        InMemoryOrganizationRepository(), InMemoryRegionRepository()
    )
    return org_service, region_service, uow, iam_provisioning


async def _seed_region(
    region_service: RegionApplicationService, uow, name="East Africa"
) -> str:
    dto = await region_service.create_region(
        CreateRegionCommand(name=name, geographic_scope=None, actor=make_actor()),
        uow=uow,
    )
    uow.recorded_events.clear()
    return dto.id


class OnboardOrganizationTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0017: `onboard_organization` — Organization creation and Org Admin provisioning as
    one guided workflow."""

    async def test_onboard_creates_organization_and_provisions_admin(self) -> None:
        org_service, region_service, uow, iam_provisioning = make_services()
        region_id = await _seed_region(region_service, uow)

        organization, admin_user_id, temporary_password = await org_service.onboard_organization(
            OnboardOrganizationCommand(
                name="Sunrise School",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                parent_org_id=None,
                admin_full_name="Amina Warsame",
                admin_email="amina@sunrise.example.com",
                admin_phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(organization.status, "active")
        self.assertEqual(admin_user_id, VALID_ADMIN_USER_ULID)
        self.assertEqual(temporary_password, FAKE_ADMIN_TEMPORARY_PASSWORD)
        # 1 commit from `_seed_region` above + 1 from the Organization itself (the iam call is
        # a second, independent Unit of Work this fake doesn't share commit_count with).
        self.assertEqual(uow.commit_count, 2)

    async def test_onboard_calls_iam_provisioning_with_role_org_admin_and_new_org_id(
        self,
    ) -> None:
        org_service, region_service, uow, iam_provisioning = make_services()
        region_id = await _seed_region(region_service, uow)
        actor = make_actor()

        organization, _admin_user_id, _temporary_password = await org_service.onboard_organization(
            OnboardOrganizationCommand(
                name="Sunrise School",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                parent_org_id=None,
                admin_full_name="Amina Warsame",
                admin_email="amina@sunrise.example.com",
                admin_phone=None,
                actor=actor,
            ),
            uow=uow,
        )

        self.assertEqual(len(iam_provisioning.calls), 1)
        call = iam_provisioning.calls[0]
        self.assertEqual(call["organization_id"], organization.id)
        self.assertEqual(call["role"], Role.ORG_ADMIN)
        self.assertEqual(call["email"], "amina@sunrise.example.com")
        self.assertEqual(call["full_name"], "Amina Warsame")
        self.assertIs(call["actor"], actor)

    async def test_onboard_requires_an_existing_region(self) -> None:
        org_service, _region_service, uow, iam_provisioning = make_services()
        with self.assertRaises(NotFoundError):
            await org_service.onboard_organization(
                OnboardOrganizationCommand(
                    name="Sunrise School",
                    org_type=OrgType.SCHOOL,
                    region_id=NON_EXISTENT_ULID,
                    parent_org_id=None,
                    admin_full_name="Amina Warsame",
                    admin_email="amina@sunrise.example.com",
                    admin_phone=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(uow.commit_count, 0)
        # A missing region fails before the Organization ever commits - iam is never called.
        self.assertEqual(iam_provisioning.calls, [])


class RegisterOrganizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_requires_an_existing_region(self) -> None:
        """Regression: `organizations.region_id` is an in-context FK (Database Design §4.2) -
        the application layer must pre-check it (surfacing NotFoundError) rather than letting
        an unchecked reference through."""
        org_service, _region_service, uow, _iam_provisioning = make_services()
        with self.assertRaises(NotFoundError):
            await org_service.register_organization(
                RegisterOrganizationCommand(
                    name="Sunrise School",
                    org_type=OrgType.SCHOOL,
                    region_id=NON_EXISTENT_ULID,
                    parent_org_id=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(uow.commit_count, 0)

    async def test_register_with_valid_region_succeeds(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        region_id = await _seed_region(region_service, uow)

        dto = await org_service.register_organization(
            RegisterOrganizationCommand(
                name="Sunrise School",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                parent_org_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(dto.status, "active")
        self.assertEqual(uow.recorded_events[0].event_type, "OrganizationRegistered")

    async def test_register_with_nonexistent_parent_org_raises_not_found(self) -> None:
        """Regression: parent_org_id hierarchy - the parent must actually exist (Database
        Design §4.2's self-referencing FK)."""
        org_service, region_service, uow, _iam_provisioning = make_services()
        region_id = await _seed_region(region_service, uow)

        with self.assertRaises(NotFoundError):
            await org_service.register_organization(
                RegisterOrganizationCommand(
                    name="Sub Campus",
                    org_type=OrgType.SCHOOL,
                    region_id=region_id,
                    parent_org_id=NON_EXISTENT_ULID,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_register_sub_organization_with_valid_parent_succeeds(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        region_id = await _seed_region(region_service, uow)
        parent_dto = await org_service.register_organization(
            RegisterOrganizationCommand(
                name="Parent Org",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                parent_org_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )

        child_dto = await org_service.register_organization(
            RegisterOrganizationCommand(
                name="Sub Campus",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                parent_org_id=parent_dto.id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(child_dto.parent_org_id, parent_dto.id)


class OrganizationStatusTransitionApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def _registered_org_id(self, org_service, region_service, uow) -> str:
        region_id = await _seed_region(region_service, uow)
        dto = await org_service.register_organization(
            RegisterOrganizationCommand(
                name="Sunrise School",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                parent_org_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        uow.recorded_events.clear()
        return dto.id

    async def test_suspend_then_reactivate(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        org_id = await self._registered_org_id(org_service, region_service, uow)

        suspended = await org_service.suspend_organization(
            SuspendOrganizationCommand(organization_id=org_id, actor=make_actor()),
            uow=uow,
        )
        self.assertEqual(suspended.status, "suspended")

        reactivated = await org_service.reactivate_organization(
            ReactivateOrganizationCommand(organization_id=org_id, actor=make_actor()),
            uow=uow,
        )
        self.assertEqual(reactivated.status, "active")

    async def test_deactivate_organization(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        org_id = await self._registered_org_id(org_service, region_service, uow)
        dto = await org_service.deactivate_organization(
            DeactivateOrganizationCommand(organization_id=org_id, actor=make_actor()),
            uow=uow,
        )
        self.assertEqual(dto.status, "inactive")

    async def test_transition_on_missing_organization_raises_not_found(self) -> None:
        org_service, _region_service, uow, _iam_provisioning = make_services()
        with self.assertRaises(NotFoundError):
            await org_service.suspend_organization(
                SuspendOrganizationCommand(
                    organization_id=NON_EXISTENT_ULID, actor=make_actor()
                ),
                uow=uow,
            )

    async def test_get_organization_by_id_returns_dto(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        org_id = await self._registered_org_id(org_service, region_service, uow)
        dto = await org_service.get_organization_by_id(
            GetOrganizationByIdQuery(organization_id=org_id), uow=uow
        )
        self.assertEqual(dto.id, org_id)


class UpdateOrganizationGeofenceApplicationTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0014: `OrganizationApplicationService.update_organization_geofence` — reachable at
    the application layer only, no approved HTTP route yet (see `UpdateOrganizationGeofenceCommand`'s
    own docstring). A newly-registered organization has no geofence configured until this is
    called (`OrganizationDTO.latitude`/`longitude`/`geofence_radius_m` all `None`)."""

    async def _registered_org_id(self, org_service, region_service, uow) -> str:
        region_id = await _seed_region(region_service, uow)
        dto = await org_service.register_organization(
            RegisterOrganizationCommand(
                name="Sunrise School",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                parent_org_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        uow.recorded_events.clear()
        return dto.id

    async def test_newly_registered_organization_has_no_geofence(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        org_id = await self._registered_org_id(org_service, region_service, uow)
        dto = await org_service.get_organization_by_id(
            GetOrganizationByIdQuery(organization_id=org_id), uow=uow
        )
        self.assertIsNone(dto.latitude)
        self.assertIsNone(dto.longitude)
        self.assertIsNone(dto.geofence_radius_m)

    async def test_update_organization_geofence_sets_all_three_fields(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        org_id = await self._registered_org_id(org_service, region_service, uow)

        dto = await org_service.update_organization_geofence(
            UpdateOrganizationGeofenceCommand(
                organization_id=org_id,
                latitude=1.234567,
                longitude=36.789012,
                radius_m=300,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(dto.latitude, 1.234567)
        self.assertEqual(dto.longitude, 36.789012)
        self.assertEqual(dto.geofence_radius_m, 300)
        self.assertEqual(uow.recorded_events[0].event_type, "OrganizationGeofenceUpdated")

    async def test_update_organization_geofence_on_missing_organization_raises_not_found(
        self,
    ) -> None:
        org_service, _region_service, uow, _iam_provisioning = make_services()
        with self.assertRaises(NotFoundError):
            await org_service.update_organization_geofence(
                UpdateOrganizationGeofenceCommand(
                    organization_id=NON_EXISTENT_ULID,
                    latitude=1.0,
                    longitude=1.0,
                    radius_m=200,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_update_organization_geofence_rejects_invalid_radius(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        org_id = await self._registered_org_id(org_service, region_service, uow)
        with self.assertRaises(DomainError):
            await org_service.update_organization_geofence(
                UpdateOrganizationGeofenceCommand(
                    organization_id=org_id,
                    latitude=1.0,
                    longitude=1.0,
                    radius_m=0,
                    actor=make_actor(),
                ),
                uow=uow,
            )


class UpdateOrganizationApproachingDistanceApplicationTests(
    unittest.IsolatedAsyncioTestCase
):
    """ADR-0014 amendment: `OrganizationApplicationService.
    update_organization_approaching_distance` — reachable at the application layer only, no
    approved HTTP route yet. A newly-registered organization defaults to 300m."""

    async def _registered_org_id(self, org_service, region_service, uow) -> str:
        region_id = await _seed_region(region_service, uow)
        dto = await org_service.register_organization(
            RegisterOrganizationCommand(
                name="Sunrise School",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                parent_org_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        uow.recorded_events.clear()
        return dto.id

    async def test_newly_registered_organization_defaults_to_300_meters(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        org_id = await self._registered_org_id(org_service, region_service, uow)
        dto = await org_service.get_organization_by_id(
            GetOrganizationByIdQuery(organization_id=org_id), uow=uow
        )
        self.assertEqual(dto.approaching_distance_m, 300)

    async def test_update_sets_the_new_value(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        org_id = await self._registered_org_id(org_service, region_service, uow)

        dto = await org_service.update_organization_approaching_distance(
            UpdateOrganizationApproachingDistanceCommand(
                organization_id=org_id,
                approaching_distance_m=250,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(dto.approaching_distance_m, 250)
        self.assertEqual(
            uow.recorded_events[0].event_type, "OrganizationApproachingDistanceUpdated"
        )

    async def test_update_on_missing_organization_raises_not_found(self) -> None:
        org_service, _region_service, uow, _iam_provisioning = make_services()
        with self.assertRaises(NotFoundError):
            await org_service.update_organization_approaching_distance(
                UpdateOrganizationApproachingDistanceCommand(
                    organization_id=NON_EXISTENT_ULID,
                    approaching_distance_m=250,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_update_rejects_a_non_positive_value(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        org_id = await self._registered_org_id(org_service, region_service, uow)
        with self.assertRaises(DomainError):
            await org_service.update_organization_approaching_distance(
                UpdateOrganizationApproachingDistanceCommand(
                    organization_id=org_id,
                    approaching_distance_m=0,
                    actor=make_actor(),
                ),
                uow=uow,
            )


class RegionApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_region_succeeds(self) -> None:
        _org_service, region_service, uow, _iam_provisioning = make_services()
        dto = await region_service.create_region(
            CreateRegionCommand(
                name="East Africa",
                geographic_scope="Horn of Africa",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(dto.status, "active")

    async def test_duplicate_region_name_is_rejected(self) -> None:
        """Regression: Database Design §4.1's `regions.name` global-uniqueness (UX)."""
        _org_service, region_service, uow, _iam_provisioning = make_services()
        await region_service.create_region(
            CreateRegionCommand(
                name="East Africa", geographic_scope=None, actor=make_actor()
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await region_service.create_region(
                CreateRegionCommand(
                    name="East Africa", geographic_scope=None, actor=make_actor()
                ),
                uow=uow,
            )
        self.assertEqual(len(uow.regions.by_id), 1)

    async def test_activate_and_deactivate_region(self) -> None:
        _org_service, region_service, uow, _iam_provisioning = make_services()
        region_id = await _seed_region(region_service, uow)
        deactivated = await region_service.deactivate_region(
            DeactivateRegionCommand(region_id=region_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(deactivated.status, "inactive")
        activated = await region_service.activate_region(
            ActivateRegionCommand(region_id=region_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(activated.status, "active")

    async def test_get_region_by_id_raises_not_found_for_missing_region(self) -> None:
        _org_service, region_service, uow, _iam_provisioning = make_services()
        with self.assertRaises(NotFoundError):
            await region_service.get_region_by_id(
                GetRegionByIdQuery(region_id=NON_EXISTENT_ULID), uow=uow
            )


class OrganizationPaginationApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_organizations_paginates_and_reports_total(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        region_id = await _seed_region(region_service, uow)
        for i in range(3):
            await org_service.register_organization(
                RegisterOrganizationCommand(
                    name=f"School {i}",
                    org_type=OrgType.SCHOOL,
                    region_id=region_id,
                    parent_org_id=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

        page = await org_service.list_organizations(
            ListOrganizationsQuery(page_request=OffsetPageRequest(page=1, page_size=2)),
            uow=uow,
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(page.page, 1)
        self.assertEqual(page.page_size, 2)
        self.assertEqual(len(page.data), 2)

        second_page = await org_service.list_organizations(
            ListOrganizationsQuery(page_request=OffsetPageRequest(page=2, page_size=2)),
            uow=uow,
        )
        self.assertEqual(len(second_page.data), 1)

    async def test_list_organizations_filters_by_region_id(self) -> None:
        """Replaces the former `test_list_organizations_filters_by_billing_model` — ADR-0016
        removed `billing_model` (and its filter) from `Organization` entirely. `region_id`
        exercises the identical filterable-fields mechanism with a field that still exists."""
        org_service, region_service, uow, _iam_provisioning = make_services()
        region_id = await _seed_region(region_service, uow, name="East Africa")
        other_region_id = await _seed_region(region_service, uow, name="West Africa")
        await org_service.register_organization(
            RegisterOrganizationCommand(
                name="In Region",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                parent_org_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await org_service.register_organization(
            RegisterOrganizationCommand(
                name="In Other Region",
                org_type=OrgType.SCHOOL,
                region_id=other_region_id,
                parent_org_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )

        page = await org_service.list_organizations(
            ListOrganizationsQuery(
                page_request=OffsetPageRequest(),
                filters=[
                    FilterCondition(field="region_id", op="eq", value=region_id)
                ],
            ),
            uow=uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].name, "In Region")

    async def test_list_organizations_sorts_descending_by_name(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        region_id = await _seed_region(region_service, uow)
        for name in ("Alpha", "Beta", "Gamma"):
            await org_service.register_organization(
                RegisterOrganizationCommand(
                    name=name,
                    org_type=OrgType.SCHOOL,
                    region_id=region_id,
                    parent_org_id=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

        page = await org_service.list_organizations(
            ListOrganizationsQuery(
                page_request=OffsetPageRequest(),
                sort=[SortSpec(field="name", descending=True)],
            ),
            uow=uow,
        )
        self.assertEqual([o.name for o in page.data], ["Gamma", "Beta", "Alpha"])

    async def test_list_regions_paginates(self) -> None:
        _org_service, region_service, uow, _iam_provisioning = make_services()
        for name in ("East Africa", "West Africa"):
            await region_service.create_region(
                CreateRegionCommand(name=name, geographic_scope=None, actor=make_actor()),
                uow=uow,
            )

        page = await region_service.list_regions(
            ListRegionsQuery(page_request=OffsetPageRequest(page=1, page_size=1)),
            uow=uow,
        )
        self.assertEqual(page.total, 2)
        self.assertEqual(len(page.data), 1)


class OrganizationStatsApplicationTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0020: `get_organization_stats`, backing `platform_audit.PlatformStatsApplicationService`."""

    async def test_reports_total_and_status_breakdown(self) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        region_id = await _seed_region(region_service, uow)
        for name in ("Alpha", "Beta"):
            await org_service.register_organization(
                RegisterOrganizationCommand(
                    name=name,
                    org_type=OrgType.SCHOOL,
                    region_id=region_id,
                    parent_org_id=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )
        suspended_dto = await org_service.register_organization(
            RegisterOrganizationCommand(
                name="Gamma",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                parent_org_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await org_service.suspend_organization(
            SuspendOrganizationCommand(
                organization_id=suspended_dto.id, actor=make_actor()
            ),
            uow=uow,
        )

        stats = await org_service.get_organization_stats(
            since_today=datetime(2026, 1, 1, tzinfo=timezone.utc), uow=uow
        )

        self.assertEqual(stats.total, 3)
        self.assertEqual(stats.by_status, {"active": 2, "suspended": 1})

    async def test_created_today_only_counts_organizations_on_or_after_the_boundary(
        self,
    ) -> None:
        org_service, region_service, uow, _iam_provisioning = make_services()
        region_id = await _seed_region(region_service, uow)
        await org_service.register_organization(
            RegisterOrganizationCommand(
                name="Alpha",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                parent_org_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )

        # make_services()'s FixedClock is 2026-01-01 — a "today" boundary strictly after that
        # excludes it.
        stats_before_boundary = await org_service.get_organization_stats(
            since_today=datetime(2026, 1, 1, tzinfo=timezone.utc), uow=uow
        )
        stats_after_boundary = await org_service.get_organization_stats(
            since_today=datetime(2026, 1, 2, tzinfo=timezone.utc), uow=uow
        )

        self.assertEqual(stats_before_boundary.created_today, 1)
        self.assertEqual(stats_after_boundary.created_today, 0)


if __name__ == "__main__":
    unittest.main()
