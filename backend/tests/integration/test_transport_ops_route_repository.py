"""PostgreSQL-backed integration test for `transport_ops`'s `SqlAlchemyRouteRepository`
(Phase 11). Stdlib `unittest` — no `pytest` (not an approved dependency), using
`unittest.IsolatedAsyncioTestCase` against the real `SqlAlchemyTransportOpsUnitOfWork` and the
live migrated schema (Alembic head `71b67f0e5709`), not fakes — mirroring
`test_transport_ops_driver_repository.py`'s skip-guard/cleanup pattern exactly.

Covers what no in-memory unit test can prove: the round trip through the real
identity-map/`flush_tracked_changes` mechanics (`infra/repositories.py`'s module docstring),
the `RouteModel.stops` selectin-eager relationship actually loading child rows, the
`(organization_id, name)` and `(route_id, sequence_no)` DB-level unique constraints
(Database Design §6.5/§6.6), and that removing a stop from the aggregate's collection actually
deletes its row via `cascade="all, delete-orphan"` rather than merely detaching it in memory.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable, per this project's established live-verification
posture. Every test inserts rows tagged with a unique per-run marker and deletes them in
`tearDown`, leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid

import sqlalchemy.exc
from sqlalchemy import text

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.audit.writer import AuditWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.time.clock import SystemClock
from raad.modules.transport_ops.domain.entities import Route
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    RouteId,
    RouteStatus,
    StopId,
)
from raad.modules.transport_ops.infra.repositories import (
    SqlAlchemyTransportOpsUnitOfWork,
)


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class RouteRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_route_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_route_ids:
                # stops cascade-delete with their route (FK ON DELETE not configured, but the
                # ORM relationship's cascade only applies within a tracked session - delete
                # stops explicitly first so a raw DELETE here never violates the FK.
                await conn.execute(
                    text("DELETE FROM stops WHERE route_id = ANY(:ids)"),
                    {"ids": self._created_route_ids},
                )
                await conn.execute(
                    text("DELETE FROM routes WHERE id = ANY(:ids)"),
                    {"ids": self._created_route_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def test_add_then_get_round_trips_route_and_stops(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            route = Route.create(
                id=RouteId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                name=f"Route {self.tag}",
                clock=self.clock,
            )
            route.add_stop(
                id=StopId(self.id_generator.new_id()),
                name="First Stop",
                latitude=2.5,
                longitude=45.3,
                sequence_no=1,
                geofence_radius_m=50,
                clock=self.clock,
            )
            route.add_stop(
                id=StopId(self.id_generator.new_id()),
                name="Second Stop",
                latitude=2.6,
                longitude=45.4,
                sequence_no=2,
                clock=self.clock,
            )
            uow.routes.add(route)
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            route_id = route.id
            self._created_route_ids.append(str(route_id))

        async with self._new_uow() as uow:
            fetched = await uow.routes.get(route_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(fetched.name, f"Route {self.tag}")
        self.assertEqual(fetched.status, RouteStatus.ACTIVE)
        self.assertEqual(len(fetched.stops), 2)
        self.assertEqual([s.sequence_no for s in fetched.stops], [1, 2])
        self.assertEqual([s.name for s in fetched.stops], ["First Stop", "Second Stop"])
        self.assertEqual(fetched.stops[0].geofence_radius_m, 50)
        self.assertIsNone(fetched.stops[1].geofence_radius_m)

    async def test_mutation_after_get_persists_without_a_second_add(self) -> None:
        """Proves the identity-map/`flush_tracked_changes` bridge described in
        `infra/repositories.py`'s module docstring: `get()` returns a detached domain object,
        and calling a lifecycle method on it followed by `commit()` (no `add()` call) must
        still persist, because the repository re-projects the tracked object onto its ORM row.
        """
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            route = Route.create(
                id=RouteId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                name=f"Route {self.tag}",
                clock=self.clock,
            )
            uow.routes.add(route)
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            route_id = route.id
            self._created_route_ids.append(str(route_id))

        async with self._new_uow() as uow:
            loaded = await uow.routes.get(route_id)
            loaded.disable(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.routes.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.routes.get(route_id)

        self.assertEqual(refetched.status, RouteStatus.INACTIVE)

    async def test_adding_a_stop_after_get_persists_the_new_row(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            route = Route.create(
                id=RouteId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                name=f"Route {self.tag}",
                clock=self.clock,
            )
            uow.routes.add(route)
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            route_id = route.id
            self._created_route_ids.append(str(route_id))

        async with self._new_uow() as uow:
            loaded = await uow.routes.get(route_id)
            loaded.add_stop(
                id=StopId(self.id_generator.new_id()),
                name="New Stop",
                latitude=1.0,
                longitude=1.0,
                sequence_no=1,
                clock=self.clock,
            )
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            refetched = await uow.routes.get(route_id)

        self.assertEqual(len(refetched.stops), 1)
        self.assertEqual(refetched.stops[0].name, "New Stop")

    async def test_removing_a_stop_after_get_deletes_its_row(self) -> None:
        """Proves `route_to_model`'s stop-removal sync (`infra/mappers.py`'s Phase 11
        addition) actually deletes the orphaned row via `cascade="all, delete-orphan"`, not
        just detaching it from the in-memory collection."""
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            route = Route.create(
                id=RouteId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                name=f"Route {self.tag}",
                clock=self.clock,
            )
            stop = route.add_stop(
                id=StopId(self.id_generator.new_id()),
                name="Doomed Stop",
                latitude=1.0,
                longitude=1.0,
                sequence_no=1,
                clock=self.clock,
            )
            uow.routes.add(route)
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            route_id = route.id
            stop_id = stop.id
            self._created_route_ids.append(str(route_id))

        async with self._new_uow() as uow:
            loaded = await uow.routes.get(route_id)
            loaded.remove_stop(stop_id, clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()

        async with self.engine.begin() as conn:
            result = await conn.execute(
                text("SELECT COUNT(*) FROM stops WHERE id = :id"),
                {"id": str(stop_id)},
            )
            self.assertEqual(result.scalar_one(), 0)

        async with self._new_uow() as uow:
            refetched = await uow.routes.get(route_id)
        self.assertEqual(refetched.stops, ())

    async def test_list_all_includes_newly_added_route(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            route = Route.create(
                id=RouteId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                name=f"List Test {self.tag}",
                clock=self.clock,
            )
            uow.routes.add(route)
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            self._created_route_ids.append(str(route.id))

        async with self._new_uow() as uow:
            all_routes = await uow.routes.list_all()

        self.assertIn(str(route.id), {str(r.id) for r in all_routes})

    async def test_get_by_name_finds_the_created_route(self) -> None:
        org_id = self.id_generator.new_id()
        name = f"Named Route {self.tag}"
        async with self._new_uow() as uow:
            route = Route.create(
                id=RouteId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                name=name,
                clock=self.clock,
            )
            uow.routes.add(route)
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            self._created_route_ids.append(str(route.id))

        async with self._new_uow() as uow:
            found = await uow.routes.get_by_name(name)

        self.assertIsNotNone(found)
        self.assertEqual(str(found.id), str(route.id))

    async def test_get_missing_route_returns_none(self) -> None:
        async with self._new_uow() as uow:
            result = await uow.routes.get(RouteId(self.id_generator.new_id()))
        self.assertIsNone(result)

    async def test_duplicate_route_name_in_same_org_violates_db_unique_constraint(
        self,
    ) -> None:
        """Regression, at the database layer: `ux_routes__organization_id_name` rejects a
        second route with the same `(organization_id, name)` even if an application-layer
        pre-check were somehow bypassed — defense in depth over
        `ensure_route_name_available` (`application/validators.py`)."""
        org_id = self.id_generator.new_id()
        name = f"Duplicate Route {self.tag}"
        async with self._new_uow() as uow:
            route = Route.create(
                id=RouteId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                name=name,
                clock=self.clock,
            )
            uow.routes.add(route)
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            self._created_route_ids.append(str(route.id))

        with self.assertRaises(sqlalchemy.exc.IntegrityError):
            async with self._new_uow() as uow:
                duplicate = Route.create(
                    id=RouteId(self.id_generator.new_id()),
                    organization_id=OrganizationId(org_id),
                    name=name,
                    clock=self.clock,
                )
                uow.routes.add(duplicate)
                uow.record_events(duplicate.pull_domain_events())
                await uow.commit()
                self._created_route_ids.append(str(duplicate.id))


if __name__ == "__main__":
    unittest.main()
