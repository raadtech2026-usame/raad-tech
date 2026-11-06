"""Unit tests for the enterprise-grade Bulk Data Import Wizard (Excel / CSV).

Tests template generation, Somali phone number normalization, dry-run validation,
and atomic batch commit for Students and Parents.
"""

from __future__ import annotations

import csv
import io
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

import openpyxl

from raad.core.errors.exceptions import ValidationError
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.import_services import (
    BUS_MANIFEST_TEMPLATE_COLUMNS,
    ImportApplicationService,
    normalize_somali_phone,
)
from raad.modules.transport_ops.application.ports import (
    StudentBillingPort,
    TransportOpsUnitOfWork,
    UserProvisioningPort,
)
from raad.modules.transport_ops.domain.entities import (
    Parent,
    Route,
    Student,
    StudentParent,
)
from raad.modules.transport_ops.domain.value_objects import (
    Gender,
    OrganizationId,
    ParentId,
    PhoneNumber,
    RouteId,
    RouteStatus,
    StudentId,
    UserId,
)

VALID_ORG_ID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class SequentialIdGenerator(IdGenerator):
    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


class InMemoryStudentRepository:
    def __init__(self) -> None:
        self.by_id: dict[str, Student] = {}

    async def get(self, student_id: StudentId) -> Student | None:
        return self.by_id.get(str(student_id))

    def add(self, student: Student) -> None:
        self.by_id[str(student.id)] = student

    async def list_all(self) -> list[Student]:
        return list(self.by_id.values())


class InMemoryParentRepository:
    def __init__(self) -> None:
        self.by_id: dict[str, Parent] = {}

    async def get(self, parent_id: ParentId) -> Parent | None:
        return self.by_id.get(str(parent_id))

    async def get_by_user_id(self, user_id: UserId) -> Parent | None:
        for p in self.by_id.values():
            if str(p.user_id) == str(user_id):
                return p
        return None

    def add(self, parent: Parent) -> None:
        self.by_id[str(parent.id)] = parent

    async def list_all(self) -> list[Parent]:
        return list(self.by_id.values())


class InMemoryStudentParentRepository:
    def __init__(self) -> None:
        self.links: dict[tuple[str, str], StudentParent] = {}

    async def get(
        self, student_id: StudentId, parent_id: ParentId
    ) -> StudentParent | None:
        return self.links.get((str(student_id), str(parent_id)))

    def add(self, link: StudentParent) -> None:
        self.links[(str(link.student_id), str(link.parent_id))] = link

    async def list_by_student(self, student_id: StudentId) -> list[StudentParent]:
        return [l for l in self.links.values() if str(l.student_id) == str(student_id)]

    async def list_by_parent(self, parent_id: ParentId) -> list[StudentParent]:
        return [l for l in self.links.values() if str(l.parent_id) == str(parent_id)]


class InMemoryRouteRepository:
    def __init__(self) -> None:
        self.by_id: dict[str, Route] = {}

    async def get(self, route_id: RouteId) -> Route | None:
        return self.by_id.get(str(route_id))

    async def get_by_name(self, name: str) -> Route | None:
        for r in self.by_id.values():
            if r.name.lower() == name.lower():
                return r
        return None

    def add(self, route: Route) -> None:
        self.by_id[str(route.id)] = route

    async def list_all(self) -> list[Route]:
        return list(self.by_id.values())


class FakeUserProvisioningPort(UserProvisioningPort):
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create_user_with_temporary_password(
        self,
        *,
        organization_id: str,
        role: Role,
        email: str | None,
        phone: str | None,
        full_name: str,
        actor: Principal,
        initial_password: str | None = None,
    ) -> tuple[str, str]:
        user_id = f"01J8Z3K9G6X8YV5T4N2RUSR{len(self.created):03d}"
        self.created.append(
            {
                "user_id": user_id,
                "org_id": organization_id,
                "role": role,
                "email": email,
                "phone": phone,
                "full_name": full_name,
                "initial_password": initial_password,
            }
        )
        return user_id, initial_password or "Tmp-Pass-123"


class FakeStudentBillingPort(StudentBillingPort):
    def __init__(self) -> None:
        self.fees: dict[str, dict] = {}

    async def set_student_monthly_fee(
        self,
        *,
        organization_id: str,
        student_id: str,
        monthly_fee: str | float | Decimal,
        currency: str = "USD",
        actor: Principal,
    ) -> None:
        self.fees[student_id] = {
            "organization_id": organization_id,
            "monthly_fee": Decimal(str(monthly_fee)),
            "currency": currency,
        }


class FakeTransportOpsUnitOfWork(TransportOpsUnitOfWork):
    def __init__(
        self,
        students: InMemoryStudentRepository,
        parents: InMemoryParentRepository,
        student_parents: InMemoryStudentParentRepository,
        routes: InMemoryRouteRepository,
    ) -> None:
        self.students = students
        self.parents = parents
        self.student_parents = student_parents
        self.routes = routes
        self.recorded_events: list = []
        self.commit_count = 0
        self.rollback_count = 0

    async def __aenter__(self) -> FakeTransportOpsUnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self.rollback_count += 1

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class BulkImportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc))
        self.id_gen = SequentialIdGenerator()
        self.user_prov = FakeUserProvisioningPort()
        self.billing_port = FakeStudentBillingPort()
        self.service = ImportApplicationService(
            clock=self.clock,
            id_generator=self.id_gen,
            user_provisioning=self.user_prov,
            student_billing=self.billing_port,
        )

        self.students_repo = InMemoryStudentRepository()
        self.parents_repo = InMemoryParentRepository()
        self.student_parents_repo = InMemoryStudentParentRepository()
        self.routes_repo = InMemoryRouteRepository()

        self.uow = FakeTransportOpsUnitOfWork(
            students=self.students_repo,
            parents=self.parents_repo,
            student_parents=self.student_parents_repo,
            routes=self.routes_repo,
        )

        self.principal = Principal(
            user_id="01J8Z3K9G6X8YV5T4N2RACTOR1",
            org_id=VALID_ORG_ID,
            role=Role.ORG_ADMIN,
        )

    def test_normalize_somali_phone_valid(self) -> None:
        cases = [
            ("+252615123456", "+252615123456"),
            ("0615123456", "+252615123456"),
            ("615123456", "+252615123456"),
            ("252615123456", "+252615123456"),
            ("00252615123456", "+252615123456"),
            ("061-512-3456", "+252615123456"),
            ("+252 61 512 3456", "+252615123456"),
            ("621234567", "+252621234567"),
            ("77123456", "+25277123456"),
            ("901234567", "+252901234567"),
            ("+14155552671", "+14155552671"),  # valid non-Somali international
        ]
        for raw, expected in cases:
            norm, err = normalize_somali_phone(raw)
            self.assertIsNone(err, f"Expected no error for '{raw}', got '{err}'")
            self.assertEqual(norm, expected)

    def test_normalize_somali_phone_invalid(self) -> None:
        invalid_cases = [
            "123",  # too short
            "0612",  # too short
            "abc615123456",  # non-digits
            "1234567890123456",  # too long
        ]
        for raw in invalid_cases:
            norm, err = normalize_somali_phone(raw)
            self.assertIsNotNone(err, f"Expected error for '{raw}'")
            self.assertIsNone(norm)

    def test_generate_template_xlsx_and_csv(self) -> None:
        # Students XLSX
        content, media_type, filename = self.service.generate_template("students", "xlsx")
        self.assertTrue(filename.endswith(".xlsx"))
        self.assertIn("openxmlformats", media_type)
        wb = openpyxl.load_workbook(io.BytesIO(content))
        ws = wb.active
        self.assertEqual(ws.cell(row=1, column=1).value, "full_name")

        # Students CSV
        content, media_type, filename = self.service.generate_template("students", "csv")
        self.assertTrue(filename.endswith(".csv"))
        self.assertEqual(media_type, "text/csv")
        reader = list(csv.reader(io.StringIO(content.decode("utf-8"))))
        self.assertEqual(reader[0][0], "full_name")
        self.assertGreater(len(reader), 1)

        # Parents XLSX
        content, media_type, filename = self.service.generate_template("parents", "xlsx")
        self.assertTrue(filename.endswith(".xlsx"))

        # Parents CSV
        content, media_type, filename = self.service.generate_template("parents", "csv")
        self.assertTrue(filename.endswith(".csv"))

    def test_generate_template_invalid_raises(self) -> None:
        with self.assertRaises(ValidationError):
            self.service.generate_template("vehicles", "xlsx")
        with self.assertRaises(ValidationError):
            self.service.generate_template("students", "pdf")

    async def test_validate_import_empty_file_raises(self) -> None:
        with self.assertRaises(ValidationError):
            await self.service.validate_import(
                "students", b"", "empty.csv", VALID_ORG_ID, uow=self.uow
            )

    async def test_validate_import_students_csv_valid(self) -> None:
        csv_data = (
            "full_name,admission_number,grade_level,parent_name,parent_phone\n"
            "Ahmed Ali,ADM-001,Grade 7,Ali Farah,0615123456\n"
            "Maryam Hassan,ADM-002,Grade 8,Hassan Omar,+252615654321\n"
        ).encode("utf-8")

        result = await self.service.validate_import(
            "students", csv_data, "students.csv", VALID_ORG_ID, uow=self.uow
        )

        self.assertEqual(result.total_rows, 2)
        self.assertEqual(result.valid_rows, 2)
        self.assertEqual(result.invalid_rows, 0)
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(result.preview[0].data["parent_phone"], "+252615123456")

    async def test_validate_import_students_xlsx_valid(self) -> None:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["full_name", "admission_number", "parent_phone"])
        ws.append(["Ahmed Ali", "ADM-001", "0615123456"])
        buf = io.BytesIO()
        wb.save(buf)

        result = await self.service.validate_import(
            "students", buf.getvalue(), "students.xlsx", VALID_ORG_ID, uow=self.uow
        )
        self.assertEqual(result.total_rows, 1)
        self.assertEqual(result.valid_rows, 1)
        self.assertEqual(result.preview[0].data["full_name"], "Ahmed Ali")

    async def test_validate_import_students_duplicate_admission_number(self) -> None:
        csv_data = (
            "full_name,admission_number,parent_phone\n"
            "Ahmed Ali,ADM-DUPLICATE,0615123456\n"
            "Other Student,ADM-DUPLICATE,0615654321\n"
        ).encode("utf-8")

        result = await self.service.validate_import(
            "students", csv_data, "students.csv", VALID_ORG_ID, uow=self.uow
        )

        self.assertEqual(result.total_rows, 2)
        self.assertEqual(result.valid_rows, 1)
        self.assertEqual(result.invalid_rows, 1)
        self.assertIn("Duplicate admission number", result.errors[0].error_message)

    async def test_validate_import_students_invalid_phone_and_gender(self) -> None:
        csv_data = (
            "full_name,admission_number,parent_phone,gender\n"
            "Ahmed Ali,ADM-001,123,bad_gender\n"
        ).encode("utf-8")

        result = await self.service.validate_import(
            "students", csv_data, "students.csv", VALID_ORG_ID, uow=self.uow
        )

        self.assertEqual(result.invalid_rows, 1)
        error_cols = [e.column for e in result.errors]
        self.assertIn("parent_phone", error_cols)
        self.assertIn("gender", error_cols)

    async def test_validate_import_students_nonexistent_route(self) -> None:
        csv_data = (
            "full_name,admission_number,route_code\n"
            "Ahmed Ali,ADM-001,NonExistentRoute\n"
        ).encode("utf-8")

        result = await self.service.validate_import(
            "students", csv_data, "students.csv", VALID_ORG_ID, uow=self.uow
        )

        self.assertEqual(result.invalid_rows, 1)
        self.assertEqual(result.errors[0].column, "route_code")
        self.assertIn("does not exist", result.errors[0].error_message)

    async def test_validate_import_parents_csv_valid(self) -> None:
        csv_data = (
            "full_name,phone,email,address\n"
            "Ali Farah,0615123456,ali@example.com,Wadajir\n"
            "Hassan Omar,0615654321,hassan@example.com,Hodan\n"
        ).encode("utf-8")

        result = await self.service.validate_import(
            "parents", csv_data, "parents.csv", VALID_ORG_ID, uow=self.uow
        )

        self.assertEqual(result.total_rows, 2)
        self.assertEqual(result.valid_rows, 2)
        self.assertEqual(result.preview[0].data["phone"], "+252615123456")

    async def test_validate_import_parents_duplicate_phone(self) -> None:
        csv_data = (
            "full_name,phone,email\n"
            "Ali Farah,0615123456,ali@example.com\n"
            "Duplicate Person,0615123456,other@example.com\n"
        ).encode("utf-8")

        result = await self.service.validate_import(
            "parents", csv_data, "parents.csv", VALID_ORG_ID, uow=self.uow
        )

        self.assertEqual(result.invalid_rows, 1)
        self.assertEqual(result.errors[0].column, "phone")
        self.assertIn("Duplicate phone", result.errors[0].error_message)

    async def test_commit_students_import_atomic(self) -> None:
        csv_data = (
            "full_name,admission_number,grade_level,parent_name,parent_phone\n"
            "Ahmed Ali,ADM-001,Grade 7,Ali Farah,0615123456\n"
            "Maryam Hassan,ADM-002,Grade 8,Hassan Omar,+252615654321\n"
        ).encode("utf-8")

        result = await self.service.commit_import(
            "students",
            csv_data,
            "students.csv",
            VALID_ORG_ID,
            self.principal,
            uow=self.uow,
        )

        self.assertEqual(result.created_count, 2)
        self.assertEqual(result.updated_count, 0)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(self.uow.commit_count, 1)

        # Verify students in repo
        students = await self.students_repo.list_all()
        self.assertEqual(len(students), 2)
        self.assertEqual(students[0].full_name, "Ahmed Ali")
        self.assertEqual(students[0].external_ref, "ADM-001")

        # Verify parents were created and linked
        parents = await self.parents_repo.list_all()
        self.assertEqual(len(parents), 2)
        links = list(self.student_parents_repo.links.values())
        self.assertEqual(len(links), 2)

    async def test_commit_students_upsert_existing(self) -> None:
        # Pre-seed student ADM-001
        student = Student.enroll(
            id=StudentId(self.id_gen.new_id()),
            organization_id=OrganizationId(VALID_ORG_ID),
            full_name="Ahmed Old Name",
            external_ref="ADM-001",
            clock=self.clock,
        )
        self.students_repo.add(student)

        csv_data = (
            "full_name,admission_number,grade_level\n"
            "Ahmed Updated Name,ADM-001,Grade 8\n"
            "New Student,ADM-002,Grade 7\n"
        ).encode("utf-8")

        result = await self.service.commit_import(
            "students",
            csv_data,
            "students.csv",
            VALID_ORG_ID,
            self.principal,
            uow=self.uow,
        )

        self.assertEqual(result.created_count, 1)
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(self.uow.commit_count, 1)

        updated_student = (await self.students_repo.list_all())[0]
        self.assertEqual(updated_student.full_name, "Ahmed Updated Name")

    async def test_commit_parents_import_atomic(self) -> None:
        csv_data = (
            "full_name,phone,email,address\n"
            "Ali Farah,0615123456,ali@example.com,Wadajir\n"
            "Hassan Omar,0615654321,hassan@example.com,Hodan\n"
        ).encode("utf-8")

        result = await self.service.commit_import(
            "parents",
            csv_data,
            "parents.csv",
            VALID_ORG_ID,
            self.principal,
            uow=self.uow,
        )

        self.assertEqual(result.created_count, 2)
        self.assertEqual(result.updated_count, 0)
        self.assertEqual(self.uow.commit_count, 1)

        parents = await self.parents_repo.list_all()
        self.assertEqual(len(parents), 2)
        self.assertEqual(str(parents[0].phone), "+252615123456")
        self.assertEqual(len(self.user_prov.created), 2)

    async def test_commit_rollback_on_failure(self) -> None:
        # Simulate a fatal database constraint failure on commit
        async def failing_commit():
            raise RuntimeError("Database constraint violation")

        self.uow.commit = failing_commit

        csv_data = (
            "full_name,admission_number\n"
            "Ahmed Ali,ADM-001\n"
        ).encode("utf-8")

        with self.assertRaises(RuntimeError):
            await self.service.commit_import(
                "students",
                csv_data,
                "students.csv",
                VALID_ORG_ID,
                self.principal,
                uow=self.uow,
            )

        self.assertEqual(self.uow.rollback_count, 1)

    def test_generate_template_bus_manifest(self) -> None:
        raw_xlsx, media_type, filename = self.service.generate_template("bus_manifest", "xlsx")
        self.assertIn("spreadsheetml", media_type)
        self.assertTrue(filename.endswith(".xlsx"))

        wb = openpyxl.load_workbook(io.BytesIO(raw_xlsx))
        ws = wb.active
        self.assertEqual(ws.title, "Bus Ingestion Template")

        headers = [cell.value for cell in ws[1] if cell.value]
        self.assertIn("bus_name", headers)
        self.assertIn("parent_name", headers)
        self.assertIn("parent_phone", headers)
        self.assertIn("student_1_name", headers)
        self.assertIn("student_1_fee", headers)
        # CRITICAL USER REQUIREMENT: grade/class must NOT be in columns
        self.assertNotIn("grade_level", headers)
        self.assertNotIn("class", headers)

    async def test_validate_bus_manifest_csv_valid(self) -> None:
        csv_data = (
            "bus_name,parent_name,parent_phone,parent_email,student_1_name,student_1_fee,student_2_name,student_2_fee\n"
            "Bus 01,Cali Faarax,0615123456,cali@example.com,Axmed Cali,30.00,Maryan Cali,25.00\n"
            "Bus 01,Faadumo Jaamac,0615998877,,Cabdi Maxamed,35.00,,\n"
        ).encode("utf-8")

        result = await self.service.validate_import(
            "bus_manifest",
            csv_data,
            "bus_manifest.csv",
            VALID_ORG_ID,
            uow=self.uow,
        )

        self.assertEqual(result.total_rows, 2)
        self.assertEqual(result.valid_rows, 2)
        self.assertEqual(result.invalid_rows, 0)
        self.assertEqual(len(result.errors), 0)

        # Check children parsed correctly
        first_row_children = result.preview[0].data["children"]
        self.assertEqual(len(first_row_children), 2)
        self.assertEqual(first_row_children[0]["name"], "Axmed Cali")
        self.assertEqual(first_row_children[0]["fee"], Decimal("30.00"))
        self.assertEqual(first_row_children[1]["name"], "Maryan Cali")
        self.assertEqual(first_row_children[1]["fee"], Decimal("25.00"))

    async def test_commit_bus_manifest_import_atomic(self) -> None:
        csv_data = (
            "bus_name,parent_name,parent_phone,parent_email,student_1_name,student_1_fee,student_2_name,student_2_fee\n"
            "Bus 01,Cali Faarax,0615123456,cali@example.com,Axmed Cali,30.00,Maryan Cali,25.00\n"
            "Bus 01,Faadumo Jaamac,0615998877,,Cabdi Maxamed,35.00,,\n"
        ).encode("utf-8")

        result = await self.service.commit_import(
            "bus_manifest",
            csv_data,
            "bus_manifest.csv",
            VALID_ORG_ID,
            self.principal,
            uow=self.uow,
        )

        # 2 parents + 3 students = 5 created records
        self.assertEqual(result.created_count, 5)
        self.assertEqual(self.uow.commit_count, 1)

        # Route created
        routes = await self.routes_repo.list_all()
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].name, "Bus 01")

        # Parents created
        parents = await self.parents_repo.list_all()
        self.assertEqual(len(parents), 2)
        self.assertEqual(str(parents[0].phone), "+252615123456")

        # IAM users created with default password "1234"
        self.assertEqual(len(self.user_prov.created), 2)
        self.assertEqual(self.user_prov.created[0]["initial_password"], "1234")

        # Students created
        students = await self.students_repo.list_all()
        self.assertEqual(len(students), 3)
        student_names = {s.full_name for s in students}
        self.assertIn("Axmed Cali", student_names)
        self.assertIn("Maryan Cali", student_names)
        self.assertIn("Cabdi Maxamed", student_names)

        # Student parent links created
        links = self.student_parents_repo.links
        self.assertEqual(len(links), 3)

        # Student billing fees recorded in school_erp
        self.assertEqual(len(self.billing_port.fees), 3)
        fees_by_student_name = {
            s.full_name: self.billing_port.fees[str(s.id)]["monthly_fee"]
            for s in students
        }
        self.assertEqual(fees_by_student_name["Axmed Cali"], Decimal("30.00"))
        self.assertEqual(fees_by_student_name["Maryan Cali"], Decimal("25.00"))
        self.assertEqual(fees_by_student_name["Cabdi Maxamed"], Decimal("35.00"))


if __name__ == "__main__":
    unittest.main()
