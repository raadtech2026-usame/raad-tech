"""Unit tests for `organization.api.routers` (`update_organization` & `_organization_dto_to_response`).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from raad.core.errors.exceptions import ValidationError
from raad.core.tenancy.principal import Principal, Role
from raad.modules.organization.api.routers import (
    _organization_dto_to_response,
    update_organization,
)
from raad.modules.organization.api.schemas import (
    OrganizationResponse,
    UpdateOrganizationRequest,
)
from raad.modules.organization.application.queries import OrganizationDTO


def _make_dto(**kwargs) -> OrganizationDTO:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": "01HXYZ00000000000000000001",
        "name": "Al-Nuur Academy",
        "org_type": "school",
        "parent_org_id": None,
        "region_id": "01HXYZ00000000000000000000",
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "latitude": 2.046934,
        "longitude": 45.318162,
        "geofence_radius_m": 250,
        "approaching_distance_m": 300,
        "trial_started_at": None,
        "trial_ends_at": None,
        "trial_state": "not_started",
    }
    defaults.update(kwargs)
    return OrganizationDTO(**defaults)


def _make_actor() -> Principal:
    return Principal(
        user_id="01HXYZ00000000000000000009",
        role=Role.ORG_ADMIN,
        org_id="01HXYZ00000000000000000001",
    )


class OrganizationRouterTests(unittest.IsolatedAsyncioTestCase):
    def test_dto_to_response_maps_geofence_and_approaching_distance(self) -> None:
        dto = _make_dto(
            latitude=2.046934,
            longitude=45.318162,
            geofence_radius_m=250,
            approaching_distance_m=400,
        )
        response = _organization_dto_to_response(dto)
        self.assertIsInstance(response, OrganizationResponse)
        self.assertEqual(response.latitude, 2.046934)
        self.assertEqual(response.longitude, 45.318162)
        self.assertEqual(response.geofence_radius_m, 250)
        self.assertEqual(response.approaching_distance_m, 400)

    async def test_update_organization_requires_at_least_one_field(self) -> None:
        service = MagicMock()
        uow = MagicMock()
        with self.assertRaises(ValidationError):
            await update_organization(
                organization_id="01HXYZ00000000000000000001",
                body=UpdateOrganizationRequest(),
                principal=_make_actor(),
                org_service=service,
                uow=uow,
            )

    async def test_update_organization_geofence_requires_all_three_fields(self) -> None:
        service = MagicMock()
        uow = MagicMock()
        with self.assertRaises(ValidationError):
            await update_organization(
                organization_id="01HXYZ00000000000000000001",
                body=UpdateOrganizationRequest(latitude=2.046934),  # missing longitude & radius
                principal=_make_actor(),
                org_service=service,
                uow=uow,
            )

    async def test_update_organization_geofence_calls_service(self) -> None:
        service = MagicMock()
        expected_dto = _make_dto(
            latitude=2.046934, longitude=45.318162, geofence_radius_m=350
        )
        service.update_organization_geofence = AsyncMock(return_value=expected_dto)
        uow = MagicMock()

        response = await update_organization(
            organization_id="01HXYZ00000000000000000001",
            body=UpdateOrganizationRequest(
                latitude=2.046934, longitude=45.318162, geofence_radius_m=350
            ),
            principal=_make_actor(),
            org_service=service,
            uow=uow,
        )

        self.assertEqual(response.latitude, 2.046934)
        self.assertEqual(response.longitude, 45.318162)
        self.assertEqual(response.geofence_radius_m, 350)
        service.update_organization_geofence.assert_called_once()

    async def test_update_organization_approaching_distance_calls_service(self) -> None:
        service = MagicMock()
        expected_dto = _make_dto(approaching_distance_m=500)
        service.update_organization_approaching_distance = AsyncMock(
            return_value=expected_dto
        )
        uow = MagicMock()

        response = await update_organization(
            organization_id="01HXYZ00000000000000000001",
            body=UpdateOrganizationRequest(approaching_distance_m=500),
            principal=_make_actor(),
            org_service=service,
            uow=uow,
        )

        self.assertEqual(response.approaching_distance_m, 500)
        service.update_organization_approaching_distance.assert_called_once()
