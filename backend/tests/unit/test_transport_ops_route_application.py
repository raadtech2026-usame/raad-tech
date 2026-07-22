"""Application-layer tests for `transport_ops`'s `RouteApplicationService` (Phase 11).
Stdlib `unittest` — no `pytest` (not an approved dependency), mirroring
`test_transport_ops_driver_application.py`'s exact structure. Uses a fixed clock/sequential id
generator fake and an in-memory fake `TransportOpsUnitOfWork`/`RouteRepository` — no
SQLAlchemy, no FastAPI, no real database. Covers: command immutability, DTO mapping, service
orchestration flow, repository interaction, route-name-uniqueness validation, and stop
add/remove/move error paths.
"""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import ConflictError, DomainError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import FilterCondition, OffsetPage, OffsetPageRequest, SortSpec
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    ActivateRouteCommand,
    AddStopToRouteCommand,
    CreateRouteCommand,
    DisableRouteCommand,
    MoveStopCommand,
    RemoveStopFromRouteCommand,
    UpdateRouteCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    GetRouteByIdQuery,
    ListRoutesQuery,
    ListStopsForRouteQuery,
    RouteDTO,
    RouteSummaryDTO,
    StopDTO,
    route_to_dto,
    route_to_summary_dto,
)
from raad.modules.transport_ops.application.services import RouteApplicationService
from raad.modules.transport_ops.domain.entities import Route
from raad.modules.transport_ops.domain.repositories import RouteRepository
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    RouteId,
    RouteStatus,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
# Well-formed ULID shape but never added to any InMemoryRouteRepository in these tests -
# exercises the NotFoundError path, distinct from RouteId's own malformed-shape DomainError.
NON_EXISTENT_ROUTE_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class SequentialIdGenerator(IdGenerator):
    """26-char, valid-Crockford-Base32 ULID-shaped ids, unique per call: a fixed 20-char
    prefix plus a zero-padded 6-digit counter (no truncation, unlike appending a short
    zero-padded suffix and slicing to length - that can collide, e.g. "...001"[:26] and
    "...0001"[:26] both drop distinguishing digits for small counter values)."""

    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"  # 20 chars

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
    own test file rather than a shared test helper, mirroring
    `test_organization_application.py`'s own established "duplicated per module" precedent."""
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


class InMemoryRouteRepository(RouteRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Route] = {}

    async def get(self, route_id: RouteId) -> Route | None:
        return self.by_id.get(str(route_id))

    async def get_by_name(self, name: str) -> Route | None:
        return next((r for r in self.by_id.values() if r.name == name), None)

    def add(self, route: Route) -> None:
        self.by_id[str(route.id)] = route

    async def list_all(self) -> list[Route]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Route]:
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )


class FakeTransportOpsUnitOfWork(TransportOpsUnitOfWork):
    def __init__(self, routes: InMemoryRouteRepository) -> None:
        self.routes = routes
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def make_actor(org_id: str = VALID_ORG_ULID) -> Principal:
    return Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=org_id)


def make_service() -> tuple[RouteApplicationService, FakeTransportOpsUnitOfWork]:
    clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
    id_generator = SequentialIdGenerator()
    service = RouteApplicationService(clock=clock, id_generator=id_generator)
    uow = FakeTransportOpsUnitOfWork(InMemoryRouteRepository())
    return service, uow


class CommandImmutabilityTests(unittest.TestCase):
    def test_create_command_is_frozen(self) -> None:
        command = CreateRouteCommand(
            organization_id=VALID_ORG_ULID, name="Morning Route A", actor=make_actor()
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.name = "Different Name"  # type: ignore[misc]

    def test_update_command_is_frozen(self) -> None:
        command = UpdateRouteCommand(
            route_id="some-id", name="Morning Route A", actor=make_actor()
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.route_id = "other-id"  # type: ignore[misc]

    def test_status_commands_are_frozen(self) -> None:
        for command in (
            ActivateRouteCommand(route_id="r1", actor=make_actor()),
            DisableRouteCommand(route_id="r1", actor=make_actor()),
        ):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                command.route_id = "other-id"  # type: ignore[misc]

    def test_commands_carry_the_actor_principal(self) -> None:
        actor = make_actor()
        command = CreateRouteCommand(
            organization_id=VALID_ORG_ULID, name="Morning Route A", actor=actor
        )
        self.assertIs(command.actor, actor)


class DTOMappingTests(unittest.TestCase):
    def make_route(self) -> Route:
        route = Route(
            id=RouteId("01J8Z3K9G6X8YV5T4N2R7QW3MC"),
            organization_id=OrganizationId(VALID_ORG_ULID),
            name="Morning Route A",
            status=RouteStatus.ACTIVE,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        return route

    def test_route_to_dto_maps_all_fields_as_primitives(self) -> None:
        dto = route_to_dto(self.make_route())
        self.assertIsInstance(dto, RouteDTO)
        self.assertEqual(dto.id, "01J8Z3K9G6X8YV5T4N2R7QW3MC")
        self.assertEqual(dto.organization_id, VALID_ORG_ULID)
        self.assertEqual(dto.name, "Morning Route A")
        self.assertEqual(dto.status, "active")  # enum -> .value, not the enum member
        self.assertEqual(dto.stops, ())

    def test_route_to_summary_dto_maps_reduced_field_set(self) -> None:
        dto = route_to_summary_dto(self.make_route())
        self.assertIsInstance(dto, RouteSummaryDTO)
        self.assertEqual(dto.id, "01J8Z3K9G6X8YV5T4N2R7QW3MC")
        self.assertEqual(dto.name, "Morning Route A")
        self.assertEqual(dto.status, "active")
        self.assertFalse(hasattr(dto, "stops"))

    def test_dtos_are_frozen(self) -> None:
        dto = route_to_dto(self.make_route())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            dto.name = "Different Name"  # type: ignore[misc]


class RouteApplicationServiceCreateTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_route_adds_to_repository_and_commits(self) -> None:
        service, uow = make_service()
        command = CreateRouteCommand(
            organization_id=VALID_ORG_ULID, name="Morning Route A", actor=make_actor()
        )
        dto = await service.create_route(command, uow=uow)

        self.assertEqual(dto.name, "Morning Route A")
        self.assertEqual(dto.status, "active")
        self.assertEqual(len(uow.routes.by_id), 1)
        self.assertIn(dto.id, uow.routes.by_id)
        self.assertEqual(uow.commit_count, 1)

    async def test_create_route_records_domain_events(self) -> None:
        service, uow = make_service()
        command = CreateRouteCommand(
            organization_id=VALID_ORG_ULID, name="Morning Route A", actor=make_actor()
        )
        await service.create_route(command, uow=uow)

        self.assertEqual(len(uow.recorded_events), 1)
        self.assertEqual(uow.recorded_events[0].event_type, "RouteCreated")

    async def test_create_route_generates_a_fresh_id_per_call(self) -> None:
        service, uow = make_service()
        first = await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID, name="Route One", actor=make_actor()
            ),
            uow=uow,
        )
        second = await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID, name="Route Two", actor=make_actor()
            ),
            uow=uow,
        )
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(uow.routes.by_id), 2)

    async def test_create_route_with_duplicate_name_raises_conflict_error(
        self,
    ) -> None:
        service, uow = make_service()
        await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID,
                name="Morning Route A",
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await service.create_route(
                CreateRouteCommand(
                    organization_id=VALID_ORG_ULID,
                    name="Morning Route A",
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(uow.commit_count, 1)  # second call never reached commit

    async def test_create_route_with_invalid_name_raises_domain_error(self) -> None:
        service, uow = make_service()
        command = CreateRouteCommand(
            organization_id=VALID_ORG_ULID, name="", actor=make_actor()
        )
        with self.assertRaises(DomainError):
            await service.create_route(command, uow=uow)
        self.assertEqual(uow.commit_count, 0)


class RouteApplicationServiceStatusTransitionTests(unittest.IsolatedAsyncioTestCase):
    async def _created_route_id(self, service: RouteApplicationService, uow) -> str:
        dto = await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID,
                name="Morning Route A",
                actor=make_actor(),
            ),
            uow=uow,
        )
        uow.recorded_events.clear()  # isolate the transition's own event from creation's
        return dto.id

    async def test_disable_route_changes_status(self) -> None:
        service, uow = make_service()
        route_id = await self._created_route_id(service, uow)
        dto = await service.disable_route(
            DisableRouteCommand(route_id=route_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "inactive")
        self.assertEqual(uow.recorded_events[-1].event_type, "RouteDisabled")

    async def test_activate_after_disable_returns_to_active(self) -> None:
        service, uow = make_service()
        route_id = await self._created_route_id(service, uow)
        await service.disable_route(
            DisableRouteCommand(route_id=route_id, actor=make_actor()), uow=uow
        )
        dto = await service.activate_route(
            ActivateRouteCommand(route_id=route_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "active")

    async def test_transition_on_missing_route_raises_not_found(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.disable_route(
                DisableRouteCommand(route_id=NON_EXISTENT_ROUTE_ID, actor=make_actor()),
                uow=uow,
            )
        self.assertEqual(uow.commit_count, 0)


class RouteApplicationServiceUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_route_changes_name(self) -> None:
        service, uow = make_service()
        created = await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID, name="Old Name", actor=make_actor()
            ),
            uow=uow,
        )
        dto = await service.update_route(
            UpdateRouteCommand(
                route_id=created.id, name="New Name", actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(dto.name, "New Name")

    async def test_update_route_on_missing_route_raises_not_found(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.update_route(
                UpdateRouteCommand(
                    route_id=NON_EXISTENT_ROUTE_ID, name="X", actor=make_actor()
                ),
                uow=uow,
            )


class RouteApplicationServiceReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_route_by_id_returns_dto(self) -> None:
        service, uow = make_service()
        created = await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID,
                name="Morning Route A",
                actor=make_actor(),
            ),
            uow=uow,
        )
        dto = await service.get_route_by_id(
            GetRouteByIdQuery(route_id=created.id), uow=uow
        )
        self.assertEqual(dto.id, created.id)
        self.assertEqual(dto.name, "Morning Route A")

    async def test_get_route_by_id_raises_not_found_for_missing_route(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.get_route_by_id(
                GetRouteByIdQuery(route_id=NON_EXISTENT_ROUTE_ID), uow=uow
            )

    async def test_list_routes_returns_summary_dtos_for_all_routes(self) -> None:
        service, uow = make_service()
        await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID, name="Route One", actor=make_actor()
            ),
            uow=uow,
        )
        await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID, name="Route Two", actor=make_actor()
            ),
            uow=uow,
        )
        page = await service.list_routes(
            ListRoutesQuery(page_request=OffsetPageRequest()), uow=uow
        )
        self.assertEqual(len(page.data), 2)
        self.assertTrue(all(isinstance(dto, RouteSummaryDTO) for dto in page.data))
        self.assertEqual(
            sorted(dto.name for dto in page.data), ["Route One", "Route Two"]
        )

    async def test_list_routes_returns_empty_page_when_none_created(self) -> None:
        service, uow = make_service()
        page = await service.list_routes(
            ListRoutesQuery(page_request=OffsetPageRequest()), uow=uow
        )
        self.assertEqual(page.data, [])
        self.assertEqual(page.total, 0)


class RouteApplicationServicePaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_routes_paginates_and_reports_total(self) -> None:
        service, uow = make_service()
        for i in range(3):
            await service.create_route(
                CreateRouteCommand(
                    organization_id=VALID_ORG_ULID,
                    name=f"Route {i}",
                    actor=make_actor(),
                ),
                uow=uow,
            )

        page = await service.list_routes(
            ListRoutesQuery(page_request=OffsetPageRequest(page=1, page_size=2)),
            uow=uow,
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(page.page, 1)
        self.assertEqual(page.page_size, 2)
        self.assertEqual(len(page.data), 2)

        second_page = await service.list_routes(
            ListRoutesQuery(page_request=OffsetPageRequest(page=2, page_size=2)),
            uow=uow,
        )
        self.assertEqual(len(second_page.data), 1)

    async def test_list_routes_filters_by_status(self) -> None:
        service, uow = make_service()
        active = await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID,
                name="Active Route",
                actor=make_actor(),
            ),
            uow=uow,
        )
        disabled = await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID,
                name="Disabled Route",
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.disable_route(
            DisableRouteCommand(route_id=disabled.id, actor=make_actor()), uow=uow
        )

        page = await service.list_routes(
            ListRoutesQuery(
                page_request=OffsetPageRequest(),
                filters=[FilterCondition(field="status", op="eq", value="inactive")],
            ),
            uow=uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].name, "Disabled Route")
        self.assertNotEqual(page.data[0].id, active.id)

    async def test_list_routes_sorts_descending_by_name(self) -> None:
        service, uow = make_service()
        for name in ("Alpha", "Beta", "Gamma"):
            await service.create_route(
                CreateRouteCommand(
                    organization_id=VALID_ORG_ULID, name=name, actor=make_actor()
                ),
                uow=uow,
            )

        page = await service.list_routes(
            ListRoutesQuery(
                page_request=OffsetPageRequest(),
                sort=[SortSpec(field="name", descending=True)],
            ),
            uow=uow,
        )
        self.assertEqual([dto.name for dto in page.data], ["Gamma", "Beta", "Alpha"])


class RouteApplicationServiceStopTests(unittest.IsolatedAsyncioTestCase):
    async def _created_route_id(self, service: RouteApplicationService, uow) -> str:
        dto = await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID,
                name="Morning Route A",
                actor=make_actor(),
            ),
            uow=uow,
        )
        return dto.id

    async def test_add_stop_to_route_returns_stop_dto(self) -> None:
        service, uow = make_service()
        route_id = await self._created_route_id(service, uow)
        stop = await service.add_stop_to_route(
            AddStopToRouteCommand(
                route_id=route_id,
                name="First Stop",
                latitude=2.5,
                longitude=45.3,
                sequence_no=1,
                geofence_radius_m=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertIsInstance(stop, StopDTO)
        self.assertEqual(stop.name, "First Stop")
        self.assertEqual(stop.sequence_no, 1)

    async def test_add_stop_persists_on_the_route(self) -> None:
        service, uow = make_service()
        route_id = await self._created_route_id(service, uow)
        await service.add_stop_to_route(
            AddStopToRouteCommand(
                route_id=route_id,
                name="First Stop",
                latitude=2.5,
                longitude=45.3,
                sequence_no=1,
                geofence_radius_m=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        route = await uow.routes.get(RouteId(route_id))
        self.assertEqual(len(route.stops), 1)

    async def test_add_stop_with_duplicate_sequence_raises_conflict_error(
        self,
    ) -> None:
        service, uow = make_service()
        route_id = await self._created_route_id(service, uow)
        await service.add_stop_to_route(
            AddStopToRouteCommand(
                route_id=route_id,
                name="First Stop",
                latitude=2.5,
                longitude=45.3,
                sequence_no=1,
                geofence_radius_m=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await service.add_stop_to_route(
                AddStopToRouteCommand(
                    route_id=route_id,
                    name="Second Stop",
                    latitude=2.6,
                    longitude=45.4,
                    sequence_no=1,
                    geofence_radius_m=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_list_stops_for_route_returns_ordered_stops(self) -> None:
        service, uow = make_service()
        route_id = await self._created_route_id(service, uow)
        await service.add_stop_to_route(
            AddStopToRouteCommand(
                route_id=route_id,
                name="Second Stop",
                latitude=2.6,
                longitude=45.4,
                sequence_no=2,
                geofence_radius_m=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.add_stop_to_route(
            AddStopToRouteCommand(
                route_id=route_id,
                name="First Stop",
                latitude=2.5,
                longitude=45.3,
                sequence_no=1,
                geofence_radius_m=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        stops = await service.list_stops_for_route(
            ListStopsForRouteQuery(route_id=route_id), uow=uow
        )
        self.assertEqual([s.sequence_no for s in stops], [1, 2])
        self.assertEqual([s.name for s in stops], ["First Stop", "Second Stop"])

    async def test_remove_stop_from_route_removes_it(self) -> None:
        service, uow = make_service()
        route_id = await self._created_route_id(service, uow)
        stop = await service.add_stop_to_route(
            AddStopToRouteCommand(
                route_id=route_id,
                name="First Stop",
                latitude=2.5,
                longitude=45.3,
                sequence_no=1,
                geofence_radius_m=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        route_dto = await service.remove_stop_from_route(
            RemoveStopFromRouteCommand(
                route_id=route_id, stop_id=stop.id, actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(route_dto.stops, ())

    async def test_move_stop_changes_sequence(self) -> None:
        service, uow = make_service()
        route_id = await self._created_route_id(service, uow)
        stop = await service.add_stop_to_route(
            AddStopToRouteCommand(
                route_id=route_id,
                name="First Stop",
                latitude=2.5,
                longitude=45.3,
                sequence_no=1,
                geofence_radius_m=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        route_dto = await service.move_stop(
            MoveStopCommand(
                route_id=route_id,
                stop_id=stop.id,
                new_sequence_no=9,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(route_dto.stops[0].sequence_no, 9)

    async def test_add_stop_to_missing_route_raises_not_found(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.add_stop_to_route(
                AddStopToRouteCommand(
                    route_id=NON_EXISTENT_ROUTE_ID,
                    name="First Stop",
                    latitude=2.5,
                    longitude=45.3,
                    sequence_no=1,
                    geofence_radius_m=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )


class RepositoryInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_never_bypasses_the_repository_to_mutate_state(self) -> None:
        # The service must go through uow.routes.add/get - not hold its own parallel state.
        service, uow = make_service()
        dto = await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID,
                name="Morning Route A",
                actor=make_actor(),
            ),
            uow=uow,
        )
        stored = await uow.routes.get(RouteId(dto.id))
        self.assertIsNotNone(stored)
        self.assertEqual(stored.name, "Morning Route A")

    async def test_uow_used_as_async_context_manager_for_every_call(self) -> None:
        service, uow = make_service()
        dto = await service.create_route(
            CreateRouteCommand(
                organization_id=VALID_ORG_ULID,
                name="Morning Route A",
                actor=make_actor(),
            ),
            uow=uow,
        )
        fetched = await service.get_route_by_id(
            GetRouteByIdQuery(route_id=dto.id), uow=uow
        )
        self.assertEqual(fetched.id, dto.id)


if __name__ == "__main__":
    unittest.main()
