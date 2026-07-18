"""Domain-only tests for `transport_ops`'s `Driver` aggregate (Phase 10.8). Stdlib
`unittest` — no `pytest` (not an approved dependency), matching
`test_transport_ops_parent_domain.py`'s established precedent exactly. Covers: value-object
validation (`DriverId`), construction invariants, state transitions (idempotent no-ops),
`update_details`, repository-interface shape, and domain-event emission.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.time.clock import Clock
from raad.modules.transport_ops.domain.entities import Driver
from raad.modules.transport_ops.domain.repositories import DriverRepository
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    DriverStatus,
    OrganizationId,
    UserId,
)

VALID_DRIVER_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MG"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_USER_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def make_driver(**overrides) -> Driver:
    defaults = dict(
        id=DriverId(VALID_DRIVER_ULID),
        organization_id=OrganizationId(VALID_ORG_ULID),
        user_id=UserId(VALID_USER_ULID),
        license_no="DL-123456",
        status=DriverStatus.ACTIVE,
    )
    defaults.update(overrides)
    return Driver(**defaults)


class DriverIdValidationTests(unittest.TestCase):
    def test_valid_ulid_constructs(self) -> None:
        driver_id = DriverId(VALID_DRIVER_ULID)
        self.assertEqual(str(driver_id), VALID_DRIVER_ULID)

    def test_too_short_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            DriverId("TOOSHORT")

    def test_lowercase_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            DriverId(VALID_DRIVER_ULID.lower())

    def test_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            DriverId("")

    def test_invalid_crockford_characters_raise_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            DriverId("0" * 25 + "I")

    def test_equality_is_by_value(self) -> None:
        self.assertEqual(DriverId(VALID_DRIVER_ULID), DriverId(VALID_DRIVER_ULID))


class DriverConstructionValidationTests(unittest.TestCase):
    def test_valid_driver_constructs(self) -> None:
        driver = make_driver()
        self.assertEqual(driver.license_no, "DL-123456")
        self.assertEqual(driver.status, DriverStatus.ACTIVE)

    def test_empty_license_no_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            make_driver(license_no="")

    def test_license_no_over_64_chars_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            make_driver(license_no="A" * 65)

    def test_license_no_exactly_64_chars_is_valid(self) -> None:
        driver = make_driver(license_no="A" * 64)
        self.assertEqual(len(driver.license_no), 64)

    def test_equality_is_by_id_not_by_field_values(self) -> None:
        a = make_driver(license_no="DL-111")
        b = make_driver(license_no="DL-222")  # same id, different license_no
        self.assertEqual(a, b)

    def test_inequality_across_different_ids(self) -> None:
        other_id = "01J8Z3K9G6X8YV5T4N2R7QW3MH"
        a = make_driver()
        b = make_driver(id=DriverId(other_id))
        self.assertNotEqual(a, b)

    def test_hash_matches_id_hash(self) -> None:
        driver = make_driver()
        self.assertEqual(hash(driver), hash(driver.id))


class DriverRegisterTests(unittest.TestCase):
    def test_register_starts_active(self) -> None:
        clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
        driver = Driver.register(
            id=DriverId(VALID_DRIVER_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            user_id=UserId(VALID_USER_ULID),
            license_no="DL-123456",
            clock=clock,
        )
        self.assertEqual(driver.status, DriverStatus.ACTIVE)

    def test_register_records_driver_registered_event(self) -> None:
        clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
        driver = Driver.register(
            id=DriverId(VALID_DRIVER_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            user_id=UserId(VALID_USER_ULID),
            license_no="DL-123456",
            clock=clock,
            actor_id="actor-1",
        )
        events = driver.pull_domain_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "DriverRegistered")
        self.assertEqual(event.aggregate_type, "Driver")
        self.assertEqual(event.aggregate_id, VALID_DRIVER_ULID)
        self.assertEqual(event.org_id, VALID_ORG_ULID)
        self.assertEqual(event.occurred_at, clock.now())
        self.assertEqual(
            event.payload,
            {
                "user_id": VALID_USER_ULID,
                "license_no": "DL-123456",
                "actor_id": "actor-1",
            },
        )

    def test_register_with_invalid_license_no_raises_before_recording_event(
        self,
    ) -> None:
        clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
        with self.assertRaises(DomainError):
            Driver.register(
                id=DriverId(VALID_DRIVER_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                user_id=UserId(VALID_USER_ULID),
                license_no="",
                clock=clock,
            )


class DriverStatusTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))

    def test_disable_changes_status_and_records_event(self) -> None:
        driver = make_driver(status=DriverStatus.ACTIVE)
        driver.disable(clock=self.clock, actor_id="admin-1")
        self.assertEqual(driver.status, DriverStatus.INACTIVE)
        events = driver.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "DriverDisabled")
        self.assertEqual(events[0].payload, {"actor_id": "admin-1"})

    def test_activate_changes_status_and_records_event(self) -> None:
        driver = make_driver(status=DriverStatus.INACTIVE)
        driver.activate(clock=self.clock)
        self.assertEqual(driver.status, DriverStatus.ACTIVE)
        events = driver.pull_domain_events()
        self.assertEqual(events[0].event_type, "DriverActivated")

    def test_disable_when_already_inactive_is_idempotent_no_op(self) -> None:
        driver = make_driver(status=DriverStatus.INACTIVE)
        driver.disable(clock=self.clock)
        self.assertEqual(driver.status, DriverStatus.INACTIVE)
        self.assertEqual(driver.pull_domain_events(), [])

    def test_activate_when_already_active_is_idempotent_no_op(self) -> None:
        driver = make_driver(status=DriverStatus.ACTIVE)
        driver.activate(clock=self.clock)
        self.assertEqual(driver.pull_domain_events(), [])

    def test_disable_then_activate_round_trip(self) -> None:
        driver = make_driver(status=DriverStatus.ACTIVE)
        driver.disable(clock=self.clock)
        self.assertEqual(driver.status, DriverStatus.INACTIVE)
        driver.activate(clock=self.clock)
        self.assertEqual(driver.status, DriverStatus.ACTIVE)

    def test_clock_is_never_called_internally_besides_via_parameter(self) -> None:
        driver = make_driver(status=DriverStatus.ACTIVE)
        driver.disable(clock=self.clock)
        event = driver.pull_domain_events()[0]
        self.assertEqual(event.occurred_at, self.clock.now())


class DriverUpdateDetailsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))

    def test_update_details_changes_license_no_and_records_event(self) -> None:
        driver = make_driver(license_no="OLD-111")
        driver.update_details(
            license_no="NEW-222", clock=self.clock, actor_id="admin-1"
        )
        self.assertEqual(driver.license_no, "NEW-222")
        events = driver.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "DriverDetailsUpdated")
        self.assertEqual(
            events[0].payload, {"license_no": "NEW-222", "actor_id": "admin-1"}
        )

    def test_update_details_with_identical_value_is_idempotent_no_op(self) -> None:
        driver = make_driver(license_no="SAME-000")
        driver.update_details(license_no="SAME-000", clock=self.clock)
        self.assertEqual(driver.pull_domain_events(), [])

    def test_update_details_rejects_empty_license_no(self) -> None:
        driver = make_driver()
        with self.assertRaises(DomainError):
            driver.update_details(license_no="", clock=self.clock)

    def test_update_details_rejects_license_no_over_64_chars(self) -> None:
        driver = make_driver()
        with self.assertRaises(DomainError):
            driver.update_details(license_no="A" * 65, clock=self.clock)


class DomainEventBufferingTests(unittest.TestCase):
    def test_pull_domain_events_drains_the_buffer(self) -> None:
        clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
        driver = Driver.register(
            id=DriverId(VALID_DRIVER_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            user_id=UserId(VALID_USER_ULID),
            license_no="DL-123456",
            clock=clock,
        )
        first_pull = driver.pull_domain_events()
        second_pull = driver.pull_domain_events()
        self.assertEqual(len(first_pull), 1)
        self.assertEqual(second_pull, [])

    def test_multiple_mutations_buffer_multiple_events_in_order(self) -> None:
        clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
        driver = make_driver(status=DriverStatus.ACTIVE)
        driver.disable(clock=clock)
        driver.activate(clock=clock)
        events = driver.pull_domain_events()
        self.assertEqual(
            [e.event_type for e in events], ["DriverDisabled", "DriverActivated"]
        )


class DriverRepositoryInterfaceTests(unittest.TestCase):
    def test_cannot_instantiate_abstract_repository_directly(self) -> None:
        with self.assertRaises(TypeError):
            DriverRepository()  # abstract - no concrete get/add/list_all

    def test_concrete_implementation_satisfying_the_interface_can_be_instantiated(
        self,
    ) -> None:
        class InMemoryDriverRepository(DriverRepository):
            def __init__(self) -> None:
                self._drivers: dict[str, Driver] = {}

            async def get(self, driver_id: DriverId) -> Driver | None:
                return self._drivers.get(str(driver_id))

            def add(self, driver: Driver) -> None:
                self._drivers[str(driver.id)] = driver

            async def list_all(self) -> list[Driver]:
                return list(self._drivers.values())

        repo = InMemoryDriverRepository()
        driver = make_driver()
        repo.add(driver)
        self.assertIs(repo._drivers[str(driver.id)], driver)

    def test_incomplete_implementation_missing_add_cannot_be_instantiated(self) -> None:
        class IncompleteRepository(DriverRepository):
            async def get(self, driver_id: DriverId) -> Driver | None:
                return None

        with self.assertRaises(TypeError):
            IncompleteRepository()


if __name__ == "__main__":
    unittest.main()
