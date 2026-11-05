"""PostgreSQL-backed integration test for `data_transfer` module's SqlAlchemyDataTransferUnitOfWork
and SqlAlchemyImportBatchRepository (Phase 2.1).

Validates against real PostgreSQL 16 Docker container:
- Persistence, identity map, and retrieval of ImportBatch aggregate.
- Correct column mapping and type preservation across all fields.
- Status transition and commit timestamp persistence.
- Organization-scoped batch listing.
- Atomic rollback behavior on transaction abort.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.time.clock import SystemClock
from raad.modules.data_transfer.domain.entities import ImportBatch
from raad.modules.data_transfer.domain.value_objects import (
    ConflictStrategy,
    ImportBatchId,
    ImportResourceType,
    ImportStatus,
)
from raad.modules.data_transfer.infra.repositories import SqlAlchemyDataTransferUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class DataTransferRepositoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self._created_batch_ids: list[str] = []

        # Unique Crockford ULID-compatible IDs
        self.org_id = "01J8Z3K9G6X8YV5T4N2R7QW001"
        self.actor_id = "01J8Z3K9G6X8YV5T4N2R7QW888"

    async def asyncTearDown(self) -> None:
        if self._created_batch_ids:
            async with self.session_factory() as session:
                for batch_id in self._created_batch_ids:
                    await session.execute(
                        text("DELETE FROM import_batches WHERE id = :id"),
                        {"id": batch_id},
                    )
                await session.commit()
        await self.engine.dispose()

    def _make_uow(self) -> SqlAlchemyDataTransferUnitOfWork:
        return SqlAlchemyDataTransferUnitOfWork(
            session_factory=self.session_factory,
            outbox_writer=self.outbox_writer,
            audit_writer=self.audit_writer,
        )

    async def test_import_batch_round_trip_persistence(self) -> None:
        batch_id_str = self.id_generator.new_id()
        self._created_batch_ids.append(batch_id_str)
        batch_id = ImportBatchId(batch_id_str)

        batch = ImportBatch.record_new(
            id=batch_id_str,
            organization_id=self.org_id,
            actor_user_id=self.actor_id,
            resource_type=ImportResourceType.STUDENTS,
            original_filename="students_batch_test.xlsx",
            file_size_bytes=10240,
            total_rows=0,
            conflict_strategy=ConflictStrategy.STRICT,
            clock=self.clock,
        )

        # 1. Insert through Unit of Work
        uow = self._make_uow()
        async with uow:
            uow.import_batches.add(batch)
            await uow.commit()

        # 2. Retrieve in a fresh UoW session
        uow2 = self._make_uow()
        async with uow2:
            retrieved = await uow2.import_batches.get_by_id(batch_id)
            self.assertIsNotNone(retrieved)
            assert retrieved is not None
            self.assertEqual(str(retrieved.id), batch_id_str)
            self.assertEqual(retrieved.organization_id, self.org_id)
            self.assertEqual(retrieved.actor_user_id, self.actor_id)
            self.assertEqual(retrieved.resource_type, ImportResourceType.STUDENTS)
            self.assertEqual(retrieved.status, ImportStatus.PENDING)
            self.assertEqual(retrieved.original_filename, "students_batch_test.xlsx")
            self.assertEqual(retrieved.file_size_bytes, 10240)
            self.assertEqual(retrieved.conflict_strategy, ConflictStrategy.STRICT)
            self.assertEqual(retrieved.total_rows, 0)
            self.assertIsNone(retrieved.committed_at)

    async def test_import_batch_status_update_and_commit(self) -> None:
        batch_id_str = self.id_generator.new_id()
        self._created_batch_ids.append(batch_id_str)
        batch_id = ImportBatchId(batch_id_str)

        batch = ImportBatch.record_new(
            id=batch_id_str,
            organization_id=self.org_id,
            actor_user_id=self.actor_id,
            resource_type=ImportResourceType.PARENTS,
            original_filename="parents_september.xlsx",
            file_size_bytes=45000,
            total_rows=100,
            conflict_strategy=ConflictStrategy.UPSERT,
            clock=self.clock,
        )

        uow = self._make_uow()
        async with uow:
            uow.import_batches.add(batch)
            await uow.commit()

        # Transition status to committed
        uow2 = self._make_uow()
        async with uow2:
            existing = await uow2.import_batches.get_by_id(batch_id)
            self.assertIsNotNone(existing)
            assert existing is not None
            existing.mark_committed(
                created_count=90,
                updated_count=10,
                skipped_count=0,
                clock=self.clock,
            )
            await uow2.commit()

        # Verify update persisted in DB
        uow3 = self._make_uow()
        async with uow3:
            verified = await uow3.import_batches.get_by_id(batch_id)
            self.assertIsNotNone(verified)
            assert verified is not None
            self.assertEqual(verified.status, ImportStatus.COMMITTED)
            self.assertEqual(verified.total_rows, 100)
            self.assertEqual(verified.created_count, 90)
            self.assertEqual(verified.updated_count, 10)
            self.assertIsNotNone(verified.committed_at)

    async def test_list_batches_by_organization(self) -> None:
        b1_str = self.id_generator.new_id()
        b2_str = self.id_generator.new_id()
        self._created_batch_ids.extend([b1_str, b2_str])

        b1 = ImportBatch.record_new(
            id=b1_str,
            organization_id=self.org_id,
            actor_user_id=self.actor_id,
            resource_type=ImportResourceType.STUDENTS,
            original_filename="f1.xlsx",
            file_size_bytes=100,
            total_rows=100,
            conflict_strategy=ConflictStrategy.STRICT,
            clock=self.clock,
        )
        b2 = ImportBatch.record_new(
            id=b2_str,
            organization_id=self.org_id,
            actor_user_id=self.actor_id,
            resource_type=ImportResourceType.PARENTS,
            original_filename="f2.xlsx",
            file_size_bytes=200,
            total_rows=100,
            conflict_strategy=ConflictStrategy.STRICT,
            clock=self.clock,
        )

        uow = self._make_uow()
        async with uow:
            uow.import_batches.add(b1)
            uow.import_batches.add(b2)
            await uow.commit()

        uow2 = self._make_uow()
        async with uow2:
            batches = await uow2.import_batches.list_by_organization(self.org_id)
            self.assertGreaterEqual(len(batches), 2)
            retrieved_ids = {str(b.id) for b in batches}
            self.assertIn(b1_str, retrieved_ids)
            self.assertIn(b2_str, retrieved_ids)

    async def test_atomic_rollback_on_failure(self) -> None:
        batch_id_str = self.id_generator.new_id()
        batch_id = ImportBatchId(batch_id_str)

        batch = ImportBatch.record_new(
            id=batch_id_str,
            organization_id=self.org_id,
            actor_user_id=self.actor_id,
            resource_type=ImportResourceType.STUDENTS,
            original_filename="rollback_test.xlsx",
            file_size_bytes=500,
            total_rows=100,
            conflict_strategy=ConflictStrategy.STRICT,
            clock=self.clock,
        )

        uow = self._make_uow()
        try:
            async with uow:
                uow.import_batches.add(batch)
                # Intentionally trigger an exception before commit
                raise RuntimeError("Simulated transaction fault")
        except RuntimeError:
            pass

        # Verify nothing was persisted
        uow2 = self._make_uow()
        async with uow2:
            not_found = await uow2.import_batches.get_by_id(batch_id)
            self.assertIsNone(not_found)


if __name__ == "__main__":
    unittest.main()
