"""Domain-only tests for `transport_ops`'s `StudentParent` aggregate (Phase 10.7). Stdlib
`unittest` — no `pytest` (not an approved dependency), matching
`test_transport_ops_student_domain.py`/`test_transport_ops_parent_domain.py`'s established
precedent exactly. Covers: construction/validation (`relationship` length), the `link` factory
(including cross-organization rejection — a pure domain invariant, `domain/entities.py`'s
`StudentParent.link` docstring), `unlink`, domain-event emission, equality/hash by composite
key, and repository-interface shape.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.time.clock import Clock
from raad.modules.transport_ops.domain.entities import StudentParent
from raad.modules.transport_ops.domain.repositories import StudentParentRepository
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    ParentId,
    StudentId,
)

VALID_STUDENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MC"
VALID_PARENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
OTHER_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MF"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def make_link(**overrides) -> StudentParent:
    defaults = dict(
        student_id=StudentId(VALID_STUDENT_ULID),
        parent_id=ParentId(VALID_PARENT_ULID),
        relationship="mother",
        is_primary=False,
    )
    defaults.update(overrides)
    return StudentParent(**defaults)


class StudentParentConstructionValidationTests(unittest.TestCase):
    def test_valid_link_constructs(self) -> None:
        link = make_link()
        self.assertEqual(link.relationship, "mother")
        self.assertFalse(link.is_primary)

    def test_relationship_none_is_valid(self) -> None:
        link = make_link(relationship=None)
        self.assertIsNone(link.relationship)

    def test_relationship_exactly_40_chars_is_valid(self) -> None:
        link = make_link(relationship="A" * 40)
        self.assertEqual(len(link.relationship), 40)

    def test_relationship_over_40_chars_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            make_link(relationship="A" * 41)

    def test_is_primary_true_is_valid(self) -> None:
        link = make_link(is_primary=True)
        self.assertTrue(link.is_primary)

    def test_equality_is_by_composite_key(self) -> None:
        a = make_link(relationship="mother")
        b = make_link(
            relationship="father"
        )  # same (student_id, parent_id), different label
        self.assertEqual(a, b)

    def test_inequality_across_different_student_id(self) -> None:
        other_student_id = "01J8Z3K9G6X8YV5T4N2R7QW3MG"
        a = make_link()
        b = make_link(student_id=StudentId(other_student_id))
        self.assertNotEqual(a, b)

    def test_inequality_across_different_parent_id(self) -> None:
        other_parent_id = "01J8Z3K9G6X8YV5T4N2R7QW3MH"
        a = make_link()
        b = make_link(parent_id=ParentId(other_parent_id))
        self.assertNotEqual(a, b)

    def test_hash_matches_composite_key_hash(self) -> None:
        link = make_link()
        self.assertEqual(hash(link), hash((link.student_id, link.parent_id)))


class StudentParentLinkTests(unittest.TestCase):
    def test_link_creates_active_association(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        link = StudentParent.link(
            student_id=StudentId(VALID_STUDENT_ULID),
            student_organization_id=OrganizationId(VALID_ORG_ULID),
            parent_id=ParentId(VALID_PARENT_ULID),
            parent_organization_id=OrganizationId(VALID_ORG_ULID),
            relationship="guardian",
            is_primary=True,
            clock=clock,
            actor_id="admin-1",
        )
        self.assertEqual(link.relationship, "guardian")
        self.assertTrue(link.is_primary)

    def test_link_records_student_parent_linked_event(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        link = StudentParent.link(
            student_id=StudentId(VALID_STUDENT_ULID),
            student_organization_id=OrganizationId(VALID_ORG_ULID),
            parent_id=ParentId(VALID_PARENT_ULID),
            parent_organization_id=OrganizationId(VALID_ORG_ULID),
            relationship="mother",
            is_primary=True,
            clock=clock,
            actor_id="admin-1",
        )
        events = link.pull_domain_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "StudentParentLinked")
        self.assertEqual(event.aggregate_type, "StudentParent")
        self.assertEqual(event.aggregate_id, VALID_STUDENT_ULID)
        self.assertEqual(event.org_id, VALID_ORG_ULID)
        self.assertEqual(event.occurred_at, clock.now())
        self.assertEqual(
            event.payload,
            {
                "student_id": VALID_STUDENT_ULID,
                "parent_id": VALID_PARENT_ULID,
                "relationship": "mother",
                "is_primary": True,
                "actor_id": "admin-1",
            },
        )

    def test_link_defaults_relationship_none_and_is_primary_false(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        link = StudentParent.link(
            student_id=StudentId(VALID_STUDENT_ULID),
            student_organization_id=OrganizationId(VALID_ORG_ULID),
            parent_id=ParentId(VALID_PARENT_ULID),
            parent_organization_id=OrganizationId(VALID_ORG_ULID),
            clock=clock,
        )
        self.assertIsNone(link.relationship)
        self.assertFalse(link.is_primary)

    def test_link_rejects_cross_organization_association(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        with self.assertRaises(DomainError):
            StudentParent.link(
                student_id=StudentId(VALID_STUDENT_ULID),
                student_organization_id=OrganizationId(VALID_ORG_ULID),
                parent_id=ParentId(VALID_PARENT_ULID),
                parent_organization_id=OrganizationId(OTHER_ORG_ULID),
                clock=clock,
            )

    def test_cross_organization_rejection_records_no_event(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        try:
            StudentParent.link(
                student_id=StudentId(VALID_STUDENT_ULID),
                student_organization_id=OrganizationId(VALID_ORG_ULID),
                parent_id=ParentId(VALID_PARENT_ULID),
                parent_organization_id=OrganizationId(OTHER_ORG_ULID),
                clock=clock,
            )
            self.fail("expected DomainError")
        except DomainError:
            pass
        # No aggregate instance was ever returned to buffer/leak an event from.

    def test_link_with_invalid_relationship_raises_before_recording_event(
        self,
    ) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        with self.assertRaises(DomainError):
            StudentParent.link(
                student_id=StudentId(VALID_STUDENT_ULID),
                student_organization_id=OrganizationId(VALID_ORG_ULID),
                parent_id=ParentId(VALID_PARENT_ULID),
                parent_organization_id=OrganizationId(VALID_ORG_ULID),
                relationship="A" * 41,
                clock=clock,
            )


class StudentParentUnlinkTests(unittest.TestCase):
    def test_unlink_records_student_parent_unlinked_event(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        link = make_link()
        link.unlink(
            organization_id=OrganizationId(VALID_ORG_ULID),
            clock=clock,
            actor_id="admin-1",
        )
        events = link.pull_domain_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "StudentParentUnlinked")
        self.assertEqual(event.aggregate_type, "StudentParent")
        self.assertEqual(event.aggregate_id, VALID_STUDENT_ULID)
        self.assertEqual(event.org_id, VALID_ORG_ULID)
        self.assertEqual(
            event.payload,
            {
                "student_id": VALID_STUDENT_ULID,
                "parent_id": VALID_PARENT_ULID,
                "actor_id": "admin-1",
            },
        )

    def test_unlink_does_not_mutate_relationship_or_is_primary(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        link = make_link(relationship="mother", is_primary=True)
        link.unlink(organization_id=OrganizationId(VALID_ORG_ULID), clock=clock)
        # Unlinking is a deletion at the persistence layer, not a status field mutation -
        # the in-memory aggregate's own fields are untouched.
        self.assertEqual(link.relationship, "mother")
        self.assertTrue(link.is_primary)


class DomainEventBufferingTests(unittest.TestCase):
    def test_pull_domain_events_drains_the_buffer(self) -> None:
        clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
        link = StudentParent.link(
            student_id=StudentId(VALID_STUDENT_ULID),
            student_organization_id=OrganizationId(VALID_ORG_ULID),
            parent_id=ParentId(VALID_PARENT_ULID),
            parent_organization_id=OrganizationId(VALID_ORG_ULID),
            clock=clock,
        )
        first_pull = link.pull_domain_events()
        second_pull = link.pull_domain_events()
        self.assertEqual(len(first_pull), 1)
        self.assertEqual(second_pull, [])


class StudentParentRepositoryInterfaceTests(unittest.TestCase):
    def test_cannot_instantiate_abstract_repository_directly(self) -> None:
        with self.assertRaises(TypeError):
            StudentParentRepository()

    def test_concrete_implementation_satisfying_the_interface_can_be_instantiated(
        self,
    ) -> None:
        class InMemoryStudentParentRepository(StudentParentRepository):
            def __init__(self) -> None:
                self._links: dict[tuple[str, str], StudentParent] = {}

            async def get(self, student_id, parent_id):
                return self._links.get((str(student_id), str(parent_id)))

            def add(self, link: StudentParent) -> None:
                self._links[(str(link.student_id), str(link.parent_id))] = link

            async def remove(self, link: StudentParent) -> None:
                self._links.pop((str(link.student_id), str(link.parent_id)), None)

            async def list_by_student(self, student_id):
                return [
                    link
                    for link in self._links.values()
                    if str(link.student_id) == str(student_id)
                ]

            async def list_by_parent(self, parent_id):
                return [
                    link
                    for link in self._links.values()
                    if str(link.parent_id) == str(parent_id)
                ]

        repo = InMemoryStudentParentRepository()
        link = make_link()
        repo.add(link)
        self.assertIs(repo._links[(str(link.student_id), str(link.parent_id))], link)

    def test_incomplete_implementation_missing_remove_cannot_be_instantiated(
        self,
    ) -> None:
        class IncompleteRepository(StudentParentRepository):
            async def get(self, student_id, parent_id):
                return None

            def add(self, link: StudentParent) -> None:
                pass

        with self.assertRaises(TypeError):
            IncompleteRepository()


if __name__ == "__main__":
    unittest.main()
