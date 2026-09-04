"""Guard against the whole integration suite silently running on the wrong PostgreSQL server.

Local development had two servers answering the same `localhost:5432`: a native Windows
PostgreSQL 17 and the Docker Compose `postgres` service (PostgreSQL 16). Both held a database
called `raad`, both used the same-looking URL, and for a while both even reported the same
Alembic revision — so every surface-level check agreed while the schema underneath differed by
two migrations. Nothing failed; the suite simply tested a different database than the running
application used, and a real migration gap went unnoticed for days.

This module turns that class of mistake from silent into loud. It asserts the *identity* of the
server the suite is actually connected to, not just that a connection succeeded.

**Portability.** The expectation is the PostgreSQL **major version**, defaulting to the version
this repository targets everywhere it declares one: `postgres:16` in
`.github/workflows/backend-pipeline.yml` and `postgres:16-alpine` in `docker/docker-compose.yml`.
CI therefore passes with no configuration at all. An OS-specific `data_directory` is deliberately
*not* hardcoded — it differs between a Linux container (`/var/lib/postgresql/data`) and a native
Windows install, and pinning either would break the other. `data_directory` is only checked when
an expectation is supplied explicitly, and it is always reported in the failure message, because
that is the field that actually distinguishes two servers a URL cannot.

Both expectations are overridable for a deployment that legitimately targets something else:

    RAAD_TEST_DB_EXPECTED_MAJOR=17                      # or "" / "any" to disable the check
    RAAD_TEST_DB_EXPECTED_DATA_DIRECTORY=/var/lib/postgresql/data
"""

from __future__ import annotations

import os
import unittest

from sqlalchemy import text

from raad.core.config.settings import DbSettings, get_settings
from raad.core.db.engine import build_engine

#: Matches `postgres:16` (CI) and `postgres:16-alpine` (docker-compose.yml) — the only PostgreSQL
#: major version this repository declares anywhere.
DEFAULT_EXPECTED_MAJOR = "16"

_DISABLED = {"", "any", "*"}


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


def expected_major() -> str | None:
    """The PostgreSQL major version the suite expects, or `None` when the check is disabled."""
    raw = os.environ.get("RAAD_TEST_DB_EXPECTED_MAJOR", DEFAULT_EXPECTED_MAJOR).strip()
    return None if raw.lower() in _DISABLED else raw


def expected_data_directory() -> str | None:
    """An optional exact `data_directory` expectation. Unset by default — see module docstring."""
    raw = os.environ.get("RAAD_TEST_DB_EXPECTED_DATA_DIRECTORY", "").strip()
    return raw or None


def parse_major(version_string: str) -> str | None:
    """Extracts the major version from a `SELECT version()` string.

    `"PostgreSQL 16.15 on x86_64-pc-linux-musl, compiled by ..."` -> `"16"`.
    """
    parts = version_string.split()
    if len(parts) < 2 or parts[0] != "PostgreSQL":
        return None
    return parts[1].split(".", 1)[0]


def describe_mismatch(*, expected: str, actual_version: str, data_directory: str) -> str:
    """The failure message. Names both servers concretely so the fix is obvious."""
    return (
        f"Connected to the wrong PostgreSQL server.\n"
        f"  expected major version : {expected}\n"
        f"  actual server          : {actual_version}\n"
        f"  actual data_directory  : {data_directory}\n"
        f"\n"
        f"RAAD_DB__URL points at a server this suite does not expect. Locally this usually means "
        f"another PostgreSQL is answering the configured host/port ahead of the Docker Compose "
        f"'postgres' service — check for a second listener before trusting any result from this "
        f"run. Set RAAD_TEST_DB_EXPECTED_MAJOR if a different major version is genuinely intended."
    )


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class DatabaseIdentityGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = build_engine(DbSettings(url=get_settings().db.url))

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _identity(self) -> tuple[str, str]:
        async with self.engine.connect() as connection:
            version = (await connection.execute(text("select version()"))).scalar_one()
            data_directory = (
                await connection.execute(
                    text("select setting from pg_settings where name = 'data_directory'")
                )
            ).scalar_one()
        return str(version), str(data_directory)

    async def test_connected_server_is_the_expected_major_version(self) -> None:
        expected = expected_major()
        if expected is None:
            self.skipTest("RAAD_TEST_DB_EXPECTED_MAJOR disabled — identity check skipped.")
        version, data_directory = await self._identity()
        actual = parse_major(version)
        self.assertIsNotNone(actual, f"Unrecognised version string: {version!r}")
        self.assertEqual(
            actual,
            expected,
            describe_mismatch(
                expected=expected, actual_version=version, data_directory=data_directory
            ),
        )

    async def test_connected_server_matches_the_expected_data_directory_when_one_is_configured(
        self,
    ) -> None:
        expected = expected_data_directory()
        if expected is None:
            self.skipTest(
                "RAAD_TEST_DB_EXPECTED_DATA_DIRECTORY not set — deliberately unset by default "
                "because the correct value differs between a Linux container and a native install."
            )
        version, data_directory = await self._identity()
        self.assertEqual(
            data_directory,
            expected,
            describe_mismatch(
                expected=expected, actual_version=version, data_directory=data_directory
            ),
        )


if __name__ == "__main__":
    unittest.main()
