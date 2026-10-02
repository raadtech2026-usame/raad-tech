"""Development only: create a parent, two children, a driver, a route with stops and today's
trips in one existing organization, so the mobile app can be exercised against a local stack.

Everything goes through the application services, the way the dashboard would do it, so the
accounts are real logins with one-time temporary passwords (printed once, at the end).

    python scripts/seed_mobile_demo.py <organization_id> <org_admin_user_id> <vehicle_id>

Never run this against production: it creates people and trips.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import timedelta

from raad.core.config.settings import get_settings
from raad.core.di.bootstrap import build_container
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    AddStopToRouteCommand,
    ChildEnrollmentSpec,
    CreateRouteCommand,
    RegisterDriverCommand,
    RegisterParentWithChildrenCommand,
    ScheduleTripCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import GetRouteByIdQuery
from raad.modules.transport_ops.application.services import (
    DriverApplicationService,
    ParentApplicationService,
    RouteApplicationService,
    TripApplicationService,
)

# Stops along a real stretch of Mogadishu, a few hundred metres apart.
STOPS = [
    ("Isgoyska KM4", 2.03280, 45.30380),
    ("Suuqa Bakaaraha", 2.03900, 45.31200),
    ("Jaamacadda", 2.04550, 45.32050),
    ("Iridda Dugsiga", 2.05100, 45.32900),
]


async def main(organization_id: str, admin_user_id: str, vehicle_id: str) -> None:
    settings = get_settings()
    if settings.environment.lower() in {"prod", "production"}:
        raise SystemExit("Refusing to seed demo data in production.")
    container = build_container(settings)
    admin = Principal(user_id=admin_user_id, role=Role.ORG_ADMIN, org_id=organization_id)
    tag = uuid.uuid4().hex[:6]
    today = container.resolve(Clock).now().date()

    def uow() -> TransportOpsUnitOfWork:
        # Scoped the way the HTTP dependency scopes it for this organization's admin.
        unit = container.resolve(TransportOpsUnitOfWork)
        unit.scope = TenantRegionScope(organization_ids=frozenset({organization_id}))
        return unit

    routes = container.resolve(RouteApplicationService)
    route = await routes.create_route(
        CreateRouteCommand(organization_id=organization_id, name=f"Demo route {tag}", actor=admin),
        uow=uow(),
    )
    for sequence_no, (name, latitude, longitude) in enumerate(STOPS, start=1):
        await routes.add_stop_to_route(
            AddStopToRouteCommand(
                route_id=route.id,
                name=name,
                latitude=latitude,
                longitude=longitude,
                sequence_no=sequence_no,
                geofence_radius_m=120,
                actor=admin,
            ),
            uow=uow(),
        )
    route = await routes.get_route_by_id(GetRouteByIdQuery(route_id=route.id), uow=uow())
    stops = sorted(route.stops, key=lambda s: s.sequence_no)

    driver, driver_password = await container.resolve(DriverApplicationService).register_driver(
        RegisterDriverCommand(
            organization_id=organization_id,
            full_name=f"Cabdi Darawal {tag}",
            email=f"driver.{tag}@demo.raad.test",
            phone=None,
            license_no=f"DEMO-{tag}",
            actor=admin,
        ),
        uow=uow(),
    )

    parent, children, parent_password = await container.resolve(
        ParentApplicationService
    ).register_parent_with_children(
        RegisterParentWithChildrenCommand(
            organization_id=organization_id,
            full_name=f"Xaliimo Waalid {tag}",
            email=f"parent.{tag}@demo.raad.test",
            phone=None,
            actor=admin,
            children=[
                ChildEnrollmentSpec(full_name="Amina Cali", relationship="mother", is_primary=True),
                ChildEnrollmentSpec(full_name="Bilal Cali", relationship="mother", is_primary=True),
            ],
            route_id=route.id,
            pickup_stop_id=stops[1].id,
            dropoff_stop_id=stops[-1].id,
            vehicle_id=vehicle_id,
        ),
        uow=uow(),
    )

    trips = container.resolve(TripApplicationService)
    created = []
    for day in (today, today + timedelta(days=1)):
        for trip_type in ("morning", "afternoon"):
            trip = await trips.schedule_trip(
                ScheduleTripCommand(
                    organization_id=organization_id,
                    vehicle_id=vehicle_id,
                    driver_id=driver.id,
                    route_id=route.id,
                    trip_type=trip_type,
                    scheduled_date=day,
                    actor=admin,
                ),
                uow=uow(),
            )
            created.append(trip.id)

    print(
        json.dumps(
            {
                "organization_id": organization_id,
                "vehicle_id": vehicle_id,
                "route_id": route.id,
                "stops": [{"id": s.id, "name": s.name, "lat": s.latitude, "lng": s.longitude} for s in stops],
                "trip_ids": created,
                "parent": {"login": f"parent.{tag}@demo.raad.test", "temporary_password": parent_password},
                "driver": {"login": f"driver.{tag}@demo.raad.test", "temporary_password": driver_password},
                "children": [c.id for c in children],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    asyncio.run(main(*sys.argv[1:]))
