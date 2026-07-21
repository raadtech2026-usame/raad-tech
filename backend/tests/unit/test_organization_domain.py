"""Domain-only tests for `organization`'s `Organization`/`Region` aggregates. Stdlib
`unittest` — no `pytest`, matching established precedent. Covers: value-object validation,
`Organization`/`Region` invariants, parent/region hierarchy fields, status transitions
(idempotent no-ops), and domain-event emission.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.time.clock import Clock
from raad.modules.organization.domain.entities import Organization, Region
from raad.modules.organization.domain.value_objects import (
    BillingModel,
    OrgType,
    OrganizationId,
    OrganizationStatus,
    RegionId,
    RegionStatus,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MC"
VALID_PARENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_REGION_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class OrganizationIdTests(unittest.TestCase):
    def test_rejects_non_ulid_shape(self) -> None:
        with self.assertRaises(DomainError):
            OrganizationId("not-a-ulid")

    def test_accepts_well_formed_ulid(self) -> None:
        self.assertEqual(OrganizationId(VALID_ORG_ULID).value, VALID_ORG_ULID)


class RegionIdTests(unittest.TestCase):
    def test_rejects_non_ulid_shape(self) -> None:
        with self.assertRaises(DomainError):
            RegionId("bad")


class OrganizationInvariantTests(unittest.TestCase):
    def make_kwargs(self, **overrides):
        kwargs = dict(
            id=OrganizationId(VALID_ORG_ULID),
            name="Sunrise School",
            org_type=OrgType.SCHOOL,
            parent_org_id=None,
            region_id=RegionId(VALID_REGION_ULID),
            billing_model=BillingModel.ORGANIZATION_PAYS,
            status=OrganizationStatus.ACTIVE,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        kwargs.update(overrides)
        return kwargs

    def test_rejects_empty_name(self) -> None:
        with self.assertRaises(DomainError):
            Organization(**self.make_kwargs(name=""))

    def test_accepts_valid_organization(self) -> None:
        org = Organization(**self.make_kwargs())
        self.assertEqual(org.name, "Sunrise School")
        self.assertIsNone(org.parent_org_id)

    def test_parent_org_hierarchy_field_stored(self) -> None:
        org = Organization(
            **self.make_kwargs(parent_org_id=OrganizationId(VALID_PARENT_ULID))
        )
        self.assertEqual(str(org.parent_org_id), VALID_PARENT_ULID)

    def test_equality_is_by_id_not_by_value(self) -> None:
        org1 = Organization(**self.make_kwargs())
        org2 = Organization(**self.make_kwargs(name="Different Name"))
        self.assertEqual(org1, org2)  # same id -> equal despite differing name


class OrganizationRegisterTests(unittest.TestCase):
    def test_register_starts_active(self) -> None:
        org = Organization.register(
            id=OrganizationId(VALID_ORG_ULID),
            name="Sunrise School",
            org_type=OrgType.SCHOOL,
            region_id=RegionId(VALID_REGION_ULID),
            billing_model=BillingModel.ORGANIZATION_PAYS,
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(org.status, OrganizationStatus.ACTIVE)

    def test_register_records_organization_registered_event(self) -> None:
        org = Organization.register(
            id=OrganizationId(VALID_ORG_ULID),
            name="Sunrise School",
            org_type=OrgType.SCHOOL,
            region_id=RegionId(VALID_REGION_ULID),
            billing_model=BillingModel.ORGANIZATION_PAYS,
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        events = org.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "OrganizationRegistered")

    def test_register_with_parent_org_hierarchy(self) -> None:
        org = Organization.register(
            id=OrganizationId(VALID_ORG_ULID),
            name="Sub Campus",
            org_type=OrgType.SCHOOL,
            region_id=RegionId(VALID_REGION_ULID),
            billing_model=BillingModel.PARENT_PAYS,
            parent_org_id=OrganizationId(VALID_PARENT_ULID),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(str(org.parent_org_id), VALID_PARENT_ULID)


class OrganizationStatusTransitionTests(unittest.TestCase):
    def make_org(
        self, status: OrganizationStatus = OrganizationStatus.ACTIVE
    ) -> Organization:
        return Organization(
            id=OrganizationId(VALID_ORG_ULID),
            name="Sunrise School",
            org_type=OrgType.SCHOOL,
            parent_org_id=None,
            region_id=RegionId(VALID_REGION_ULID),
            billing_model=BillingModel.ORGANIZATION_PAYS,
            status=status,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def test_suspend_active_organization(self) -> None:
        org = self.make_org(status=OrganizationStatus.ACTIVE)
        org.suspend(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(org.status, OrganizationStatus.SUSPENDED)
        self.assertEqual(
            org.pull_domain_events()[0].event_type, "OrganizationSuspended"
        )

    def test_suspend_already_suspended_is_idempotent_no_op(self) -> None:
        org = self.make_org(status=OrganizationStatus.SUSPENDED)
        org.suspend(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(org.pull_domain_events(), [])

    def test_reactivate_suspended_organization(self) -> None:
        org = self.make_org(status=OrganizationStatus.SUSPENDED)
        org.reactivate(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(org.status, OrganizationStatus.ACTIVE)
        self.assertEqual(
            org.pull_domain_events()[0].event_type, "OrganizationReactivated"
        )

    def test_deactivate_active_organization(self) -> None:
        org = self.make_org(status=OrganizationStatus.ACTIVE)
        org.deactivate(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(org.status, OrganizationStatus.INACTIVE)
        self.assertEqual(
            org.pull_domain_events()[0].event_type, "OrganizationDeactivated"
        )

    def test_deactivate_already_inactive_is_idempotent_no_op(self) -> None:
        org = self.make_org(status=OrganizationStatus.INACTIVE)
        org.deactivate(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(org.pull_domain_events(), [])

    def test_suspend_then_reactivate_round_trip(self) -> None:
        org = self.make_org(status=OrganizationStatus.ACTIVE)
        org.suspend(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        org.reactivate(clock=FixedClock(datetime(2026, 1, 2, tzinfo=timezone.utc)))
        self.assertEqual(org.status, OrganizationStatus.ACTIVE)


class RegionInvariantTests(unittest.TestCase):
    def test_rejects_empty_name(self) -> None:
        with self.assertRaises(DomainError):
            Region(
                id=RegionId(VALID_REGION_ULID),
                name="",
                geographic_scope=None,
                status=RegionStatus.ACTIVE,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    def test_accepts_valid_region(self) -> None:
        region = Region(
            id=RegionId(VALID_REGION_ULID),
            name="East Africa",
            geographic_scope="Horn of Africa",
            status=RegionStatus.ACTIVE,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(region.name, "East Africa")


class RegionCreateTests(unittest.TestCase):
    def test_create_starts_active_and_records_event(self) -> None:
        region = Region.create(
            id=RegionId(VALID_REGION_ULID),
            name="East Africa",
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(region.status, RegionStatus.ACTIVE)
        self.assertEqual(region.pull_domain_events()[0].event_type, "RegionCreated")


class RegionStatusTransitionTests(unittest.TestCase):
    def make_region(self, status: RegionStatus = RegionStatus.ACTIVE) -> Region:
        return Region(
            id=RegionId(VALID_REGION_ULID),
            name="East Africa",
            geographic_scope=None,
            status=status,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def test_deactivate_active_region(self) -> None:
        region = self.make_region(status=RegionStatus.ACTIVE)
        region.deactivate(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(region.status, RegionStatus.INACTIVE)
        self.assertEqual(region.pull_domain_events()[0].event_type, "RegionDeactivated")

    def test_activate_already_active_is_idempotent_no_op(self) -> None:
        region = self.make_region(status=RegionStatus.ACTIVE)
        region.activate(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(region.pull_domain_events(), [])

    def test_activate_inactive_region(self) -> None:
        region = self.make_region(status=RegionStatus.INACTIVE)
        region.activate(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(region.status, RegionStatus.ACTIVE)


if __name__ == "__main__":
    unittest.main()
