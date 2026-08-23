"""Unit tests for ADR-0031 (Fleet Overview read model) — `FleetOverviewApplicationService`
(`tracking.application.services`) and the two small `fleet_device` additions it composes
(`DeviceApplicationService.list_online_devices_with_vehicle_assignment`,
`VehicleApplicationService.list_vehicles_by_ids`). Stdlib `unittest` only, fakes at the same
"fake the port/service, not the whole subsystem" grain this suite already uses elsewhere
(`test_tracking_application.py`'s own `NullLatestPositionPort`).

`FleetOverviewApplicationService` is composed with lightweight fakes standing in for
`VehicleApplicationService`/`DeviceApplicationService` — duck-typed, not `isinstance`-checked
anywhere in the real constructor, the same "fake the exact methods a caller uses" approach this
whole test suite already relies on for every other application-service dependency.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import AuthorizationError
from raad.core.tenancy.principal import Principal, Role
from raad.modules.fleet_device.application.queries import OnlineDeviceAssignmentDTO, VehicleDTO
from raad.modules.tracking.application.ports import LatestPositionPort
from raad.modules.tracking.application.services import (
    FLEET_OVERVIEW_MAX_ONLINE_VEHICLES,
    FleetOverviewApplicationService,
)
from raad.modules.tracking.domain.entities import VehiclePosition
from raad.modules.tracking.domain.value_objects import (
    DeviceId,
    GeoPoint,
    HeadingDegrees,
    OrganizationId,
    SpeedKph,
    VehicleId,
    VehiclePositionId,
)


def _vehicle_dto(vehicle_id: str, plate_no: str, label: str | None = None) -> VehicleDTO:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return VehicleDTO(
        id=vehicle_id,
        organization_id="org-1",
        plate_no=plate_no,
        label=label,
        capacity=None,
        status="active",
        created_at=now,
        updated_at=now,
    )


def _position(vehicle_id: str, *, lat: float, lng: float, speed: int | None = None) -> VehiclePosition:
    return VehiclePosition(
        id=VehiclePositionId("01J8Z3K9G6X8YV5T4N2R000001"),
        organization_id=OrganizationId("org-1"),
        vehicle_id=VehicleId(vehicle_id),
        device_id=DeviceId("device-x"),
        trip_id=None,
        position=GeoPoint(latitude=lat, longitude=lng),
        speed_kph=SpeedKph(speed) if speed is not None else None,
        heading_deg=HeadingDegrees(90),
        alarm_flags=None,
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_backfill=False,
    )


class FakeVehicleService:
    def __init__(self, vehicles: list[VehicleDTO]) -> None:
        self._by_id = {v.id: v for v in vehicles}
        self.list_vehicles_by_ids_calls: list[list[str]] = []

    async def list_vehicles_by_ids(self, vehicle_ids: list[str], *, uow) -> list[VehicleDTO]:
        self.list_vehicles_by_ids_calls.append(list(vehicle_ids))
        return [self._by_id[v] for v in vehicle_ids if v in self._by_id]


class FakeDeviceService:
    def __init__(self, online: list[OnlineDeviceAssignmentDTO]) -> None:
        self._online = online

    async def list_online_devices_with_vehicle_assignment(
        self, *, uow
    ) -> list[OnlineDeviceAssignmentDTO]:
        return list(self._online)


class FakeLatestPositionPort(LatestPositionPort):
    def __init__(self, by_vehicle: dict[VehicleId, VehiclePosition] | None = None) -> None:
        self._by_vehicle = by_vehicle or {}
        self.get_latest_many_calls: list[list[VehicleId]] = []

    async def get_latest(self, vehicle_id: VehicleId) -> VehiclePosition | None:
        return self._by_vehicle.get(vehicle_id)

    async def get_latest_many(
        self, vehicle_ids: list[VehicleId]
    ) -> dict[VehicleId, VehiclePosition]:
        self.get_latest_many_calls.append(list(vehicle_ids))
        return {v: self._by_vehicle[v] for v in vehicle_ids if v in self._by_vehicle}


_SENTINEL_UOW = object()


class FleetOverviewApplicationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_online_devices_returns_an_empty_honest_result(self) -> None:
        service = FleetOverviewApplicationService(
            vehicle_service=FakeVehicleService([]),
            device_service=FakeDeviceService([]),
            latest_position_port=FakeLatestPositionPort(),
        )

        result = await service.list_online_vehicles(fleet_device_uow=_SENTINEL_UOW)

        self.assertEqual(result.vehicles, [])
        self.assertEqual(result.total_online, 0)

    async def test_joins_online_device_to_its_vehicle_and_cached_position(self) -> None:
        online = [
            OnlineDeviceAssignmentDTO(
                device_id="device-1", terminal_id="TERM1", vehicle_id="vehicle-1"
            )
        ]
        vehicles = [_vehicle_dto("vehicle-1", "ABC-123", label="Bus 1")]
        positions = {VehicleId("vehicle-1"): _position("vehicle-1", lat=2.05, lng=45.32, speed=30)}
        service = FleetOverviewApplicationService(
            vehicle_service=FakeVehicleService(vehicles),
            device_service=FakeDeviceService(online),
            latest_position_port=FakeLatestPositionPort(positions),
        )

        result = await service.list_online_vehicles(fleet_device_uow=_SENTINEL_UOW)

        self.assertEqual(result.total_online, 1)
        self.assertEqual(len(result.vehicles), 1)
        row = result.vehicles[0]
        self.assertEqual(row.vehicle_id, "vehicle-1")
        self.assertEqual(row.plate_no, "ABC-123")
        self.assertEqual(row.label, "Bus 1")
        self.assertEqual(row.device_id, "device-1")
        self.assertTrue(row.is_online)
        self.assertIsNotNone(row.position)
        self.assertEqual(row.position.latitude, 2.05)
        self.assertEqual(row.position.speed_kph, 30)

    async def test_position_is_null_for_a_vehicle_with_no_cached_key(self) -> None:
        """The confirmed, disclosed gap (ADR-0031): the live JT808 adapter doesn't yet write
        `vehicle:{id}:last`, so this is the honest, common case today — never fabricated."""
        online = [
            OnlineDeviceAssignmentDTO(
                device_id="device-1", terminal_id="TERM1", vehicle_id="vehicle-1"
            )
        ]
        service = FleetOverviewApplicationService(
            vehicle_service=FakeVehicleService([_vehicle_dto("vehicle-1", "ABC-123")]),
            device_service=FakeDeviceService(online),
            latest_position_port=FakeLatestPositionPort({}),
        )

        result = await service.list_online_vehicles(fleet_device_uow=_SENTINEL_UOW)

        self.assertIsNone(result.vehicles[0].position)

    async def test_no_latest_position_port_bound_degrades_to_null_position_not_a_crash(
        self,
    ) -> None:
        online = [
            OnlineDeviceAssignmentDTO(
                device_id="device-1", terminal_id="TERM1", vehicle_id="vehicle-1"
            )
        ]
        service = FleetOverviewApplicationService(
            vehicle_service=FakeVehicleService([_vehicle_dto("vehicle-1", "ABC-123")]),
            device_service=FakeDeviceService(online),
            latest_position_port=None,
        )

        result = await service.list_online_vehicles(fleet_device_uow=_SENTINEL_UOW)

        self.assertEqual(len(result.vehicles), 1)
        self.assertIsNone(result.vehicles[0].position)

    async def test_an_online_device_whose_vehicle_is_out_of_scope_is_silently_excluded(
        self,
    ) -> None:
        """`VehicleApplicationService.list_vehicles_by_ids` (ADR-0021 scoped) simply omits an
        out-of-scope/nonexistent vehicle id rather than erroring — this service must not crash
        or fabricate a row for it, the same "absent, not an error" contract `list_by_ids`'s own
        docstring documents."""
        online = [
            OnlineDeviceAssignmentDTO(
                device_id="device-1", terminal_id="TERM1", vehicle_id="vehicle-1"
            )
        ]
        service = FleetOverviewApplicationService(
            vehicle_service=FakeVehicleService([]),  # vehicle-1 never resolves
            device_service=FakeDeviceService(online),
            latest_position_port=FakeLatestPositionPort(),
        )

        result = await service.list_online_vehicles(fleet_device_uow=_SENTINEL_UOW)

        self.assertEqual(result.vehicles, [])
        # `total_online` still reflects the true pre-filter online count, not the post-join one.
        self.assertEqual(result.total_online, 1)

    async def test_caps_at_the_configured_maximum_and_reports_the_true_pre_cap_total(
        self,
    ) -> None:
        online = [
            OnlineDeviceAssignmentDTO(
                device_id=f"device-{i}", terminal_id=f"T{i}", vehicle_id=f"vehicle-{i:03d}"
            )
            for i in range(FLEET_OVERVIEW_MAX_ONLINE_VEHICLES + 5)
        ]
        vehicles = [_vehicle_dto(f"vehicle-{i:03d}", f"PLATE-{i}") for i in range(len(online))]
        service = FleetOverviewApplicationService(
            vehicle_service=FakeVehicleService(vehicles),
            device_service=FakeDeviceService(online),
            latest_position_port=FakeLatestPositionPort(),
        )

        result = await service.list_online_vehicles(fleet_device_uow=_SENTINEL_UOW)

        self.assertEqual(len(result.vehicles), FLEET_OVERVIEW_MAX_ONLINE_VEHICLES)
        self.assertEqual(result.total_online, FLEET_OVERVIEW_MAX_ONLINE_VEHICLES + 5)


class FleetOverviewRoleGateTests(unittest.IsolatedAsyncioTestCase):
    """A real gap found while wiring this route (`tracking/api/routers.py`'s own module-level
    comment): `tracking.vehicles.read_latest` is also held by `parent` for their existing
    single-vehicle, CR-1-gated use case — this bulk route has no per-vehicle ownership check at
    all, so a parent must never reach it. Regression coverage for the explicit
    `_FLEET_OVERVIEW_ELIGIBLE_ROLES` gate, mirroring `core.policies.video_access`'s identical
    role-set-check shape (`.claude/rules/testing.md` #3: safety-critical invariants need
    explicit tests, not incidental coverage)."""

    async def test_parent_is_rejected_even_though_it_holds_the_reused_permission(self) -> None:
        from raad.modules.tracking.api.routers import list_online_vehicles

        parent_principal = Principal(user_id="parent-1", role=Role.PARENT, org_id="org-1")

        with self.assertRaises(AuthorizationError):
            await list_online_vehicles(
                principal=parent_principal,
                fleet_overview_service=FleetOverviewApplicationService(
                    vehicle_service=FakeVehicleService([]),
                    device_service=FakeDeviceService([]),
                    latest_position_port=None,
                ),
                fleet_device_uow=_SENTINEL_UOW,
            )

    async def test_org_admin_is_allowed_through_the_role_gate(self) -> None:
        from raad.modules.tracking.api.routers import list_online_vehicles

        org_admin_principal = Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id="org-1")

        # No exception raised, and the (empty) result comes back normally.
        response = await list_online_vehicles(
            principal=org_admin_principal,
            fleet_overview_service=FleetOverviewApplicationService(
                vehicle_service=FakeVehicleService([]),
                device_service=FakeDeviceService([]),
                latest_position_port=None,
            ),
            fleet_device_uow=_SENTINEL_UOW,
        )
        self.assertEqual(response.vehicles, [])
        self.assertEqual(response.total_online, 0)


if __name__ == "__main__":
    unittest.main()
