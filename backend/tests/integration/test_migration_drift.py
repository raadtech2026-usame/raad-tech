"""Integration tests for Alembic schema drift and migration resilience.

Validates the 13 migration safety criteria required for production deployments:
1. Clean PostgreSQL database upgrades to Alembic head.
2. Existing partial schema upgrades successfully.
3. Matching existing indexes are accepted.
4. Incorrect index definitions fail clearly.
5. Matching existing columns are accepted.
6. Incorrect existing column definitions fail clearly.
7. Missing `import_batches` table is created.
8. Required permissions are seeded exactly once.
9. Running upgrade again does not duplicate schema objects or permissions.
10. Existing customer data remains unchanged.
11. Alembic version reaches the correct head.
12. Downgrade does not remove pre-existing objects.
13. Migration chain has no broken revisions or cycles.
"""

from __future__ import annotations

import asyncio
import os
import unittest
import uuid
from typing import Any

import asyncpg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from raad.core.config.settings import get_settings


def _find_postgres_base_url() -> tuple[str, str] | None:
    """Finds reachable PostgreSQL connection, returns (asyncpg_url, sqlalchemy_url)."""
    candidates = []
    env_url = os.environ.get("RAAD_DB__URL")
    if env_url:
        candidates.append(env_url)
    candidates.extend([
        "postgresql+asyncpg://raad:raad@localhost:5433/raad",
        "postgresql+asyncpg://raad:raad@localhost:5432/raad",
    ])
    for sa_url in candidates:
        apg_url = sa_url.replace("postgresql+asyncpg://", "postgresql://")
        try:
            async def _check() -> None:
                conn = await asyncpg.connect(apg_url, timeout=3)
                await conn.close()

            asyncio.run(_check())
            return apg_url, sa_url
        except Exception:
            continue
    return None


class TestMigrationDrift(unittest.TestCase):
    """End-to-end PostgreSQL migration drift test suite."""

    base_apg_url: str
    base_sa_url: str

    @classmethod
    def setUpClass(cls) -> None:
        res = _find_postgres_base_url()
        if not res:
            raise unittest.SkipTest(
                "No PostgreSQL server reachable — migration drift integration tests require a live database."
            )
        cls.base_apg_url, cls.base_sa_url = res

    def _make_db_name(self, suffix: str) -> str:
        clean_suffix = suffix.replace("-", "_")[:16]
        return f"test_drift_{clean_suffix}_{uuid.uuid4().hex[:8]}"

    def _create_isolated_db(self, db_name: str) -> tuple[str, str]:
        async def _exec() -> None:
            conn = await asyncpg.connect(self.base_apg_url)
            try:
                await conn.execute(f'CREATE DATABASE "{db_name}"')
            finally:
                await conn.close()

        asyncio.run(_exec())
        base_prefix, _ = self.base_apg_url.rsplit("/", 1)
        apg_url = f"{base_prefix}/{db_name}"
        sa_prefix, _ = self.base_sa_url.rsplit("/", 1)
        sa_url = f"{sa_prefix}/{db_name}"
        return apg_url, sa_url

    def _drop_isolated_db(self, db_name: str) -> None:
        async def _exec() -> None:
            conn = await asyncpg.connect(self.base_apg_url)
            try:
                await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
            finally:
                await conn.close()

        asyncio.run(_exec())

    def _run_alembic(self, sa_url: str, command_func: Any, *args: Any, **kwargs: Any) -> None:
        orig_url = os.environ.get("RAAD_DB__URL")
        try:
            os.environ["RAAD_DB__URL"] = sa_url
            get_settings.cache_clear()
            cfg_path = "backend/alembic.ini" if os.path.exists("backend/alembic.ini") else "alembic.ini"
            cfg = Config(cfg_path)
            script_path = "backend/migrations" if os.path.exists("backend/migrations") else "migrations"
            cfg.set_main_option("script_location", script_path)
            command_func(cfg, *args, **kwargs)
        finally:
            if orig_url is not None:
                os.environ["RAAD_DB__URL"] = orig_url
            else:
                os.environ.pop("RAAD_DB__URL", None)
            get_settings.cache_clear()

    async def _query(self, apg_url: str, sql: str, *args: Any) -> list[dict[str, Any]]:
        conn = await asyncpg.connect(apg_url)
        try:
            records = await conn.fetch(sql, *args)
            return [dict(r) for r in records]
        finally:
            await conn.close()

    async def _execute(self, apg_url: str, sql: str, *args: Any) -> None:
        conn = await asyncpg.connect(apg_url)
        try:
            await conn.execute(sql, *args)
        finally:
            await conn.close()

    def test_criterion_13_migration_graph_validity(self) -> None:
        """Criterion 13: Migration chain has no broken revisions or cycles."""
        cfg_path = "backend/alembic.ini" if os.path.exists("backend/alembic.ini") else "alembic.ini"
        cfg = Config(cfg_path)
        script_path = "backend/migrations" if os.path.exists("backend/migrations") else "migrations"
        cfg.set_main_option("script_location", script_path)
        script_dir = ScriptDirectory.from_config(cfg)

        heads = script_dir.get_heads()
        self.assertEqual(heads, ["c3d4e5f6a7b8"], f"Expected single head 'c3d4e5f6a7b8', got {heads}")

        visited: set[str] = set()
        curr: str | None = heads[0]
        while curr:
            self.assertNotIn(curr, visited, f"Cycle detected at revision {curr}")
            visited.add(curr)
            rev = script_dir.get_revision(curr)
            self.assertIsNotNone(rev, f"Revision {curr} not found in script directory")
            curr = rev.down_revision

        self.assertIn("e3a7c5d91b24", visited)
        self.assertIn("f7b8c9d0e1a2", visited)
        self.assertIn("a1b2c3d4e5f6", visited)
        self.assertIn("b2c3d4e5f6a7", visited)
        self.assertIn("c3d4e5f6a7b8", visited)

    def test_clean_upgrade_and_head_verification(self) -> None:
        """Criteria 1, 7, 8, 11: Clean upgrade to head, table creation, RBAC seeding, version check."""
        db_name = self._make_db_name("clean_head")
        apg_url, sa_url = self._create_isolated_db(db_name)
        try:
            # 1. Clean upgrade to head
            self._run_alembic(sa_url, command.upgrade, "head")

            # 11. Alembic version reaches head
            rows = asyncio.run(self._query(apg_url, "SELECT version_num FROM alembic_version"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["version_num"], "c3d4e5f6a7b8")

            # 7. import_batches table created
            ib_exists = asyncio.run(
                self._query(
                    apg_url,
                    "SELECT 1 FROM information_schema.tables WHERE table_name = 'import_batches'",
                )
            )
            self.assertEqual(len(ib_exists), 1, "import_batches table was not created")

            # 8. RBAC permissions seeded exactly once
            grants = asyncio.run(
                self._query(
                    apg_url,
                    "SELECT role::text, permission FROM role_permissions WHERE permission LIKE 'data_transfer.%'",
                )
            )
            self.assertEqual(len(grants), 10, f"Expected exactly 10 data_transfer grants, found {len(grants)}")
            # Confirm org_admin has NO data_transfer grants
            org_admin_grants = [g for g in grants if g["role"] == "org_admin"]
            self.assertEqual(len(org_admin_grants), 0, "org_admin must not have data_transfer permissions")
        finally:
            self._drop_isolated_db(db_name)

    def test_partial_schema_indexes_matching_accepted(self) -> None:
        """Criteria 2, 3: Existing matching composite indexes are safely accepted."""
        db_name = self._make_db_name("idx_match")
        apg_url, sa_url = self._create_isolated_db(db_name)
        try:
            # Upgrade up to e3a7c5d91b24
            self._run_alembic(sa_url, command.upgrade, "e3a7c5d91b24")

            # Simulate schema drift: pre-create the 3 composite indexes
            asyncio.run(
                self._execute(
                    apg_url,
                    """
                    CREATE INDEX ix_students__organization_id_full_name ON students (organization_id, full_name);
                    CREATE INDEX ix_parents__organization_id_full_name ON parents (organization_id, full_name);
                    CREATE INDEX ix_student_assignments__route_vehicle_status ON student_assignments (route_id, vehicle_id, status);
                    """,
                )
            )

            # Upgrade to f7b8c9d0e1a2 — must succeed without DuplicateTableError
            self._run_alembic(sa_url, command.upgrade, "f7b8c9d0e1a2")

            rows = asyncio.run(self._query(apg_url, "SELECT version_num FROM alembic_version"))
            self.assertEqual(rows[0]["version_num"], "f7b8c9d0e1a2")
        finally:
            self._drop_isolated_db(db_name)

    def test_incompatible_index_definition_fails_clearly(self) -> None:
        """Criterion 4: Incorrect index definitions fail clearly with RuntimeError."""
        db_name = self._make_db_name("idx_incompat")
        apg_url, sa_url = self._create_isolated_db(db_name)
        try:
            # Upgrade up to e3a7c5d91b24
            self._run_alembic(sa_url, command.upgrade, "e3a7c5d91b24")

            # Pre-create index with incorrect columns
            asyncio.run(
                self._execute(
                    apg_url,
                    "CREATE INDEX ix_students__organization_id_full_name ON students (organization_id, id);",
                )
            )

            # Attempt upgrade to f7b8c9d0e1a2 — must raise RuntimeError detailing mismatch
            with self.assertRaises(Exception) as ctx:
                self._run_alembic(sa_url, command.upgrade, "f7b8c9d0e1a2")

            err_msg = str(ctx.exception)
            self.assertTrue(
                "incompatible definition" in err_msg or "RuntimeError" in str(type(ctx.exception)),
                f"Expected error describing incompatible definition, got: {err_msg}",
            )
        finally:
            self._drop_isolated_db(db_name)

    def test_partial_schema_columns_matching_accepted(self) -> None:
        """Criterion 5: Existing matching columns on staff_documents are safely accepted."""
        db_name = self._make_db_name("col_match")
        apg_url, sa_url = self._create_isolated_db(db_name)
        try:
            # Upgrade up to f7b8c9d0e1a2
            self._run_alembic(sa_url, command.upgrade, "f7b8c9d0e1a2")

            # Pre-create matching columns on staff_documents
            asyncio.run(
                self._execute(
                    apg_url,
                    """
                    ALTER TABLE staff_documents ADD COLUMN file_name VARCHAR(255);
                    ALTER TABLE staff_documents ADD COLUMN file_content_type VARCHAR(100);
                    ALTER TABLE staff_documents ADD COLUMN file_data TEXT;
                    """,
                )
            )

            # Upgrade to a1b2c3d4e5f6 — must succeed cleanly
            self._run_alembic(sa_url, command.upgrade, "a1b2c3d4e5f6")

            rows = asyncio.run(self._query(apg_url, "SELECT version_num FROM alembic_version"))
            self.assertEqual(rows[0]["version_num"], "a1b2c3d4e5f6")
        finally:
            self._drop_isolated_db(db_name)

    def test_incompatible_column_definition_fails_clearly(self) -> None:
        """Criterion 6: Incorrect existing column definitions fail clearly with RuntimeError."""
        db_name = self._make_db_name("col_incompat")
        apg_url, sa_url = self._create_isolated_db(db_name)
        try:
            # Upgrade up to f7b8c9d0e1a2
            self._run_alembic(sa_url, command.upgrade, "f7b8c9d0e1a2")

            # Pre-create column with incorrect max length (VARCHAR(50) instead of VARCHAR(255))
            asyncio.run(
                self._execute(
                    apg_url,
                    "ALTER TABLE staff_documents ADD COLUMN file_name VARCHAR(50);",
                )
            )

            with self.assertRaises(Exception) as ctx:
                self._run_alembic(sa_url, command.upgrade, "a1b2c3d4e5f6")

            err_msg = str(ctx.exception)
            self.assertTrue(
                "incompatible length" in err_msg or "incompatible" in err_msg,
                f"Expected error describing incompatible length, got: {err_msg}",
            )
        finally:
            self._drop_isolated_db(db_name)

    def test_upgrade_idempotency_and_no_duplication(self) -> None:
        """Criterion 9: Running upgrade again does not duplicate objects or permissions."""
        db_name = self._make_db_name("idempotent")
        apg_url, sa_url = self._create_isolated_db(db_name)
        try:
            self._run_alembic(sa_url, command.upgrade, "head")

            # Run upgrade head again
            self._run_alembic(sa_url, command.upgrade, "head")

            # Verify permissions count remained exactly 10
            grants = asyncio.run(
                self._query(
                    apg_url,
                    "SELECT count(*) as cnt FROM role_permissions WHERE permission LIKE 'data_transfer.%'",
                )
            )
            self.assertEqual(grants[0]["cnt"], 10)
        finally:
            self._drop_isolated_db(db_name)

    def test_customer_data_preservation(self) -> None:
        """Criterion 10: Existing customer data remains completely unchanged across migration."""
        db_name = self._make_db_name("customer_data")
        apg_url, sa_url = self._create_isolated_db(db_name)
        try:
            self._run_alembic(sa_url, command.upgrade, "e3a7c5d91b24")

            # Insert customer rows into students and parents
            org_id = "01M6TESTORG000000000000001"
            user_id = "01M6TESTUSER00000000000001"
            student_id = "01M6TESTSTUDENT00000000001"
            parent_id = "01M6TESTPARENT000000000001"

            asyncio.run(
                self._execute(
                    apg_url,
                    f"""
                    INSERT INTO students (id, organization_id, full_name, status, row_version, created_at, updated_at)
                    VALUES ('{student_id}', '{org_id}', 'Amina Hassan', 'active', 1, NOW(), NOW());

                    INSERT INTO parents (id, organization_id, user_id, full_name, phone, status, row_version, created_at, updated_at)
                    VALUES ('{parent_id}', '{org_id}', '{user_id}', 'Hassan Ali', '+252612222222', 'active', 1, NOW(), NOW());
                    """,
                )
            )

            # Upgrade to head
            self._run_alembic(sa_url, command.upgrade, "head")

            # Verify all rows and data are intact
            students = asyncio.run(
                self._query(apg_url, f"SELECT full_name FROM students WHERE id = '{student_id}'")
            )
            self.assertEqual(len(students), 1)
            self.assertEqual(students[0]["full_name"], "Amina Hassan")

            parents = asyncio.run(
                self._query(apg_url, f"SELECT full_name, phone FROM parents WHERE id = '{parent_id}'")
            )
            self.assertEqual(len(parents), 1)
            self.assertEqual(parents[0]["phone"], "+252612222222")
        finally:
            self._drop_isolated_db(db_name)

    def test_downgrade_preserves_pre_existing_objects(self) -> None:
        """Criterion 12: Downgrade removes only migration objects without deleting pre-existing data."""
        db_name = self._make_db_name("downgrade")
        apg_url, sa_url = self._create_isolated_db(db_name)
        try:
            self._run_alembic(sa_url, command.upgrade, "head")

            # Check pre-existing permission count before downgrade
            pre_grants = asyncio.run(
                self._query(
                    apg_url,
                    "SELECT count(*) as cnt FROM role_permissions WHERE permission NOT LIKE 'data_transfer.%'",
                )
            )
            initial_pre_count = pre_grants[0]["cnt"]
            self.assertGreater(initial_pre_count, 0)

            # Downgrade b2c3d4e5f6a7 -> a1b2c3d4e5f6
            self._run_alembic(sa_url, command.downgrade, "a1b2c3d4e5f6")

            # Verify import_batches is dropped
            ib_exists = asyncio.run(
                self._query(
                    apg_url,
                    "SELECT 1 FROM information_schema.tables WHERE table_name = 'import_batches'",
                )
            )
            self.assertEqual(len(ib_exists), 0, "import_batches table should be dropped after downgrade")

            # Verify data_transfer.* permissions are removed
            dt_grants = asyncio.run(
                self._query(
                    apg_url,
                    "SELECT count(*) as cnt FROM role_permissions WHERE permission LIKE 'data_transfer.%'",
                )
            )
            self.assertEqual(dt_grants[0]["cnt"], 0)

            # Verify all other role_permissions remain intact
            post_grants = asyncio.run(
                self._query(
                    apg_url,
                    "SELECT count(*) as cnt FROM role_permissions WHERE permission NOT LIKE 'data_transfer.%'",
                )
            )
            self.assertEqual(post_grants[0]["cnt"], initial_pre_count)
        finally:
            self._drop_isolated_db(db_name)


if __name__ == "__main__":
    unittest.main()
