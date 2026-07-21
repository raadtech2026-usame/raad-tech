"""Domain-only tests for `transport_ops`'s `Parent` aggregate (Phase 10.6). Stdlib
`unittest` — no `pytest` (not an approved dependency), matching
`test_transport_ops_student_domain.py`'s established precedent exactly. Covers: value-object
validation (`ParentId`/`UserId`/`PhoneNumber`), construction invariants, state transitions
(idempotent no-ops), `update_details`, repository-interface shape, and domain-event emission.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.time.clock import Clock
from raad.modules.transport_ops.domain.entities import Parent
from raad.modules.transport_ops.domain.repositories import ParentRepository
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    ParentId,
    ParentStatus,
    PhoneNumber,
    UserId,
)

VALID_PARENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MC"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_USER_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def make_parent(**overrides) -> Parent:
    defaults = dict(
        id=ParentId(VALID_PARENT_ULID),
        organization_id=OrganizationId(VALID_ORG_ULID),
        user_id=UserId(VALID_USER_ULID),
        full_name="Fatima Hassan",
        phone=None,
        status=ParentStatus.ACTIVE,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Parent(**defaults)


class ParentIdValidationTests(unittest.TestCase):
    def test_valid_ulid_constructs(self) -> None:
        parent_id = ParentId(VALID_PARENT_ULID)
        self.assertEqual(str(parent_id), VALID_PARENT_ULID)

    def test_too_short_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            ParentId("TOOSHORT")

    def test_lowercase_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            ParentId(VALID_PARENT_ULID.lower())

    def test_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            ParentId("")

    def test_invalid_crockford_characters_raise_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            ParentId("0" * 25 + "I")

    def test_equality_is_by_value(self) -> None:
        self.assertEqual(ParentId(VALID_PARENT_ULID), ParentId(VALID_PARENT_ULID))


class UserIdValidationTests(unittest.TestCase):
    def test_non_empty_string_constructs(self) -> None:
        user_id = UserId("any-opaque-value")
        self.assertEqual(str(user_id), "any-opaque-value")

    def test_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            UserId("")

    def test_does_not_re_validate_ulid_shape(self) -> None:
        # Cross-module reference to iam.User: opaque non-empty string only, per
        # .claude/rules/database.md #3 - this must NOT reject a non-ULID-shaped id.
        UserId("not-a-ulid-at-all")


class PhoneNumberValidationTests(unittest.TestCase):
    def test_valid_e164_constructs(self) -> None:
        phone = PhoneNumber("+252700000000")
        self.assertEqual(str(phone), "+252700000000")

    def test_missing_plus_prefix_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            PhoneNumber("252700000000")

    def test_leading_zero_after_plus_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            PhoneNumber("+0700000000")

    def test_non_digit_characters_raise_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            PhoneNumber("+25270000abc")

    def test_over_max_length_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            PhoneNumber("+" + "1" * 32)


class ParentConstructionValidationTests(unittest.TestCase):
    def test_valid_parent_constructs(self) -> None:
        parent = make_parent()
        self.assertEqual(parent.full_name, "Fatima Hassan")
        self.assertEqual(parent.status, ParentStatus.ACTIVE)
        self.assertIsNone(parent.phone)

    def test_empty_full_name_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            make_parent(full_name="")

    def test_full_name_over_200_chars_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            make_parent(full_name="A" * 201)

    def test_full_name_exactly_200_chars_is_valid(self) -> None:
        parent = make_parent(full_name="A" * 200)
        self.assertEqual(len(parent.full_name), 200)

    def test_phone_none_is_valid(self) -> None:
        parent = make_parent(phone=None)
        self.assertIsNone(parent.phone)

    def test_phone_with_valid_value_is_valid(self) -> None:
        parent = make_parent(phone=PhoneNumber("+252700000000"))
        self.assertEqual(str(parent.phone), "+252700000000")

    def test_equality_is_by_id_not_by_field_values(self) -> None:
        a = make_parent(full_name="Fatima Hassan")
        b = make_parent(full_name="Different Name")  # same id, different name
        self.assertEqual(a, b)

    def test_inequality_across_different_ids(self) -> None:
        other_id = "01J8Z3K9G6X8YV5T4N2R7QW3MF"
        a = make_parent()
        b = make_parent(id=ParentId(other_id))
        self.assertNotEqual(a, b)

    def test_hash_matches_id_hash(self) -> None:
        parent = make_parent()
        self.assertEqual(hash(parent), hash(parent.id))


class ParentRegisterTests(unittest.TestCase):
    def test_register_starts_active(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        parent = Parent.register(
            id=ParentId(VALID_PARENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            user_id=UserId(VALID_USER_ULID),
            full_name="Fatima Hassan",
            clock=clock,
        )
        self.assertEqual(parent.status, ParentStatus.ACTIVE)

    def test_register_records_parent_registered_event(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        parent = Parent.register(
            id=ParentId(VALID_PARENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            user_id=UserId(VALID_USER_ULID),
            full_name="Fatima Hassan",
            phone=PhoneNumber("+252700000000"),
            clock=clock,
            actor_id="actor-1",
        )
        events = parent.pull_domain_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "ParentRegistered")
        self.assertEqual(event.aggregate_type, "Parent")
        self.assertEqual(event.aggregate_id, VALID_PARENT_ULID)
        self.assertEqual(event.org_id, VALID_ORG_ULID)
        self.assertEqual(event.occurred_at, clock.now())
        self.assertEqual(
            event.payload,
            {
                "user_id": VALID_USER_ULID,
                "full_name": "Fatima Hassan",
                "phone": "+252700000000",
                "actor_id": "actor-1",
            },
        )

    def test_register_with_invalid_full_name_raises_before_recording_event(
        self,
    ) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        with self.assertRaises(DomainError):
            Parent.register(
                id=ParentId(VALID_PARENT_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                user_id=UserId(VALID_USER_ULID),
                full_name="",
                clock=clock,
            )

    def test_register_without_phone_is_valid(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        parent = Parent.register(
            id=ParentId(VALID_PARENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            user_id=UserId(VALID_USER_ULID),
            full_name="Fatima Hassan",
            clock=clock,
        )
        self.assertIsNone(parent.phone)
        self.assertIsNone(parent.pull_domain_events()[0].payload["phone"])


class ParentStatusTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))

    def test_disable_changes_status_and_records_event(self) -> None:
        parent = make_parent(status=ParentStatus.ACTIVE)
        parent.disable(clock=self.clock, actor_id="admin-1")
        self.assertEqual(parent.status, ParentStatus.INACTIVE)
        events = parent.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "ParentDisabled")
        self.assertEqual(events[0].payload, {"actor_id": "admin-1"})

    def test_activate_changes_status_and_records_event(self) -> None:
        parent = make_parent(status=ParentStatus.INACTIVE)
        parent.activate(clock=self.clock)
        self.assertEqual(parent.status, ParentStatus.ACTIVE)
        events = parent.pull_domain_events()
        self.assertEqual(events[0].event_type, "ParentActivated")

    def test_disable_when_already_inactive_is_idempotent_no_op(self) -> None:
        parent = make_parent(status=ParentStatus.INACTIVE)
        parent.disable(clock=self.clock)
        self.assertEqual(parent.status, ParentStatus.INACTIVE)
        self.assertEqual(parent.pull_domain_events(), [])

    def test_activate_when_already_active_is_idempotent_no_op(self) -> None:
        parent = make_parent(status=ParentStatus.ACTIVE)
        parent.activate(clock=self.clock)
        self.assertEqual(parent.pull_domain_events(), [])

    def test_disable_then_activate_round_trip(self) -> None:
        parent = make_parent(status=ParentStatus.ACTIVE)
        parent.disable(clock=self.clock)
        self.assertEqual(parent.status, ParentStatus.INACTIVE)
        parent.activate(clock=self.clock)
        self.assertEqual(parent.status, ParentStatus.ACTIVE)

    def test_clock_is_never_called_internally_besides_via_parameter(self) -> None:
        parent = make_parent(status=ParentStatus.ACTIVE)
        parent.disable(clock=self.clock)
        event = parent.pull_domain_events()[0]
        self.assertEqual(event.occurred_at, self.clock.now())


class ParentUpdateDetailsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))

    def test_update_details_changes_fields_and_records_event(self) -> None:
        parent = make_parent(full_name="Old Name", phone=None)
        parent.update_details(
            full_name="New Name",
            phone=PhoneNumber("+252700000000"),
            clock=self.clock,
            actor_id="admin-1",
        )
        self.assertEqual(parent.full_name, "New Name")
        self.assertEqual(str(parent.phone), "+252700000000")
        events = parent.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "ParentDetailsUpdated")
        self.assertEqual(
            events[0].payload,
            {
                "full_name": "New Name",
                "phone": "+252700000000",
                "actor_id": "admin-1",
            },
        )

    def test_update_details_with_identical_values_is_idempotent_no_op(self) -> None:
        phone = PhoneNumber("+252700000000")
        parent = make_parent(full_name="Same Name", phone=phone)
        parent.update_details(full_name="Same Name", phone=phone, clock=self.clock)
        self.assertEqual(parent.pull_domain_events(), [])

    def test_update_details_rejects_empty_full_name(self) -> None:
        parent = make_parent()
        with self.assertRaises(DomainError):
            parent.update_details(full_name="", phone=None, clock=self.clock)

    def test_update_details_rejects_full_name_over_200_chars(self) -> None:
        parent = make_parent()
        with self.assertRaises(DomainError):
            parent.update_details(full_name="A" * 201, phone=None, clock=self.clock)

    def test_update_details_can_clear_phone_to_none(self) -> None:
        parent = make_parent(phone=PhoneNumber("+252700000000"))
        parent.update_details(full_name="Fatima Hassan", phone=None, clock=self.clock)
        self.assertIsNone(parent.phone)


class DomainEventBufferingTests(unittest.TestCase):
    def test_pull_domain_events_drains_the_buffer(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        parent = Parent.register(
            id=ParentId(VALID_PARENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            user_id=UserId(VALID_USER_ULID),
            full_name="Fatima Hassan",
            clock=clock,
        )
        first_pull = parent.pull_domain_events()
        second_pull = parent.pull_domain_events()
        self.assertEqual(len(first_pull), 1)
        self.assertEqual(second_pull, [])

    def test_multiple_mutations_buffer_multiple_events_in_order(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        parent = make_parent(status=ParentStatus.ACTIVE)
        parent.disable(clock=clock)
        parent.activate(clock=clock)
        events = parent.pull_domain_events()
        self.assertEqual(
            [e.event_type for e in events], ["ParentDisabled", "ParentActivated"]
        )


class ParentRepositoryInterfaceTests(unittest.TestCase):
    def test_cannot_instantiate_abstract_repository_directly(self) -> None:
        with self.assertRaises(TypeError):
            ParentRepository()  # abstract - no concrete get/add/list_all

    def test_concrete_implementation_satisfying_the_interface_can_be_instantiated(
        self,
    ) -> None:
        class InMemoryParentRepository(ParentRepository):
            def __init__(self) -> None:
                self._parents: dict[str, Parent] = {}

            async def get(self, parent_id: ParentId) -> Parent | None:
                return self._parents.get(str(parent_id))

            async def get_by_user_id(self, user_id) -> Parent | None:
                return next(
                    (
                        p
                        for p in self._parents.values()
                        if str(p.user_id) == str(user_id)
                    ),
                    None,
                )

            def add(self, parent: Parent) -> None:
                self._parents[str(parent.id)] = parent

            async def list_all(self) -> list[Parent]:
                return list(self._parents.values())

        repo = InMemoryParentRepository()
        parent = make_parent()
        repo.add(parent)
        self.assertIs(repo._parents[str(parent.id)], parent)

    def test_incomplete_implementation_missing_add_cannot_be_instantiated(self) -> None:
        class IncompleteRepository(ParentRepository):
            async def get(self, parent_id: ParentId) -> Parent | None:
                return None

        with self.assertRaises(TypeError):
            IncompleteRepository()


if __name__ == "__main__":
    unittest.main()
