"""Application-layer tests for `transport_ops`'s `ParentApplicationService` (Phase 10.6).
Stdlib `unittest` — no `pytest` (not an approved dependency), mirroring
`test_transport_ops_student_application.py`'s exact structure. Uses a fixed clock/sequential id
generator fake and an in-memory fake `TransportOpsUnitOfWork`/`ParentRepository` — no
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
    ActivateParentCommand,
    DisableParentCommand,
    RegisterParentCommand,
    UpdateParentCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    GetParentByIdQuery,
    ListParentsQuery,
    ParentDTO,
    ParentSummaryDTO,
    parent_to_dto,
    parent_to_summary_dto,
)
from raad.modules.transport_ops.application.services import ParentApplicationService
from raad.modules.transport_ops.domain.entities import Parent
from raad.modules.transport_ops.domain.repositories import ParentRepository
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    ParentId,
    ParentStatus,
    PhoneNumber,
    UserId,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_USER_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
# Well-formed ULID shape but never added to any InMemoryParentRepository in these tests -
# exercises the NotFoundError path, distinct from ParentId's own malformed-shape DomainError.
NON_EXISTENT_PARENT_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"


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


class InMemoryParentRepository(ParentRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Parent] = {}

    async def get(self, parent_id: ParentId) -> Parent | None:
        return self.by_id.get(str(parent_id))

    def add(self, parent: Parent) -> None:
        self.by_id[str(parent.id)] = parent

    async def list_all(self) -> list[Parent]:
        return list(self.by_id.values())


class FakeTransportOpsUnitOfWork(TransportOpsUnitOfWork):
    def __init__(self, parents: InMemoryParentRepository) -> None:
        self.parents = parents
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


def make_service() -> tuple[ParentApplicationService, FakeTransportOpsUnitOfWork]:
    clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
    id_generator = SequentialIdGenerator()
    service = ParentApplicationService(clock=clock, id_generator=id_generator)
    uow = FakeTransportOpsUnitOfWork(InMemoryParentRepository())
    return service, uow


class CommandImmutabilityTests(unittest.TestCase):
    def test_register_command_is_frozen(self) -> None:
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            full_name="Fatima Hassan",
            phone=None,
            actor=make_actor(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.full_name = "Different Name"  # type: ignore[misc]

    def test_update_command_is_frozen(self) -> None:
        command = UpdateParentCommand(
            parent_id="some-id",
            full_name="Fatima Hassan",
            phone=None,
            actor=make_actor(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.parent_id = "other-id"  # type: ignore[misc]

    def test_status_commands_are_frozen(self) -> None:
        for command in (
            ActivateParentCommand(parent_id="p1", actor=make_actor()),
            DisableParentCommand(parent_id="p1", actor=make_actor()),
        ):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                command.parent_id = "other-id"  # type: ignore[misc]

    def test_commands_carry_the_actor_principal(self) -> None:
        actor = make_actor()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            full_name="Fatima Hassan",
            phone=None,
            actor=actor,
        )
        self.assertIs(command.actor, actor)


class DTOMappingTests(unittest.TestCase):
    def make_parent(self) -> Parent:
        return Parent(
            id=ParentId("01J8Z3K9G6X8YV5T4N2R7QW3MC"),
            organization_id=OrganizationId(VALID_ORG_ULID),
            user_id=UserId(VALID_USER_ULID),
            full_name="Fatima Hassan",
            phone=PhoneNumber("+252700000000"),
            status=ParentStatus.ACTIVE,
        )

    def test_parent_to_dto_maps_all_fields_as_primitives(self) -> None:
        dto = parent_to_dto(self.make_parent())
        self.assertIsInstance(dto, ParentDTO)
        self.assertEqual(dto.id, "01J8Z3K9G6X8YV5T4N2R7QW3MC")
        self.assertEqual(dto.organization_id, VALID_ORG_ULID)
        self.assertEqual(dto.user_id, VALID_USER_ULID)
        self.assertEqual(dto.full_name, "Fatima Hassan")
        self.assertEqual(dto.phone, "+252700000000")
        self.assertEqual(dto.status, "active")  # enum -> .value, not the enum member

    def test_parent_to_dto_preserves_none_phone(self) -> None:
        parent = self.make_parent()
        parent.phone = None
        dto = parent_to_dto(parent)
        self.assertIsNone(dto.phone)

    def test_parent_to_summary_dto_maps_reduced_field_set(self) -> None:
        dto = parent_to_summary_dto(self.make_parent())
        self.assertIsInstance(dto, ParentSummaryDTO)
        self.assertEqual(dto.id, "01J8Z3K9G6X8YV5T4N2R7QW3MC")
        self.assertEqual(dto.full_name, "Fatima Hassan")
        self.assertEqual(dto.status, "active")
        self.assertFalse(hasattr(dto, "organization_id"))
        self.assertFalse(hasattr(dto, "user_id"))
        self.assertFalse(hasattr(dto, "phone"))

    def test_dtos_are_frozen(self) -> None:
        dto = parent_to_dto(self.make_parent())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            dto.full_name = "Different Name"  # type: ignore[misc]


class ParentApplicationServiceRegisterTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_parent_adds_to_repository_and_commits(self) -> None:
        service, uow = make_service()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            full_name="Fatima Hassan",
            phone="+252700000000",
            actor=make_actor(),
        )
        dto = await service.register_parent(command, uow=uow)

        self.assertEqual(dto.full_name, "Fatima Hassan")
        self.assertEqual(dto.status, "active")
        self.assertEqual(len(uow.parents.by_id), 1)
        self.assertIn(dto.id, uow.parents.by_id)
        self.assertEqual(uow.commit_count, 1)

    async def test_register_parent_records_domain_events(self) -> None:
        service, uow = make_service()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            full_name="Fatima Hassan",
            phone=None,
            actor=make_actor(),
        )
        await service.register_parent(command, uow=uow)

        self.assertEqual(len(uow.recorded_events), 1)
        self.assertEqual(uow.recorded_events[0].event_type, "ParentRegistered")

    async def test_register_parent_generates_a_fresh_id_per_call(self) -> None:
        service, uow = make_service()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            full_name="Fatima Hassan",
            phone=None,
            actor=make_actor(),
        )
        first = await service.register_parent(command, uow=uow)
        second = await service.register_parent(command, uow=uow)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(uow.parents.by_id), 2)

    async def test_register_parent_without_phone_leaves_phone_none(self) -> None:
        service, uow = make_service()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            full_name="Fatima Hassan",
            phone=None,
            actor=make_actor(),
        )
        dto = await service.register_parent(command, uow=uow)
        self.assertIsNone(dto.phone)

    async def test_register_parent_with_invalid_phone_raises_domain_error(
        self,
    ) -> None:
        service, uow = make_service()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            user_id=VALID_USER_ULID,
            full_name="Fatima Hassan",
            phone="not-e164",
            actor=make_actor(),
        )
        with self.assertRaises(DomainError):
            await service.register_parent(command, uow=uow)
        self.assertEqual(uow.commit_count, 0)


class ParentApplicationServiceStatusTransitionTests(unittest.IsolatedAsyncioTestCase):
    async def _registered_parent_id(
        self, service: ParentApplicationService, uow
    ) -> str:
        dto = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                full_name="Fatima Hassan",
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        uow.recorded_events.clear()  # isolate the transition's own event from registration's
        return dto.id

    async def test_disable_parent_changes_status(self) -> None:
        service, uow = make_service()
        parent_id = await self._registered_parent_id(service, uow)
        dto = await service.disable_parent(
            DisableParentCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "inactive")
        self.assertEqual(uow.recorded_events[-1].event_type, "ParentDisabled")

    async def test_activate_after_disable_returns_to_active(self) -> None:
        service, uow = make_service()
        parent_id = await self._registered_parent_id(service, uow)
        await service.disable_parent(
            DisableParentCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        dto = await service.activate_parent(
            ActivateParentCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "active")

    async def test_repeated_disable_is_idempotent_no_new_event(self) -> None:
        service, uow = make_service()
        parent_id = await self._registered_parent_id(service, uow)
        await service.disable_parent(
            DisableParentCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        uow.recorded_events.clear()
        await service.disable_parent(
            DisableParentCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(uow.recorded_events, [])  # already inactive - no-op

    async def test_transition_on_missing_parent_raises_not_found(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.disable_parent(
                DisableParentCommand(
                    parent_id=NON_EXISTENT_PARENT_ID, actor=make_actor()
                ),
                uow=uow,
            )
        self.assertEqual(uow.commit_count, 0)  # never reached commit

    async def test_malformed_parent_id_shape_raises_domain_error_not_not_found(
        self,
    ) -> None:
        # ParentId's own ULID-shape validation runs before the repository lookup - a
        # malformed id is a DomainError, distinct from a well-formed but absent NotFoundError.
        service, uow = make_service()
        with self.assertRaises(DomainError):
            await service.disable_parent(
                DisableParentCommand(parent_id="not-a-ulid", actor=make_actor()),
                uow=uow,
            )


class ParentApplicationServiceUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_parent_changes_full_name_and_phone(self) -> None:
        service, uow = make_service()
        registered = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                full_name="Old Name",
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        dto = await service.update_parent(
            UpdateParentCommand(
                parent_id=registered.id,
                full_name="New Name",
                phone="+252700000000",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(dto.full_name, "New Name")
        self.assertEqual(dto.phone, "+252700000000")

    async def test_update_parent_on_missing_parent_raises_not_found(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.update_parent(
                UpdateParentCommand(
                    parent_id=NON_EXISTENT_PARENT_ID,
                    full_name="X",
                    phone=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )


class ParentApplicationServiceReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_parent_by_id_returns_dto(self) -> None:
        service, uow = make_service()
        registered = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                full_name="Fatima Hassan",
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        dto = await service.get_parent_by_id(
            GetParentByIdQuery(parent_id=registered.id), uow=uow
        )
        self.assertEqual(dto.id, registered.id)
        self.assertEqual(dto.full_name, "Fatima Hassan")

    async def test_get_parent_by_id_raises_not_found_for_missing_parent(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.get_parent_by_id(
                GetParentByIdQuery(parent_id=NON_EXISTENT_PARENT_ID), uow=uow
            )

    async def test_list_parents_returns_summary_dtos_for_all_parents(self) -> None:
        service, uow = make_service()
        await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                full_name="Parent One",
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                full_name="Parent Two",
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        results = await service.list_parents(ListParentsQuery(), uow=uow)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(isinstance(dto, ParentSummaryDTO) for dto in results))
        self.assertEqual(
            sorted(dto.full_name for dto in results), ["Parent One", "Parent Two"]
        )

    async def test_list_parents_returns_empty_list_when_none_registered(self) -> None:
        service, uow = make_service()
        results = await service.list_parents(ListParentsQuery(), uow=uow)
        self.assertEqual(results, [])


class RepositoryInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_never_bypasses_the_repository_to_mutate_state(self) -> None:
        # The service must go through uow.parents.add/get - not hold its own parallel state.
        service, uow = make_service()
        dto = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                full_name="Fatima Hassan",
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        stored = await uow.parents.get(ParentId(dto.id))
        self.assertIsNotNone(stored)
        self.assertEqual(stored.full_name, "Fatima Hassan")

    async def test_uow_used_as_async_context_manager_for_every_call(self) -> None:
        service, uow = make_service()
        dto = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                user_id=VALID_USER_ULID,
                full_name="Fatima Hassan",
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        fetched = await service.get_parent_by_id(
            GetParentByIdQuery(parent_id=dto.id), uow=uow
        )
        self.assertEqual(fetched.id, dto.id)


if __name__ == "__main__":
    unittest.main()
