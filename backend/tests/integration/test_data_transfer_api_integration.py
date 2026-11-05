"""Real HTTP + PostgreSQL + RBAC integration tests for data_transfer API endpoints (Phase 2.1).

Validates against live Docker PostgreSQL 16:
- All 4 platform-scoped endpoints mounted and functional:
  1. GET  /api/v1/admin/organizations/{org_id}/imports/templates/{resource_type}
  2. POST /api/v1/admin/organizations/{org_id}/imports/validate
  3. POST /api/v1/admin/organizations/{org_id}/imports/commit
  4. GET  /api/v1/admin/organizations/{org_id}/imports/batches
- Security role matrix:
  - FOUNDER: full access to templates, validation, commit, batches.
  - ORG_ADMIN: 403 Forbidden on all data_transfer actions.
  - DRIVER / PARENT: 403 Forbidden.
  - UNAUTHENTICATED: 401 Unauthorized.
- IDOR shield (ADR-0021): access to non-existent or out-of-scope org returns 404.
- Real XLSX parsing and validation: valid workbook, invalid telephone, missing fields.
- Atomic commit: commits to database, creates batch record, persists students/parents.
"""

from __future__ import annotations

import io
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
import openpyxl
from sqlalchemy import text

from raad.core.config.settings import get_settings
from raad.core.security.tokens import TokenService
from raad.core.tenancy.principal import Principal, Role
from raad.main import create_app

EXISTING_ORG_ID = "01M4ZT3DV63S4D3SY3X0MA9YVX"
NONEXISTENT_ORG_ID = "01J8Z3K9G6X8YV5T4N2R7QW999"


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


def create_sample_student_xlsx(rows: list[dict[str, str]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Students"

    headers = [
        "full_name",
        "admission_number",
        "grade_level",
        "parent_name",
        "parent_phone",
        "route_code",
        "gender",
        "date_of_birth",
        "notes",
    ]
    ws.append(headers)

    for r in rows:
        ws.append([
            r.get("full_name", ""),
            r.get("admission_number", r.get("external_reference", "")),
            r.get("grade_level", "Grade 7"),
            r.get("parent_name", ""),
            r.get("parent_phone", ""),
            r.get("route_code", ""),
            r.get("gender", ""),
            r.get("date_of_birth", ""),
            r.get("notes", ""),
        ])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def create_sample_parent_xlsx(rows: list[dict[str, str]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Parents"

    headers = [
        "full_name",
        "phone",
        "email",
        "address",
        "emergency_contact_name",
        "emergency_contact_phone",
        "notes",
    ]
    ws.append(headers)

    for r in rows:
        ws.append([
            r.get("full_name", ""),
            r.get("phone", r.get("primary_phone", "")),
            r.get("email", ""),
            r.get("address", ""),
            r.get("emergency_contact_name", ""),
            r.get("emergency_contact_phone", ""),
            r.get("notes", ""),
        ])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class DataTransferApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import asyncio
        from sqlalchemy.ext.asyncio import create_async_engine

        cls.app = create_app()
        cls.client_context = TestClient(cls.app)
        cls.client = cls.client_context.__enter__()
        cls.tokens: TokenService = cls.client.app.state.container.resolve(TokenService)

        # Seed support_assignments for finance user so they have authorized org scope
        settings = get_settings()
        engine = create_async_engine(settings.db.url)

        async def seed_support():
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO support_assignments (user_id, organization_id, granted_at) "
                        "VALUES ('01M4ZSMKCWDG8ZW51S9YVRENM6', '01M4ZT3DV63S4D3SY3X0MA9YVX', now()) "
                        "ON CONFLICT DO NOTHING;"
                    )
                )
            await engine.dispose()

        asyncio.run(seed_support())

        # Principals
        cls.founder = Principal(user_id="01M4ZSMKCWDG8ZW51S9YVRENM3", role=Role.FOUNDER, org_id=None)
        cls.reg_mgr = Principal(user_id="01M4ZSMKCWDG8ZW51S9YVRENM4", role=Role.REGIONAL_MANAGER, org_id=None)
        cls.support = Principal(user_id="01M4ZSMKCWDG8ZW51S9YVRENM5", role=Role.SUPPORT_STAFF, org_id=None)
        cls.finance = Principal(user_id="01M4ZSMKCWDG8ZW51S9YVRENM6", role=Role.FINANCE_STAFF, org_id=None)
        cls.org_admin = Principal(
            user_id="01M4ZT3DVT5QSFRF6HXQZD1TZH",
            role=Role.ORG_ADMIN,
            org_id=EXISTING_ORG_ID,
        )
        cls.driver = Principal(user_id="01M4ZT3DVT5QSFRF6HXQZD1DRV", role=Role.DRIVER, org_id=EXISTING_ORG_ID)
        cls.parent = Principal(user_id="01M4ZT3DVT5QSFRF6HXQZD1PAR", role=Role.PARENT, org_id=EXISTING_ORG_ID)

    @classmethod
    def tearDownClass(cls) -> None:
        import asyncio
        from sqlalchemy.ext.asyncio import create_async_engine

        cls.client_context.__exit__(None, None, None)

        settings = get_settings()
        engine = create_async_engine(settings.db.url)

        async def cleanup_support():
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "DELETE FROM support_assignments WHERE user_id = '01M4ZSMKCWDG8ZW51S9YVRENM6';"
                    )
                )
            await engine.dispose()

        asyncio.run(cleanup_support())

    def _auth(self, principal: Principal) -> dict[str, str]:
        pair = self.tokens.issue_token_pair(
            subject=principal.user_id, role=principal.role, org_id=principal.org_id
        )
        return {"Authorization": f"Bearer {pair.access_token}"}

    # -------------------------------------------------------------------------
    # 1. Unauthenticated and Role Denial Gates (Negative Security Checks)
    # -------------------------------------------------------------------------

    def test_unauthenticated_requests_are_denied_401(self) -> None:
        url = f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/batches"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 401)

    def test_org_admin_is_strictly_denied_all_import_actions_403(self) -> None:
        auth = self._auth(self.org_admin)

        # Template
        resp1 = self.client.get(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/templates/students",
            headers=auth,
        )
        self.assertEqual(resp1.status_code, 403)

        # Validate
        file_bytes = create_sample_student_xlsx([])
        resp2 = self.client.post(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/validate?resource_type=students",
            files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth,
        )
        self.assertEqual(resp2.status_code, 403)

        # Commit
        resp3 = self.client.post(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/commit?resource_type=students",
            files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth,
        )
        self.assertEqual(resp3.status_code, 403)

        # Batches
        resp4 = self.client.get(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/batches",
            headers=auth,
        )
        self.assertEqual(resp4.status_code, 403)

    def test_driver_and_parent_denied_403(self) -> None:
        for p in (self.driver, self.parent):
            auth = self._auth(p)
            resp = self.client.get(
                f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/batches",
                headers=auth,
            )
            self.assertEqual(resp.status_code, 403)

    def test_finance_staff_can_read_templates_but_not_commit(self) -> None:
        auth = self._auth(self.finance)

        # Template read allowed
        resp_tpl = self.client.get(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/templates/students?format=csv",
            headers=auth,
        )
        self.assertEqual(resp_tpl.status_code, 200)

        # Commit denied
        file_bytes = create_sample_student_xlsx([])
        resp_commit = self.client.post(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/commit?resource_type=students",
            files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth,
        )
        self.assertEqual(resp_commit.status_code, 403)

    def test_nonexistent_organization_returns_404_idor_shield(self) -> None:
        auth = self._auth(self.founder)
        resp = self.client.get(
            f"/api/v1/admin/organizations/{NONEXISTENT_ORG_ID}/imports/batches",
            headers=auth,
        )
        self.assertEqual(resp.status_code, 404)

    # -------------------------------------------------------------------------
    # 2. Template Generation Endpoints (Real Excel / CSV file delivery)
    # -------------------------------------------------------------------------

    def test_founder_downloads_student_xlsx_template(self) -> None:
        auth = self._auth(self.founder)
        resp = self.client.get(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/templates/students?format=xlsx",
            headers=auth,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", resp.headers["content-type"])
        # Verify valid workbook bytes
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        self.assertIn("full_name", [cell.value for cell in wb.active[1]])

    def test_founder_downloads_parent_csv_template(self) -> None:
        auth = self._auth(self.founder)
        resp = self.client.get(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/templates/parents?format=csv",
            headers=auth,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.headers["content-type"])
        csv_text = resp.text
        self.assertIn("full_name", csv_text)
        self.assertIn("phone", csv_text)

    # -------------------------------------------------------------------------
    # 3. Validation & Parsing Diagnostics (Real File Processing)
    # -------------------------------------------------------------------------

    def test_validate_valid_student_workbook(self) -> None:
        auth = self._auth(self.founder)
        file_bytes = create_sample_student_xlsx([
            {
                "full_name": "Amina Farah",
                "date_of_birth": "2012-05-15",
                "gender": "female",
                "external_reference": "STU-1001",
                "notes": "Grade 6 student",
            },
            {
                "full_name": "Liban Dahir",
                "date_of_birth": "2011-09-20",
                "gender": "male",
                "external_reference": "STU-1002",
                "notes": "Grade 7 student",
            },
        ])

        resp = self.client.post(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/validate?resource_type=students",
            files={"file": ("students.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["resource_type"], "students")
        self.assertEqual(data["total_rows"], 2)
        self.assertEqual(data["valid_rows"], 2)
        self.assertEqual(data["invalid_rows"], 0)
        self.assertEqual(len(data["errors"]), 0)
        self.assertEqual(len(data["preview"]), 2)
        self.assertTrue(data["preview"][0]["is_valid"])

    def test_validate_invalid_parent_phone_diagnostics(self) -> None:
        auth = self._auth(self.founder)
        # Invalid Somali phone number
        file_bytes = create_sample_parent_xlsx([
            {
                "full_name": "Guled Warsame",
                "primary_phone": "12345",  # Invalid phone
                "email": "guled@example.com",
            }
        ])

        resp = self.client.post(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/validate?resource_type=parents",
            files={"file": ("parents.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_rows"], 1)
        self.assertEqual(data["invalid_rows"], 1)
        self.assertGreaterEqual(len(data["errors"]), 1)
        self.assertEqual(data["errors"][0]["row_number"], 2)

    # -------------------------------------------------------------------------
    # 4. Atomic Commit & Database Batch Recording (Live DB Verification)
    # -------------------------------------------------------------------------

    def test_commit_bulk_import_persists_to_postgresql(self) -> None:
        auth = self._auth(self.founder)
        unique_ref = f"REF-{datetime.now(timezone.utc).strftime('%H%M%S')}"

        file_bytes = create_sample_student_xlsx([
            {
                "full_name": f"Hassan Ali {unique_ref}",
                "date_of_birth": "2013-01-10",
                "gender": "male",
                "external_reference": unique_ref,
            }
        ])

        # Execute commit
        resp = self.client.post(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/commit?resource_type=students&conflict_strategy=skip_invalid",
            files={"file": ("commit_test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth,
        )
        self.assertEqual(resp.status_code, 200)
        commit_data = resp.json()

        self.assertEqual(commit_data["status"], "committed")
        self.assertEqual(commit_data["total_processed"], 1)
        self.assertEqual(commit_data["created_count"], 1)
        batch_id = commit_data["batch_id"]
        self.assertTrue(bool(batch_id))

        # Query batch list endpoint to confirm batch history is recorded
        resp_batches = self.client.get(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/batches",
            headers=auth,
        )
        self.assertEqual(resp_batches.status_code, 200)
        batches_data = resp_batches.json()
        batch_ids = [b["id"] for b in batches_data["items"]]
        self.assertIn(batch_id, batch_ids)

    def test_commit_parents_persists_to_postgresql_with_iam_user(self) -> None:
        auth = self._auth(self.founder)
        suffix = datetime.now(timezone.utc).strftime("%H%M%S")
        phone = f"061599{suffix[-4:]}"
        email = f"parent.{suffix}@example.com"

        file_bytes = create_sample_parent_xlsx([
            {
                "full_name": f"Parent Faadumo {suffix}",
                "phone": phone,
                "email": email,
                "address": "Wadajir, Mogadishu",
                "emergency_contact_name": "Emergency Ali",
                "emergency_contact_phone": "0615001122",
                "notes": "VIP Client",
            }
        ])

        resp = self.client.post(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/commit?resource_type=parents&conflict_strategy=skip_invalid",
            files={"file": ("parents_commit.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth,
        )
        self.assertEqual(resp.status_code, 200)
        commit_data = resp.json()

        self.assertEqual(commit_data["status"], "committed")
        self.assertEqual(commit_data["total_processed"], 1)
        self.assertEqual(commit_data["created_count"], 1)
        batch_id = commit_data["batch_id"]
        self.assertTrue(bool(batch_id))

        # Confirm batch in list
        resp_batches = self.client.get(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/batches",
            headers=auth,
        )
        self.assertEqual(resp_batches.status_code, 200)
        batches_data = resp_batches.json()
        self.assertIn(batch_id, [b["id"] for b in batches_data["items"]])

    def test_commit_students_with_parent_relationship_and_duplicate_upsert(self) -> None:
        auth = self._auth(self.founder)
        suffix = datetime.now(timezone.utc).strftime("%H%M%S")
        adm_no = f"ADM-REL-{suffix}"

        # 1. First commit: enroll student with parent
        file_bytes_1 = create_sample_student_xlsx([
            {
                "full_name": f"Student Aadan {suffix}",
                "admission_number": adm_no,
                "grade_level": "Grade 5",
                "parent_name": f"Parent Warsame {suffix}",
                "parent_phone": "0615112233",
                "gender": "male",
                "date_of_birth": "2014-04-12",
                "notes": "Bus 1",
            }
        ])

        resp_1 = self.client.post(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/commit?resource_type=students&conflict_strategy=skip_invalid",
            files={"file": ("student_rel.xlsx", file_bytes_1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth,
        )
        self.assertEqual(resp_1.status_code, 200)
        data_1 = resp_1.json()
        self.assertEqual(data_1["created_count"], 1)
        self.assertEqual(data_1["updated_count"], 0)

        # 2. Second commit: same admission number with updated name and grade (Upsert)
        file_bytes_2 = create_sample_student_xlsx([
            {
                "full_name": f"Student Aadan Updated {suffix}",
                "admission_number": adm_no,
                "grade_level": "Grade 6",
                "gender": "male",
                "date_of_birth": "2014-04-12",
                "notes": "Advanced to Grade 6",
            }
        ])

        resp_2 = self.client.post(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/commit?resource_type=students&conflict_strategy=upsert",
            files={"file": ("student_rel_upsert.xlsx", file_bytes_2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth,
        )
        self.assertEqual(resp_2.status_code, 200)
        data_2 = resp_2.json()
        self.assertEqual(data_2["created_count"], 0)
        self.assertEqual(data_2["updated_count"], 1)
        self.assertEqual(data_2["total_processed"], 1)

    def test_validate_missing_columns_and_in_sheet_duplicate(self) -> None:
        auth = self._auth(self.founder)

        # Missing full_name in one row, duplicate admission number across rows
        file_bytes = create_sample_student_xlsx([
            {
                "full_name": "",
                "admission_number": "ADM-DUP-1",
                "gender": "male",
            },
            {
                "full_name": "Duplicate Student A",
                "admission_number": "ADM-DUP-2",
                "gender": "female",
            },
            {
                "full_name": "Duplicate Student B",
                "admission_number": "ADM-DUP-2",
                "gender": "female",
            },
        ])

        resp = self.client.post(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/validate?resource_type=students",
            files={"file": ("validation_edge.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth,
        )
        self.assertEqual(resp.status_code, 200)
        val_data = resp.json()
        self.assertEqual(val_data["total_rows"], 3)
        self.assertEqual(val_data["valid_rows"], 1)
        self.assertEqual(val_data["invalid_rows"], 2)

        # Row 1 error: full_name required
        # Row 3 error: duplicate admission number
        errors = val_data["errors"]
        error_msgs = [e["error_message"] for e in errors]
        self.assertTrue(any("Full name is required" in m for m in error_msgs))
        self.assertTrue(any("Duplicate admission number" in m for m in error_msgs))

    def test_validate_corrupted_excel_bytes_returns_validation_error(self) -> None:
        auth = self._auth(self.founder)
        corrupted_bytes = b"This is not a real zip or xlsx file."

        resp = self.client.post(
            f"/api/v1/admin/organizations/{EXISTING_ORG_ID}/imports/validate?resource_type=students",
            files={"file": ("corrupted.xlsx", corrupted_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth,
        )
        self.assertEqual(resp.status_code, 422)
        err_data = resp.json()
        error_msg = err_data.get("error", {}).get("message", "") or str(err_data.get("detail", ""))
        self.assertTrue(
            "Invalid or corrupted Excel workbook" in error_msg or "Unable to decode" in error_msg,
            f"Unexpected error response: {err_data}",
        )


if __name__ == "__main__":
    unittest.main()
