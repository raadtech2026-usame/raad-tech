"""Unit tests for `platform_audit.application.services.PlatformStatsApplicationService`
(ADR-0020). Stdlib `unittest` — no `pytest`. Fake doubles for each of the six constructor-
injected dependencies — this service takes them directly (unlike `interfaces/http/
policy_guards.py`'s free functions, which resolve from a raw `Container`), so no
`Container`-binding trick is needed here, just plain fakes recording what they were called with.

Covers: the composition itself (each module's DTO lands in the right `PlatformStatsDTO` field),
and the time-boundary arithmetic (`since_today`/`mau_since`/expiring/revenue windows) —
resolved once, here, and passed identically to every dependency that needs one.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.health.service import DependencyStatus
from raad.core.time.clock import Clock
from raad.modules.billing.application.queries import BillingStatsDTO
from raad.modules.fleet_device.application.queries import DeviceStatsDTO, VehicleStatsDTO
from raad.modules.iam.application.queries import UserStatsDTO
from raad.modules.organization.application.queries import OrganizationStatsDTO
from raad.modules.platform_audit.application.services import PlatformStatsApplicationService


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _FakeOrganizationService:
    def __init__(self, *, expired_trial_ids: list[str] | None = None) -> None:
        self.calls: list[dict] = []
        self.expired_trial_calls: list[dict] = []
        self._expired_trial_ids = expired_trial_ids or []

    async def get_organization_stats(self, *, since_today, uow) -> OrganizationStatsDTO:
        self.calls.append({"since_today": since_today, "uow": uow})
        return OrganizationStatsDTO(total=10, by_status={"active": 9, "suspended": 1}, created_today=2)

    async def get_expired_trial_organization_ids(self, *, now, uow) -> list[str]:
        self.expired_trial_calls.append({"now": now, "uow": uow})
        return self._expired_trial_ids


class _FakeUserService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def get_user_stats(self, *, since_today, mau_since, uow) -> UserStatsDTO:
        self.calls.append({"since_today": since_today, "mau_since": mau_since, "uow": uow})
        return UserStatsDTO(total=50, by_status={"active": 48, "invited": 2}, monthly_active=30, created_today=3)


class _FakeVehicleService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def get_vehicle_stats(self, *, uow) -> VehicleStatsDTO:
        self.calls.append({"uow": uow})
        return VehicleStatsDTO(total=25)


class _FakeDeviceService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def get_device_stats(self, *, uow) -> DeviceStatsDTO:
        self.calls.append({"uow": uow})
        return DeviceStatsDTO(total=25, online=20, offline=5)


class _FakeBillingService:
    def __init__(self, *, subscribed_organization_ids: frozenset[str] = frozenset()) -> None:
        self.calls: list[dict] = []
        self.subscription_lookup_calls: list[dict] = []
        # ids for which `get_current_subscription_for_organization` returns non-`None` — every
        # other id (the common case for these tests) returns `None`, i.e. "no subscription".
        self._subscribed_organization_ids = subscribed_organization_ids

    async def get_billing_stats(
        self,
        *,
        expiring_window_start,
        expiring_window_end,
        revenue_window_start,
        revenue_window_end,
        uow,
    ) -> BillingStatsDTO:
        self.calls.append(
            {
                "expiring_window_start": expiring_window_start,
                "expiring_window_end": expiring_window_end,
                "revenue_window_start": revenue_window_start,
                "revenue_window_end": revenue_window_end,
                "uow": uow,
            }
        )
        return BillingStatsDTO(
            subscription_by_status={"active": 8, "trial": 2},
            expiring_soon=1,
            revenue=1234.5,
            active_by_billing_cycle={"monthly": 7, "annual": 3},
        )

    async def get_current_subscription_for_organization(self, organization_id, *, uow):
        self.subscription_lookup_calls.append({"organization_id": organization_id, "uow": uow})
        return "a-subscription" if organization_id in self._subscribed_organization_ids else None


class _FakeHealthCheckService:
    def __init__(self) -> None:
        self.database_status = DependencyStatus(configured=True, reachable=True)
        self.broker_status = DependencyStatus(configured=True, reachable=False)

    async def check_database(self) -> DependencyStatus:
        return self.database_status

    async def check_broker(self) -> DependencyStatus:
        return self.broker_status


def make_service(
    *,
    now: datetime,
    expired_trial_ids: list[str] | None = None,
    subscribed_organization_ids: frozenset[str] = frozenset(),
) -> tuple[
    PlatformStatsApplicationService,
    _FakeOrganizationService,
    _FakeUserService,
    _FakeVehicleService,
    _FakeDeviceService,
    _FakeBillingService,
    _FakeHealthCheckService,
]:
    org = _FakeOrganizationService(expired_trial_ids=expired_trial_ids)
    user = _FakeUserService()
    vehicle = _FakeVehicleService()
    device = _FakeDeviceService()
    billing = _FakeBillingService(subscribed_organization_ids=subscribed_organization_ids)
    health = _FakeHealthCheckService()
    service = PlatformStatsApplicationService(
        clock=FixedClock(now),
        organization_service=org,
        user_service=user,
        vehicle_service=vehicle,
        device_service=device,
        billing_service=billing,
        health_check_service=health,
    )
    return service, org, user, vehicle, device, billing, health


class PlatformStatsCompositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_composes_every_dependencys_dto_into_the_response(self) -> None:
        service, *_rest = make_service(now=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))

        stats = await service.get_platform_stats(
            org_uow="org-uow", iam_uow="iam-uow", fleet_device_uow="fleet-uow", billing_uow="billing-uow"
        )

        self.assertEqual(stats.organizations.total, 10)
        self.assertEqual(stats.users.monthly_active, 30)
        self.assertEqual(stats.vehicles.total, 25)
        self.assertEqual(stats.devices.online, 20)
        self.assertEqual(stats.billing.revenue, 1234.5)
        self.assertEqual(stats.billing.active_by_billing_cycle, {"monthly": 7, "annual": 3})
        self.assertEqual(stats.payment_due_organizations, 0)  # no expired-trial orgs seeded
        self.assertEqual(stats.system_health.database, "ok")
        self.assertEqual(stats.system_health.broker, "down")

    async def test_payment_due_counts_expired_trial_organizations_with_no_subscription(
        self,
    ) -> None:
        """Organization Management phase — "Payment Due" = trial expired AND no `Subscription`
        row at all. An expired-trial org that *does* have a subscription (of any status) is not
        counted here — its own subscription status already speaks for it."""
        service, org, *_rest, billing, _health = make_service(
            now=datetime(2026, 1, 15, tzinfo=timezone.utc),
            expired_trial_ids=["org-a", "org-b", "org-c"],
            subscribed_organization_ids=frozenset({"org-b"}),
        )

        stats = await service.get_platform_stats(
            org_uow="org-uow", iam_uow="iam-uow", fleet_device_uow="fleet-uow", billing_uow="billing-uow"
        )

        self.assertEqual(stats.payment_due_organizations, 2)  # org-a and org-c, not org-b
        self.assertEqual(org.expired_trial_calls[0]["uow"], "org-uow")
        self.assertEqual(
            {call["organization_id"] for call in billing.subscription_lookup_calls},
            {"org-a", "org-b", "org-c"},
        )
        self.assertTrue(
            all(call["uow"] == "billing-uow" for call in billing.subscription_lookup_calls)
        )

    async def test_passes_each_modules_own_uow_through_unchanged(self) -> None:
        """Each dependency's UoW is resolved by the caller (the router) and threaded through
        as-is — this service never constructs or substitutes one."""
        service, org, user, vehicle, device, billing, _health = make_service(
            now=datetime(2026, 1, 15, tzinfo=timezone.utc)
        )

        await service.get_platform_stats(
            org_uow="org-uow", iam_uow="iam-uow", fleet_device_uow="fleet-uow", billing_uow="billing-uow"
        )

        self.assertEqual(org.calls[0]["uow"], "org-uow")
        self.assertEqual(user.calls[0]["uow"], "iam-uow")
        self.assertEqual(vehicle.calls[0]["uow"], "fleet-uow")
        self.assertEqual(device.calls[0]["uow"], "fleet-uow")
        self.assertEqual(billing.calls[0]["uow"], "billing-uow")

    async def test_since_today_is_midnight_of_the_clocks_own_day(self) -> None:
        service, org, user, *_rest = make_service(
            now=datetime(2026, 3, 15, 17, 45, 30, tzinfo=timezone.utc)
        )

        await service.get_platform_stats(
            org_uow=None, iam_uow=None, fleet_device_uow=None, billing_uow=None
        )

        expected_midnight = datetime(2026, 3, 15, 0, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(org.calls[0]["since_today"], expected_midnight)
        self.assertEqual(user.calls[0]["since_today"], expected_midnight)

    async def test_mau_window_is_30_days_before_now(self) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
        service, _org, user, *_rest = make_service(now=now)

        await service.get_platform_stats(
            org_uow=None, iam_uow=None, fleet_device_uow=None, billing_uow=None
        )

        self.assertEqual(user.calls[0]["mau_since"], datetime(2026, 2, 13, 12, 0, tzinfo=timezone.utc))

    async def test_expiring_window_runs_from_now_to_30_days_ahead(self) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
        service, *_rest, billing, _health = make_service(now=now)

        await service.get_platform_stats(
            org_uow=None, iam_uow=None, fleet_device_uow=None, billing_uow=None
        )

        self.assertEqual(billing.calls[0]["expiring_window_start"], now)
        self.assertEqual(
            billing.calls[0]["expiring_window_end"],
            datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc),
        )

    async def test_revenue_window_is_month_to_date(self) -> None:
        now = datetime(2026, 3, 15, 17, 45, 30, tzinfo=timezone.utc)
        service, *_rest, billing, _health = make_service(now=now)

        await service.get_platform_stats(
            org_uow=None, iam_uow=None, fleet_device_uow=None, billing_uow=None
        )

        self.assertEqual(
            billing.calls[0]["revenue_window_start"],
            datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(billing.calls[0]["revenue_window_end"], now)


if __name__ == "__main__":
    unittest.main()
