"""HTTP end-to-end tests for the mobile self-service routes (ADR-0060, ADR-0061): the real
application, real routing, real JWT verification and the real database.

What only this level can show: the routes are mounted and reachable without any permission
grant, an unauthenticated call is refused, and ownership answers 404 over the wire.

**Requires a reachable PostgreSQL database** (`RAAD_DB__URL`); skipped when unavailable.
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import timedelta

from fastapi.testclient import TestClient

from raad.core.config.settings import get_settings
from raad.core.security.tokens import TokenService
from raad.core.tenancy.principal import Principal
from raad.main import create_app
from test_self_service_integration import _SKIP_REASON, World, _db_available


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class MeHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.loop = asyncio.new_event_loop()
        cls.world = World()
        cls.loop.run_until_complete(cls.world.seed())
        cls.client_context = TestClient(create_app())
        cls.client = cls.client_context.__enter__()
        cls.tokens: TokenService = cls.client.app.state.container.resolve(TokenService)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        cls.loop.run_until_complete(cls.world.cleanup())
        cls.loop.close()

    def _auth(self, principal: Principal) -> dict[str, str]:
        pair = self.tokens.issue_token_pair(
            subject=principal.user_id, role=principal.role, org_id=principal.org_id
        )
        return {"Authorization": f"Bearer {pair.access_token}"}

    def _get(self, path: str, principal: Principal | None):
        headers = self._auth(principal) if principal is not None else {}
        return self.client.get(f"/api/v1{path}", headers=headers)

    # ---- authentication ------------------------------------------------------------------------

    def test_every_route_refuses_an_unauthenticated_call(self) -> None:
        for path in (
            "/me/transport",
            "/me/trips",
            f"/me/trips/{self.world.trip_a}",
            "/me/crew",
            "/me/documents",
            "/me/unavailability",
            "/me/incidents",
        ):
            with self.subTest(path=path):
                self.assertEqual(self._get(path, None).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/me/incidents", json={}).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/me/unavailability", json={}).status_code, 401)

    # ---- parent --------------------------------------------------------------------------------

    def test_parent_reads_own_transport_and_trips(self) -> None:
        transport = self._get("/me/transport", self.world.parent_a)
        self.assertEqual(transport.status_code, 200, transport.text)
        (child,) = transport.json()
        self.assertEqual(child["student_id"], self.world.student_a)
        self.assertEqual(child["assignment"]["vehicle"]["plate_no"], f"S{self.world.tag}")
        self.assertEqual(child["assignment"]["pickup_stop"]["name"], "Stop 1")
        self.assertNotIn("Stop 2", transport.text)  # the other family's pickup stop
        self.assertNotIn(self.world.student_b, transport.text)

        trips = self._get("/me/trips", self.world.parent_a)
        self.assertEqual(trips.status_code, 200, trips.text)
        self.assertEqual(len(trips.json()), 3)
        self.assertNotIn(self.world.student_b, trips.text)
        self.assertEqual(trips.json()[0]["planned_departure"], "06:30:00")

    def test_parent_cannot_use_driver_routes(self) -> None:
        for path in ("/me/crew", "/me/documents", "/me/unavailability", "/me/incidents",
                     f"/me/trips/{self.world.trip_a}"):
            with self.subTest(path=path):
                self.assertEqual(self._get(path, self.world.parent_a).status_code, 404)

    # ---- driver --------------------------------------------------------------------------------

    def test_driver_reads_own_trips_and_not_another_drivers(self) -> None:
        a = self.world.driver_a["principal"]
        trips = self._get("/me/trips", a)
        self.assertEqual(trips.status_code, 200, trips.text)
        self.assertEqual(
            [t["id"] for t in trips.json()], [self.world.trip_a, self.world.trip_a_tomorrow]
        )

        own = self._get(f"/me/trips/{self.world.trip_a}", a)
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual([s["name"] for s in own.json()["stops"]], ["Stop 1", "Stop 2", "Stop 3"])
        self.assertEqual(len(own.json()["passengers"]), 2)

        self.assertEqual(self._get(f"/me/trips/{self.world.trip_b}", a).status_code, 404)
        self.assertEqual(self._get("/me/transport", a).status_code, 404)
        self.assertEqual(self._get("/me/crew", a).status_code, 200)
        self.assertEqual(self._get("/me/documents", a).json()["documents"][0]["number"], "LIC-A")

    def test_driver_cannot_start_another_drivers_trip(self) -> None:
        a = self.world.driver_a["principal"]
        response = self.client.post(
            f"/api/v1/trips/{self.world.trip_b}/start", headers=self._auth(a)
        )
        self.assertEqual(response.status_code, 403, response.text)

    def test_driver_reports_unavailability_and_an_incident(self) -> None:
        b = self.world.driver_b["principal"]
        day = (self.world.today + timedelta(days=4)).isoformat()
        created = self.client.post(
            "/api/v1/me/unavailability",
            headers=self._auth(b),
            json={"starts_on": day, "ends_on": day, "reason": "personal", "note": "Family"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        listed = self._get("/me/unavailability", b).json()
        self.assertEqual([u["id"] for u in listed], [created.json()["id"]])

        bad = self.client.post(
            "/api/v1/me/unavailability",
            headers=self._auth(b),
            json={"starts_on": day, "ends_on": day, "reason": "holiday"},
        )
        self.assertEqual(bad.status_code, 422)

        withdrawn = self.client.delete(
            f"/api/v1/me/unavailability/{created.json()['id']}", headers=self._auth(b)
        )
        self.assertEqual(withdrawn.status_code, 204, withdrawn.text)
        other = self.client.delete(
            f"/api/v1/me/unavailability/{created.json()['id']}",
            headers=self._auth(self.world.driver_a["principal"]),
        )
        self.assertEqual(other.status_code, 404)

        incident = self.client.post(
            "/api/v1/me/incidents",
            headers=self._auth(b),
            json={
                "category": "delay",
                "severity": "low",
                "title": "Road closed at the bridge",
                "trip_id": self.world.trip_b,
            },
        )
        self.assertEqual(incident.status_code, 201, incident.text)
        mine = self._get("/me/incidents", b).json()
        self.assertEqual([i["title"] for i in mine], ["Road closed at the bridge"])
        self.assertEqual(self._get("/me/incidents", self.world.driver_a["principal"]).json(), [])

        foreign = self.client.post(
            "/api/v1/me/incidents",
            headers=self._auth(b),
            json={"category": "delay", "title": "Not my trip", "trip_id": self.world.trip_a},
        )
        self.assertEqual(foreign.status_code, 404)


if __name__ == "__main__":
    unittest.main()
