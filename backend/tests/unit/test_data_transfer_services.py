"""Unit tests for data_transfer bounded context application services and batch persistence.

Tests template generation, target-scoped dry-run validation, atomic commit into target organization,
and ImportBatch aggregate audit record tracking.
"""

from __future__ import annotations

import io
import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import NotFoundError, ValidationError
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.data_transfer.application.ports import DataTransferUnitOfWork
from raad.modules.data_transfer.application.services import (
    DataTransferApplicationService,
)
from raad.modules.data_transfer.domain.entities import ImportBatch
from raad.modules.data_transfer.domain.repositories import ImportBatchRepository
from raad.modules.data_transfer.domain.value_objects import (
    ConflictStrategy,
    ImportStatus,
)
from raad.modules.transport_ops.application.import_services import (
    ImportApplicationService,
)
from tests.unit.test_bulk_imports import (
    FakeTransportOpsUnitOfWork,
    FakeUserProvisioningPort,
    FixedClock,
    InMemoryParentRepository,
    InMemoryRouteRepository,
    InMemoryStudentParentRepository,
    InMemoryStudentRepository,
    SequentialIdGenerator,
)

TARGET_ORG_A = "01J8Z3K9G6X8YV5T4N2R00000A"
TARGET_ORG_B = "01J8Z3K9G6X8YV5T4N2R00000B"


class InMemoryImportBatchRepository(ImportBatchRepository):
    def __init__(self) -> None:
        self.batches: dict[str, ImportBatch] = {}

    def add(self, batch: ImportBatch) -> None:
        self.batches[batch.id] = batch

    async def get(self, batch_id: str) -> ImportBatch | None:
        return self.batches.get(batch_id)

    async def list_by_organization(
        self, organization_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ImportBatch]:
        matches = [
            b for b in self.batches.values() if b.organization_id == organization_id
        ]
        matches.sort(key=lambda b: b.created_at, reverse=True)
        return matches[offset : offset + limit]


class FakeDataTransferUnitOfWork(DataTransferUnitOfWork):
    def __init__(self, batches: InMemoryImportBatchRepository) -> None:
        self.batches = batches
        self.commit_count = 0
        self.recorded_events: list = []

    async def __aenter__(self) -> FakeDataTransferUnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        pass


class DataTransferServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc))
        self.id_gen = SequentialIdGenerator()
        self.user_prov = FakeUserProvisioningPort()

        self.import_app_service = ImportApplicationService(
            clock=self.clock,
            id_generator=self.id_gen,
            user_provisioning=self.user_prov,
        )

        self.service = DataTransferApplicationService(
            clock=self.clock,
            id_generator=self.id_gen,
            import_service=self.import_app_service,
        )

        self.students_repo = InMemoryStudentRepository()
        self.parents_repo = InMemoryParentRepository()
        self.student_parents_repo = InMemoryStudentParentRepository()
        self.routes_repo = InMemoryRouteRepository()

        self.transport_uow = FakeTransportOpsUnitOfWork(
            students=self.students_repo,
            parents=self.parents_repo,
            student_parents=self.student_parents_repo,
            routes=self.routes_repo,
        )

        self.batch_repo = InMemoryImportBatchRepository()
        self.transfer_uow = FakeDataTransferUnitOfWork(self.batch_repo)

        # Super Admin Actor (Founder)
        self.super_admin = Principal(
            user_id="01J8Z3K9G6X8YV5T4N2RADMIN1",
            org_id=None,  # Super Admin has no single tenant org_id
            role=Role.FOUNDER,
        )

    def test_generate_template_delegation(self) -> None:
        content, media_type, filename = self.service.generate_template("students", "xlsx")
        self.assertTrue(filename.endswith(".xlsx"))
        self.assertIn("openxmlformats", media_type)

    async def test_validate_import_empty_file_raises(self) -> None:
        with self.assertRaises(ValidationError):
            await self.service.validate_import(
                organization_id=TARGET_ORG_A,
                resource_type="students",
                file_bytes=b"",
                filename="students.xlsx",
                transport_ops_uow=self.transport_uow,
            )

    async def test_validate_import_students_success(self) -> None:
        csv_data = (
            "full_name,admission_number,grade_level,parent_name,parent_phone\n"
            "Ahmed Ali,ADM-101,Grade 7,Ali Farah,0615123456\n"
        ).encode("utf-8")

        result = await self.service.validate_import(
            organization_id=TARGET_ORG_A,
            resource_type="students",
            file_bytes=csv_data,
            filename="students.csv",
            transport_ops_uow=self.transport_uow,
        )

        self.assertEqual(result.total_rows, 1)
        self.assertEqual(result.valid_rows, 1)
        self.assertEqual(result.invalid_rows, 0)
        self.assertEqual(result.preview[0].data["parent_phone"], "+252615123456")

    async def test_commit_import_creates_target_records_and_persists_batch(self) -> None:
        csv_data = (
            "full_name,admission_number,grade_level,parent_name,parent_phone\n"
            "Ahmed Ali,ADM-101,Grade 7,Ali Farah,0615123456\n"
            "Maryam Hassan,ADM-102,Grade 8,Hassan Omar,+252615654321\n"
        ).encode("utf-8")

        commit_result, batch = await self.service.commit_import(
            organization_id=TARGET_ORG_A,
            resource_type="students",
            file_bytes=csv_data,
            filename="students.csv",
            conflict_strategy=ConflictStrategy.SKIP_INVALID,
            principal=self.super_admin,
            data_transfer_uow=self.transfer_uow,
            transport_ops_uow=self.transport_uow,
        )

        self.assertEqual(commit_result.created_count, 2)
        self.assertEqual(commit_result.updated_count, 0)
        self.assertEqual(commit_result.skipped_count, 0)

        # Batch persistence assertions
        self.assertIsNotNone(batch.id)
        self.assertEqual(batch.organization_id, TARGET_ORG_A)
        self.assertEqual(batch.actor_user_id, self.super_admin.user_id)
        self.assertEqual(batch.status, ImportStatus.COMMITTED)
        self.assertEqual(batch.total_rows, 2)
        self.assertEqual(batch.created_count, 2)
        self.assertEqual(batch.updated_count, 0)
        self.assertEqual(batch.skipped_count, 0)
        self.assertEqual(self.transfer_uow.commit_count, 1)

        # Verify students in repository are scoped to TARGET_ORG_A
        students = await self.students_repo.list_all()
        self.assertEqual(len(students), 2)
        for s in students:
            self.assertEqual(str(s.organization_id), TARGET_ORG_A)

        # Verify batch is in batch repository
        stored_batch = await self.service.get_batch(
            batch.id, data_transfer_uow=self.transfer_uow
        )
        self.assertEqual(stored_batch.id, batch.id)

    async def test_list_batches_returns_organization_history(self) -> None:
        # Pre-seed batches for two different organizations
        b1 = ImportBatch.record_new(
            id="BATCH001",
            organization_id=TARGET_ORG_A,
            actor_user_id=self.super_admin.user_id,
            resource_type="students",
            original_filename="a.xlsx",
            file_size_bytes=1024,
            total_rows=10,
            clock=self.clock,
        )
        b1.mark_committed(created_count=10, updated_count=0, skipped_count=0, clock=self.clock)
        self.batch_repo.add(b1)

        b2 = ImportBatch.record_new(
            id="BATCH002",
            organization_id=TARGET_ORG_B,
            actor_user_id=self.super_admin.user_id,
            resource_type="parents",
            original_filename="b.xlsx",
            file_size_bytes=2048,
            total_rows=5,
            clock=self.clock,
        )
        b2.mark_committed(created_count=5, updated_count=0, skipped_count=0, clock=self.clock)
        self.batch_repo.add(b2)

        history_a = await self.service.list_batches(
            TARGET_ORG_A, data_transfer_uow=self.transfer_uow
        )
        self.assertEqual(len(history_a), 1)
        self.assertEqual(history_a[0].id, "BATCH001")
        self.assertEqual(history_a[0].organization_id, TARGET_ORG_A)

        history_b = await self.service.list_batches(
            TARGET_ORG_B, data_transfer_uow=self.transfer_uow
        )
        self.assertEqual(len(history_b), 1)
        self.assertEqual(history_b[0].id, "BATCH002")
        self.assertEqual(history_b[0].organization_id, TARGET_ORG_B)

    async def test_get_nonexistent_batch_raises_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            await self.service.get_batch("NONEXISTENT", data_transfer_uow=self.transfer_uow)


if __name__ == "__main__":
    unittest.main()
