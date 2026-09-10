"""Regression cover for the Founder Platform Reports Expansion (2026-09-09).

`tests/unit/test_reporting_export.py` already proves the generic catalog/export machinery
(role enforcement, real PDF/xlsx bytes) against *fake* report definitions. It never drives the
real builders `core/di/report_definitions.py` registers — exactly the gap this codebase's own
Permanent Engineering Lessons name for the `_MoneyValidatingModel`/page-size bugs ("a fake-backed
unit test cannot see it... the unit tests call application services directly... anything living
purely inside [this] is untested by default"). These tests close that gap for the ten platform
reports this phase added: they drive the real `build` closures `register_report_definitions`
produces, against fake `UnitOfWork`s standing in for each owning module's real one, so a wrong
attribute name, a wrong enum member, or a broken cross-collection join (Payment -> Invoice ->
Subscription -> Plan for the three Revenue reports) fails here rather than only in a live export.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime
from types import SimpleNamespace

from raad.core.di.container import Container
from raad.core.di.report_definitions import register_report_definitions
from raad.core.pagination import OffsetPage
from raad.core.tenancy.principal import Principal, Role
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.domain.value_objects import BillingCycle, PaymentStatus, PlanStatus
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.domain.value_objects import DeviceLifecycleState, VehicleStatus
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.domain.value_objects import OrgType, OrganizationStatus, RegionStatus
from raad.modules.platform_audit.application.ports import PlatformAuditUnitOfWork
from raad.modules.reporting.application.catalog import ReportCatalog, ReportRequest
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.domain.value_objects import DriverStatus


class _Amount:
    """Stand-in for `billing.domain.value_objects.Money` — only `.amount`/`.currency` are read
    by any report builder, so a full `Decimal`-backed value object is not needed here."""

    def __init__(self, amount: float, currency: str) -> None:
        self.amount = amount
        self.currency = currency


class _FakeRepo:
    """Serves a fixed row list through the same `list_page(...)` shape every real repository
    implements — mirrors `test_reporting_export.py`'s own `_CountingRepository`, but returns
    caller-supplied domain-shaped fakes instead of bare integers."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    async def list_page(self, page_request, *, filters, sort, search):
        start = (page_request.page - 1) * page_request.page_size
        chunk = self._rows[start : start + page_request.page_size]
        return OffsetPage(
            data=chunk, total=len(self._rows), page=page_request.page, page_size=page_request.page_size
        )


class _FakeUow:
    """A no-op transaction boundary carrying one `_FakeRepo` per keyword argument — e.g.
    `_FakeUow(organizations=[...], regions=[...])` mirrors `OrganizationUnitOfWork`'s real shape
    closely enough for `_collect`/`async with uow:` to work unmodified."""

    def __init__(self, **repos: list) -> None:
        for name, rows in repos.items():
            setattr(self, name, _FakeRepo(rows))
        self.scope = None

    async def __aenter__(self) -> "_FakeUow":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


FOUNDER = Principal(user_id="founder-1", role=Role.FOUNDER, org_id=None)
FINANCE = Principal(user_id="finance-1", role=Role.FINANCE_STAFF, org_id=None)

REGION_NORTH = SimpleNamespace(
    id="region-1", name="Northern Region", geographic_scope="North",
    status=RegionStatus.ACTIVE, created_at=datetime(2026, 1, 1),
)
REGION_SOUTH = SimpleNamespace(
    id="region-2", name="Southern Region", geographic_scope=None,
    status=RegionStatus.ACTIVE, created_at=datetime(2026, 1, 1),
)
ORG_1 = SimpleNamespace(
    id="org-1", name="Green Valley School", org_type=OrgType.SCHOOL,
    status=OrganizationStatus.ACTIVE, region_id="region-1", parent_org_id=None,
    created_at=datetime(2026, 1, 2),
)
ORG_2 = SimpleNamespace(
    id="org-2", name="Blue Ridge Academy", org_type=OrgType.SCHOOL,
    status=OrganizationStatus.ACTIVE, region_id="region-2", parent_org_id=None,
    created_at=datetime(2026, 2, 2),
)
PLAN_STANDARD = SimpleNamespace(
    id="plan-1", name="Standard", billing_cycle=BillingCycle.MONTHLY,
    price=_Amount(199.5, "USD"), vehicle_limit=10, device_limit=20, user_limit=None,
    status=PlanStatus.ACTIVE,
)
PLAN_PREMIUM = SimpleNamespace(
    id="plan-2", name="Premium", billing_cycle=BillingCycle.ANNUAL,
    price=_Amount(1999.0, "USD"), vehicle_limit=None, device_limit=None, user_limit=None,
    status=PlanStatus.ACTIVE,
)
VEHICLE_1 = SimpleNamespace(
    plate_no="ABC-123", label="Bus 1", organization_id="org-1", capacity=40,
    status=VehicleStatus.ACTIVE, created_at=datetime(2026, 1, 5),
)
DRIVER_1 = SimpleNamespace(
    organization_id="org-1", license_no="DL-001", status=DriverStatus.ACTIVE,
    created_at=datetime(2026, 1, 5),
)
DEVICE_1 = SimpleNamespace(
    terminal_id="01234567890123456789", model="LSZ-C5804DG-Q-F", organization_id="org-1",
    lifecycle_state=DeviceLifecycleState.ASSIGNED, is_online=True,
    last_seen_at=datetime(2026, 9, 1, 10, 0, 0),
)
AUDIT_RENEWED = SimpleNamespace(
    created_at=datetime(2026, 9, 1, 9, 0, 0), action="SubscriptionRenewed",
    entity_type="Subscription", entity_id="sub-1", organization_id="org-1",
    actor_user_id="user-1",
)
AUDIT_OPENED = SimpleNamespace(
    created_at=datetime(2026, 1, 1, 9, 0, 0), action="SubscriptionOpened",
    entity_type="Subscription", entity_id="sub-1", organization_id="org-1",
    actor_user_id=None,
)
SUBSCRIPTION_1 = SimpleNamespace(id="sub-1", plan_id="plan-1")
INVOICE_1 = SimpleNamespace(id="inv-1", subscription_id="sub-1")
PAYMENT_PAID = SimpleNamespace(
    organization_id="org-1", invoice_id="inv-1", amount=_Amount(199.5, "USD"),
    status=PaymentStatus.PAID, provider="stripe", created_at=datetime(2026, 9, 1, 9, 30, 0),
)
PAYMENT_FAILED = SimpleNamespace(
    organization_id="org-1", invoice_id="inv-1", amount=_Amount(50.0, "USD"),
    status=PaymentStatus.FAILED, provider="stripe", created_at=datetime(2026, 9, 2, 9, 30, 0),
)


def _catalog() -> ReportCatalog:
    container = Container()
    container.bind_factory(
        OrganizationUnitOfWork,
        lambda: _FakeUow(organizations=[ORG_1, ORG_2], regions=[REGION_NORTH, REGION_SOUTH]),
    )
    container.bind_factory(
        BillingUnitOfWork,
        lambda: _FakeUow(
            plans=[PLAN_STANDARD, PLAN_PREMIUM],
            subscriptions=[SUBSCRIPTION_1],
            invoices=[INVOICE_1],
            payments=[PAYMENT_PAID, PAYMENT_FAILED],
        ),
    )
    container.bind_factory(
        FleetDeviceUnitOfWork, lambda: _FakeUow(vehicles=[VEHICLE_1], devices=[DEVICE_1])
    )
    container.bind_factory(TransportOpsUnitOfWork, lambda: _FakeUow(drivers=[DRIVER_1]))
    container.bind_factory(
        PlatformAuditUnitOfWork,
        lambda: _FakeUow(audit_entries=[AUDIT_RENEWED, AUDIT_OPENED]),
    )
    catalog = ReportCatalog()
    register_report_definitions(catalog, container)
    return catalog


_WINDOW = {"start": date(2026, 1, 1), "end": date(2026, 12, 31)}


class NewReportsRegisterTests(unittest.TestCase):
    """The ten new keys exist, are unique, and are offered to the right roles."""

    def test_all_ten_new_keys_are_registered(self) -> None:
        catalog = _catalog()
        for key in [
            "platform.organizations", "platform.regions", "platform.plans",
            "platform.vehicles", "platform.drivers", "platform.devices",
            "platform.audit_logs", "platform.revenue", "platform.revenue_by_plan",
            "platform.revenue_by_region",
        ]:
            with self.subTest(key=key):
                self.assertIsNotNone(catalog.get(key))

    def test_finance_staff_cannot_see_audit_logs(self) -> None:
        """`admin.audit.read` is not held by `finance_staff` — the report catalogue must not
        reopen that gap through a different door."""
        keys = {d.key for d in _catalog().list_for(FINANCE)}
        self.assertNotIn("platform.audit_logs", keys)

    def test_founder_sees_every_new_platform_report(self) -> None:
        keys = {d.key for d in _catalog().list_for(FOUNDER, scope="platform")}
        self.assertIn("platform.audit_logs", keys)
        self.assertIn("platform.revenue", keys)
        self.assertIn("platform.organizations", keys)


class OrganizationsPlansRegionsBuilderTests(unittest.IsolatedAsyncioTestCase):
    async def test_organizations_report_lists_both_organizations(self) -> None:
        table = await _catalog().get("platform.organizations").build(ReportRequest(principal=FOUNDER))
        self.assertEqual(len(table.rows), 2)
        names = {row[0] for row in table.rows}
        self.assertEqual(names, {"Green Valley School", "Blue Ridge Academy"})
        # `org_type`/`status` are real enums — a wrong `.value` access raises, not renders wrong.
        self.assertIn("School", table.rows[0][1])
        self.assertIn("Active", table.rows[0][2])

    async def test_regions_report_lists_both_regions(self) -> None:
        table = await _catalog().get("platform.regions").build(ReportRequest(principal=FOUNDER))
        self.assertEqual({row[0] for row in table.rows}, {"Northern Region", "Southern Region"})

    async def test_plans_report_formats_amount_and_unlimited_allowances(self) -> None:
        table = await _catalog().get("platform.plans").build(ReportRequest(principal=FOUNDER))
        standard = next(row for row in table.rows if row[0] == "Standard")
        self.assertEqual(standard[2], "199.50")
        premium = next(row for row in table.rows if row[0] == "Premium")
        self.assertEqual(premium[4], "Unlimited")  # vehicle_limit


class FleetAndDriverBuilderTests(unittest.IsolatedAsyncioTestCase):
    async def test_vehicles_report_shows_plate_and_organization(self) -> None:
        table = await _catalog().get("platform.vehicles").build(ReportRequest(principal=FOUNDER))
        self.assertEqual(table.rows, [["ABC-123", "Bus 1", "org-1", "40", "Active", "2026-01-05"]])

    async def test_drivers_report_shows_licence_and_organization(self) -> None:
        table = await _catalog().get("platform.drivers").build(ReportRequest(principal=FOUNDER))
        self.assertEqual(table.rows, [["org-1", "DL-001", "Active", "2026-01-05"]])

    async def test_devices_report_shows_lifecycle_and_connectivity(self) -> None:
        table = await _catalog().get("platform.devices").build(ReportRequest(principal=FOUNDER))
        self.assertEqual(len(table.rows), 1)
        self.assertEqual(table.rows[0][3], "Assigned")
        self.assertEqual(table.rows[0][4], "Online")


class AuditLogsBuilderTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_both_entries_with_no_date_filter(self) -> None:
        table = await _catalog().get("platform.audit_logs").build(ReportRequest(principal=FOUNDER))
        self.assertEqual(len(table.rows), 2)
        actions = {row[1] for row in table.rows}
        self.assertEqual(actions, {"SubscriptionRenewed", "SubscriptionOpened"})

    async def test_date_filter_excludes_entries_outside_the_window(self) -> None:
        table = await _catalog().get("platform.audit_logs").build(
            ReportRequest(principal=FOUNDER, start=date(2026, 8, 1), end=date(2026, 9, 30))
        )
        self.assertEqual(len(table.rows), 1)
        self.assertEqual(table.rows[0][1], "SubscriptionRenewed")


class RevenueBuilderTests(unittest.IsolatedAsyncioTestCase):
    """The real thing being exercised: `Payment -> Invoice -> Subscription -> Plan`, and
    `Payment -> Organization -> Region`, joined entirely client-side from four/two separate
    `_collect` reads — and the failed payment must never appear in a *collected* revenue figure."""

    async def test_revenue_report_includes_only_the_paid_payment(self) -> None:
        table = await _catalog().get("platform.revenue").build(
            ReportRequest(principal=FOUNDER, **_WINDOW)
        )
        self.assertEqual(len(table.rows), 1)
        row = table.rows[0]
        self.assertEqual(row[2], "Standard")  # resolved via invoice -> subscription -> plan
        self.assertEqual(row[3], "199.50")
        self.assertEqual(table.total_row[3], "199.50")

    async def test_revenue_by_plan_groups_the_one_paid_payment_under_standard(self) -> None:
        table = await _catalog().get("platform.revenue_by_plan").build(
            ReportRequest(principal=FOUNDER, **_WINDOW)
        )
        self.assertEqual(table.rows, [["Standard", "1", "199.50"]])

    async def test_revenue_by_region_groups_the_one_paid_payment_under_northern(self) -> None:
        table = await _catalog().get("platform.revenue_by_region").build(
            ReportRequest(principal=FOUNDER, **_WINDOW)
        )
        self.assertEqual(table.rows, [["Northern Region", "1", "199.50"]])

    async def test_a_payment_with_no_resolvable_plan_falls_back_honestly(self) -> None:
        """A payment whose invoice/subscription chain does not resolve (e.g. a pre-ADR-0040
        row) must render as "Unknown plan", never a fabricated name or a crash."""
        container = Container()
        container.bind_factory(
            BillingUnitOfWork,
            lambda: _FakeUow(
                plans=[],
                subscriptions=[],
                invoices=[],
                payments=[PAYMENT_PAID],
            ),
        )
        container.bind_factory(
            OrganizationUnitOfWork,
            lambda: _FakeUow(organizations=[ORG_1], regions=[REGION_NORTH]),
        )
        catalog = ReportCatalog()
        register_report_definitions(catalog, container)

        table = await catalog.get("platform.revenue_by_plan").build(
            ReportRequest(principal=FOUNDER, **_WINDOW)
        )
        self.assertEqual(table.rows, [["Unknown plan", "1", "199.50"]])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
