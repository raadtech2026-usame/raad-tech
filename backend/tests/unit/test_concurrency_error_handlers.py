"""Database refusals reach the client as the status their meaning deserves (Known Issue #16).

**Why this file exists.** Two payments recorded on one Parent Invoice at the same moment: the
second loses the `row_version` race, SQLAlchemy raises `StaleDataError`, the Unit of Work rolls
the transaction back — and the client got `500 INTERNAL_ERROR`, as if the API had crashed,
inviting an unchanged retry. The same was true of every unique and foreign-key constraint in
the codebase. The refusal was always correct; only its status was wrong.

These tests drive the real registered handlers through a FastAPI app, so they prove the
response the client actually sees, not just a lookup table.
"""

from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from raad.core.errors.handlers import register_exception_handlers, resolve_integrity_error


class _DriverError(Exception):
    """Stands in for the asyncpg adapter's error: SQLAlchemy copies the SQLSTATE onto it."""

    def __init__(self, sqlstate: str | None) -> None:
        super().__init__("driver error")
        self.sqlstate = sqlstate


def _integrity(sqlstate: str | None) -> IntegrityError:
    return IntegrityError("INSERT ...", {}, _DriverError(sqlstate))


def _app(exc: Exception) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/boom")
    async def boom() -> None:
        raise exc

    return TestClient(app, raise_server_exceptions=False)


class ConcurrencyErrorHandlerTests(unittest.TestCase):
    def test_a_lost_optimistic_lock_is_a_409_conflict(self) -> None:
        response = _app(StaleDataError("UPDATE erp_parent_invoices expected 1 row")).post("/boom")
        self.assertEqual(response.status_code, 409)
        body = response.json()["error"]
        self.assertEqual(body["code"], "CONFLICT")
        self.assertIn("another request", body["message"])
        # Schema internals never reach the client.
        self.assertNotIn("erp_parent_invoices", body["message"])

    def test_a_unique_violation_is_a_409_conflict(self) -> None:
        response = _app(_integrity("23505")).post("/boom")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "CONFLICT")

    def test_a_foreign_key_violation_is_a_422(self) -> None:
        response = _app(_integrity("23503")).post("/boom")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_a_check_violation_is_a_422(self) -> None:
        self.assertEqual(_app(_integrity("23514")).post("/boom").status_code, 422)

    def test_an_unclassified_constraint_stays_a_server_fault(self) -> None:
        """A NOT NULL the code should always fill is a defect; hiding it behind 4xx would too."""
        response = _app(_integrity("23502")).post("/boom")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_ERROR")
        self.assertIsNone(resolve_integrity_error(_integrity(None)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
