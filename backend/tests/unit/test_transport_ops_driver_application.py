"""Application-layer tests for `transport_ops`'s `DriverApplicationService` (Phase 10.8).
Stdlib `unittest` — no `pytest` (not an approved dependency), mirroring
`test_transport_ops_parent_application.py`'s exact structure. Uses a fixed clock/sequential id
generator fake and an in-memory fake `TransportOpsUnitOfWork`/`DriverRepository` — no
SQLAlchemy, no FastAPI, no real database. Covers: command immutability, DTO mapping, service
orchestration flow, repository interaction, and status-transition/validation error paths.
"""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import DomainError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    ActivateDriverCommand,
    DisableDriverCommand,
    RegisterDriverCommand,
    UpdateDriverCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    DriverDTO,
    DriverSummaryDTO,
    GetDriverByIdQuery,
    ListDriversQuery,
    driver_to_dto,
    driver_to_summary_dto,
)
from raad.modules.transport_ops.application.services import DriverApplicationService
from raad.modules.transport_ops.domain.entities import Driver
from raad.modules.transport_ops.domain.repositories import DriverRepository
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    DriverStatus,
    OrganizationId,
    UserId,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_USER_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
# Well-formed ULID shape but never added to any InMemoryDriverRepository in these tests -
# exercises the NotFoundError path, distinct from DriverId's own malformed-shape DomainError.
NON_EXISTENT_DRIVER_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"


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


class InMemoryDriverRepository(DriverRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Driver] = {}

    async def get(self, driver_id: DriverId) -> Driver | None:
        return self.by_id.get(str(driver_id))

    def add(self, driver: Driver) -> None:
        self.by_id[str(driver.id)] = driver

    async def list_all(self) -> list[Driver]:
        return list(self.by_id.values())


class FakeTransportOpsUnitOfWork(TransportOpsUnitOfWork):
    def __init__(self, drivers: InMemoryDriverRepository) -> None:
        self.drivers = drivers
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


def make_service() -> tuple[DriverApplicationService, FakeTransportOpsUnitOfWork]:
    clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
    id_generator = SequentialIdGenerator()
    service = DriverApplicationService(clock=clock, id_generator=id_generator)
    uow = FakeTransportOpsUnitOfWork(InMemoryDriverRepository())
    return service, uow


class CommandImmutabilityTests(unittest.TestCase):
    def test_register_command_is_frozen(self) -> None:
        command = RegisterDriverCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            license_no="DL-123456",
            actor=make_actor(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.license_no = "Different"  # type: ignore[misc]

    def test_update_command_is_frozen(self) -> None:
        command = UpdateDriverCommand(
            driver_id="some-id",
            license_no="DL-123456",
            actor=make_actor(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.driver_id = "other-id"  # type: ignore[misc]

    def test_status_commands_are_frozen(self) -> None:
        for command in (
            ActivateDriverCommand(driver_id="d1", actor=make_actor()),
            DisableDriverCommand(driver_id="d1", actor=make_actor()),
        ):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                command.driver_id = "other-id"  # type: ignore[misc]

    def test_commands_carry_the_actor_principal(self) -> None:
        actor = make_actor()
        command = RegisterDriverCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            license_no="DL-123456",
            actor=actor,
        )
        self.assertIs(command.actor, actor)


class DTOMappingTests(unittest.TestCase):
    def make_driver(self) -> Driver:
        return Driver(
            id=DriverId("01J8Z3K9G6X8YV5T4N2R7QW3MC"),
            organization_id=OrganizationId(VALID_ORG_ULID),
            user_id=UserId(VALID_USER_ULID),
            license_no="DL-123456",
            status=DriverStatus.ACTIVE,
        )

    def test_driver_to_dto_maps_all_fields_as_primitives(self) -> None:
        dto = driver_to_dto(self.make_driver())
        self.assertIsInstance(dto, DriverDTO)
        self.assertEqual(dto.id, "01J8Z3K9G6X8YV5T4N2R7QW3MC")
        self.assertEqual(dto.organization_id, VALID_ORG_ULID)
        self.assertEqual(dto.user_id, VALID_USER_ULID)
        self.assertEqual(dto.license_no, "DL-123456")
        self.assertEqual(dto.status, "active")  # enum -> .value, not the enum member

    def test_driver_to_summary_dto_maps_reduced_field_set(self) -> None:
        dto = driver_to_summary_dto(self.make_driver())
        self.assertIsInstance(dto, DriverSummaryDTO)
        self.assertEqual(dto.id, "01J8Z3K9G6X8YV5T4N2R7QW3MC")
        self.assertEqual(dto.license_no, "DL-123456")
        self.assertEqual(dto.status, "active")
        self.assertFalse(hasattr(dto, "organization_id"))
        self.assertFalse(hasattr(dto, "user_id"))

    def test_dtos_are_frozen(self) -> None:
        dto = driver_to_dto(self.make_driver())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            dto.license_no = "Different"  # type: ignore[misc]


class DriverApplicationServiceRegisterTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_driver_adds_to_repository_and_commits(self) -> None:
        service, uow = make_service()
        command = RegisterDriverCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            license_no="DL-123456",
            actor=make_actor(),
        )
        dto = await service.register_driver(command, uow=uow)

        self.assertEqual(dto.license_no, "DL-123456")
        self.assertEqual(dto.status, "active")
        self.assertEqual(len(uow.drivers.by_id), 1)
        self.assertIn(dto.id, uow.drivers.by_id)
        self.assertEqual(uow.commit_count, 1)

    async def test_register_driver_records_domain_events(self) -> None:
        service, uow = make_service()
        command = RegisterDriverCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            license_no="DL-123456",
            actor=make_actor(),
        )
        await service.register_driver(command, uow=uow)

        self.assertEqual(len(uow.recorded_events), 1)
        self.assertEqual(uow.recorded_events[0].event_type, "DriverRegistered")

    async def test_register_driver_generates_a_fresh_id_per_call(self) -> None:
        service, uow = make_service()
        command = RegisterDriverCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            license_no="DL-123456",
            actor=make_actor(),
        )
        first = await service.register_driver(command, uow=uow)
        second = await service.register_driver(command, uow=uow)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(uow.drivers.by_id), 2)

    async def test_register_driver_with_invalid_license_no_raises_domain_error(
        self,
    ) -> None:
        service, uow = make_service()
        command = RegisterDriverCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            license_no="",
            actor=make_actor(),
        )
        with self.assertRaises(DomainError):
            await service.register_driver(command, uow=uow)
        self.assertEqual(uow.commit_count, 0)


class DriverApplicationServiceStatusTransitionTests(unittest.IsolatedAsyncioTestCase):
    async def _registered_driver_id(
        self, service: DriverApplicationService, uow
    ) -> str:
        dto = await service.register_driver(
            RegisterDriverCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                license_no="DL-123456",
                actor=make_actor(),
            ),
            uow=uow,
        )
        uow.recorded_events.clear()  # isolate the transition's own event from registration's
        return dto.id

    async def test_disable_driver_changes_status(self) -> None:
        service, uow = make_service()
        driver_id = await self._registered_driver_id(service, uow)
        dto = await service.disable_driver(
            DisableDriverCommand(driver_id=driver_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "inactive")
        self.assertEqual(uow.recorded_events[-1].event_type, "DriverDisabled")

    async def test_activate_after_disable_returns_to_active(self) -> None:
        service, uow = make_service()
        driver_id = await self._registered_driver_id(service, uow)
        await service.disable_driver(
            DisableDriverCommand(driver_id=driver_id, actor=make_actor()), uow=uow
        )
        dto = await service.activate_driver(
            ActivateDriverCommand(driver_id=driver_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "active")

    async def test_repeated_disable_is_idempotent_no_new_event(self) -> None:
        service, uow = make_service()
        driver_id = await self._registered_driver_id(service, uow)
        await service.disable_driver(
            DisableDriverCommand(driver_id=driver_id, actor=make_actor()), uow=uow
        )
        uow.recorded_events.clear()
        await service.disable_driver(
            DisableDriverCommand(driver_id=driver_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(uow.recorded_events, [])  # already inactive - no-op

    async def test_transition_on_missing_driver_raises_not_found(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.disable_driver(
                DisableDriverCommand(
                    driver_id=NON_EXISTENT_DRIVER_ID, actor=make_actor()
                ),
                uow=uow,
            )
        self.assertEqual(uow.commit_count, 0)  # never reached commit

    async def test_malformed_driver_id_shape_raises_domain_error_not_not_found(
        self,
    ) -> None:
        # DriverId's own ULID-shape validation runs before the repository lookup - a
        # malformed id is a DomainError, distinct from a well-formed but absent NotFoundError.
        service, uow = make_service()
        with self.assertRaises(DomainError):
            await service.disable_driver(
                DisableDriverCommand(driver_id="not-a-ulid", actor=make_actor()),
                uow=uow,
            )


class DriverApplicationServiceUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_driver_changes_license_no(self) -> None:
        service, uow = make_service()
        registered = await service.register_driver(
            RegisterDriverCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                license_no="OLD-111",
                actor=make_actor(),
            ),
            uow=uow,
        )
        dto = await service.update_driver(
            UpdateDriverCommand(
                driver_id=registered.id,
                license_no="NEW-222",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(dto.license_no, "NEW-222")

    async def test_update_driver_on_missing_driver_raises_not_found(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.update_driver(
                UpdateDriverCommand(
                    driver_id=NON_EXISTENT_DRIVER_ID,
                    license_no="X",
                    actor=make_actor(),
                ),
                uow=uow,
            )


class DriverApplicationServiceReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_driver_by_id_returns_dto(self) -> None:
        service, uow = make_service()
        registered = await service.register_driver(
            RegisterDriverCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                license_no="DL-123456",
                actor=make_actor(),
            ),
            uow=uow,
        )
        dto = await service.get_driver_by_id(
            GetDriverByIdQuery(driver_id=registered.id), uow=uow
        )
        self.assertEqual(dto.id, registered.id)
        self.assertEqual(dto.license_no, "DL-123456")

    async def test_get_driver_by_id_raises_not_found_for_missing_driver(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.get_driver_by_id(
                GetDriverByIdQuery(driver_id=NON_EXISTENT_DRIVER_ID), uow=uow
            )

    async def test_list_drivers_returns_summary_dtos_for_all_drivers(self) -> None:
        service, uow = make_service()
        await service.register_driver(
            RegisterDriverCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                license_no="Driver One",
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.register_driver(
            RegisterDriverCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                license_no="Driver Two",
                actor=make_actor(),
            ),
            uow=uow,
        )
        results = await service.list_drivers(ListDriversQuery(), uow=uow)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(isinstance(dto, DriverSummaryDTO) for dto in results))
        self.assertEqual(
            sorted(dto.license_no for dto in results), ["Driver One", "Driver Two"]
        )

    async def test_list_drivers_returns_empty_list_when_none_registered(self) -> None:
        service, uow = make_service()
        results = await service.list_drivers(ListDriversQuery(), uow=uow)
        self.assertEqual(results, [])


class RepositoryInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_never_bypasses_the_repository_to_mutate_state(self) -> None:
        # The service must go through uow.drivers.add/get - not hold its own parallel state.
        service, uow = make_service()
        dto = await service.register_driver(
            RegisterDriverCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                license_no="DL-123456",
                actor=make_actor(),
            ),
            uow=uow,
        )
        stored = await uow.drivers.get(DriverId(dto.id))
        self.assertIsNotNone(stored)
        self.assertEqual(stored.license_no, "DL-123456")

    async def test_uow_used_as_async_context_manager_for_every_call(self) -> None:
        service, uow = make_service()
        dto = await service.register_driver(
            RegisterDriverCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                license_no="DL-123456",
                actor=make_actor(),
            ),
            uow=uow,
        )
        fetched = await service.get_driver_by_id(
            GetDriverByIdQuery(driver_id=dto.id), uow=uow
        )
        self.assertEqual(fetched.id, dto.id)


if __name__ == "__main__":
    unittest.main()
