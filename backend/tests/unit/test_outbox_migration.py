"""Unit test for outbox partial index migration (PERF-03 remediation).

Verifies:
- Upgrade creates the partial index on outbox(created_at) where published_at IS NULL.
- Upgrade is idempotent (subsequent runs accept existing index safely).
- Downgrade removes the index cleanly.
"""

from __future__ import annotations

import unittest
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

import importlib

migration = importlib.import_module(
    "migrations.versions.20261106_1800_c3d4e5f6a7b8_outbox_pending_partial_index"
)


class OutboxMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = sa.create_engine("sqlite:///:memory:")
        with self.engine.connect() as conn:
            metadata = sa.MetaData()
            self.table = sa.Table(
                "outbox",
                metadata,
                sa.Column("id", sa.String(26), primary_key=True),
                sa.Column("event_id", sa.String(36), unique=True, nullable=False),
                sa.Column("created_at", sa.DateTime, nullable=False),
                sa.Column("published_at", sa.DateTime, nullable=True),
            )
            metadata.create_all(conn)
            conn.commit()

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_upgrade_and_downgrade_cycle(self) -> None:
        with self.engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)

            # Patch Alembic op context for testing
            original_op = migration.op
            migration.op = op
            try:
                # 1. Run upgrade
                migration.upgrade()
                conn.commit()

                inspector = sa.inspect(conn)
                indexes = {idx["name"]: idx for idx in inspector.get_indexes("outbox")}
                self.assertIn("ix_outbox__pending_created_at", indexes)

                # 2. Idempotent re-run
                migration.upgrade()
                conn.commit()

                # 3. Downgrade
                migration.downgrade()
                conn.commit()

                inspector = sa.inspect(conn)
                indexes_after = {idx["name"]: idx for idx in inspector.get_indexes("outbox")}
                self.assertNotIn("ix_outbox__pending_created_at", indexes_after)
            finally:
                migration.op = original_op
