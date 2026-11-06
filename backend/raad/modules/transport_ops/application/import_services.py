"""Bulk data ingestion application service for transport_ops (Students and Parents).

Handles Excel (.xlsx) and CSV template generation, file parsing, dry-run validation
with Somali phone number normalization, duplicate detection, and atomic batch commit.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from raad.core.errors.exceptions import ValidationError
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
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
    StudentId,
    UserId,
)


_PHONE_CLEAN_RE = re.compile(r"[\s\-\.\(\)]")
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d")

STUDENT_TEMPLATE_COLUMNS = [
    ("full_name", "Full Name *", "e.g. Ahmed Ali"),
    ("admission_number", "Admission Number", "e.g. ADM-2026-001"),
    ("grade_level", "Grade Level", "e.g. Grade 7"),
    ("parent_name", "Parent / Guardian Name", "e.g. Ali Farah"),
    ("parent_phone", "Parent Phone", "e.g. 0615123456"),
    ("route_code", "Route Code", "e.g. North Route"),
    ("gender", "Gender", "male or female"),
    ("date_of_birth", "Date of Birth", "YYYY-MM-DD"),
    ("notes", "Notes", "Optional medical or transit notes"),
]

PARENT_TEMPLATE_COLUMNS = [
    ("full_name", "Full Name *", "e.g. Faadumo Jaamac"),
    ("phone", "Phone Number *", "e.g. 0615123456"),
    ("email", "Email Address", "e.g. faadumo@example.com"),
    ("address", "Address", "e.g. Wadajir, Mogadishu"),
    ("emergency_contact_name", "Emergency Contact Name", "e.g. Ali Warsame"),
    ("emergency_contact_phone", "Emergency Contact Phone", "e.g. 0615999888"),
    ("notes", "Notes", "Optional notes"),
]

BUS_MANIFEST_TEMPLATE_COLUMNS = [
    ("bus_name", "Bus Name *", "e.g. Bus 01"),
    ("parent_name", "Parent Full Name *", "e.g. Cali Faarax"),
    ("parent_phone", "Parent Phone *", "e.g. 0615123456"),
    ("parent_email", "Parent Email", "e.g. cali@example.com (Optional)"),
    ("student_1_name", "Student 1 Name *", "e.g. Axmed Cali"),
    ("student_1_fee", "Student 1 Monthly Fee ($)", "e.g. 30.00"),
    ("student_2_name", "Student 2 Name", "e.g. Maryan Cali (Optional)"),
    ("student_2_fee", "Student 2 Monthly Fee ($)", "e.g. 25.00 (Optional)"),
    ("student_3_name", "Student 3 Name", "e.g. Yaasiin Cali (Optional)"),
    ("student_3_fee", "Student 3 Monthly Fee ($)", "e.g. 20.00 (Optional)"),
    ("student_4_name", "Student 4 Name", "Optional"),
    ("student_4_fee", "Student 4 Monthly Fee ($)", "Optional"),
]

BUS_MANIFEST_SAMPLE_ROWS = [
    [
        "Bus 01",
        "Cali Faarax",
        "0615123456",
        "cali.faarax@example.com",
        "Axmed Cali",
        "30.00",
        "Maryan Cali",
        "25.00",
        "",
        "",
        "",
        "",
    ],
    [
        "Bus 01",
        "Faadumo Jaamac",
        "0615998877",
        "",
        "Cabdi Maxamed",
        "35.00",
        "",
        "",
        "",
        "",
        "",
        "",
    ],
    [
        "Bus 02",
        "Xasan Cumar",
        "+252615654321",
        "xasan.cumar@example.com",
        "Khadar Xasan",
        "30.00",
        "Hani Xasan",
        "30.00",
        "Guuleed Xasan",
        "20.00",
        "",
        "",
    ],
]

STUDENT_SAMPLE_ROWS = [
    [
        "Ahmed Ali",
        "ADM-2026-001",
        "Grade 7",
        "Ali Farah",
        "0615123456",
        "North Route",
        "male",
        "2012-05-14",
        "Morning bus",
    ],
    [
        "Maryam Hassan",
        "ADM-2026-002",
        "Grade 8",
        "Hassan Omar",
        "+252615654321",
        "South Route",
        "female",
        "2011-08-22",
        "",
    ],
]

PARENT_SAMPLE_ROWS = [
    [
        "Ali Farah",
        "0615123456",
        "ali.farah@example.com",
        "Wadajir, Mogadishu",
        "Farah Warsame",
        "0615001122",
        "Father",
    ],
    [
        "Hassan Omar",
        "+252615654321",
        "hassan.omar@example.com",
        "Hodan, Mogadishu",
        "Omar Abdi",
        "+252615998877",
        "Guardian",
    ],
]


def normalize_somali_phone(phone_raw: str | None) -> tuple[str | None, str | None]:
    """Normalizes Somali phone numbers automatically to E.164 (+252...).

    Returns (normalized_phone, error_message).
    If phone_raw is empty, returns (None, None).
    """
    if phone_raw is None:
        return None, None
    val = str(phone_raw).strip()
    if not val:
        return None, None

    cleaned = _PHONE_CLEAN_RE.sub("", val)

    if cleaned.startswith("+252"):
        national = cleaned[4:]
    elif cleaned.startswith("00252"):
        national = cleaned[5:]
    elif cleaned.startswith("252") and len(cleaned) >= 10:
        national = cleaned[3:]
    elif cleaned.startswith("0"):
        national = cleaned.lstrip("0")
    else:
        if cleaned.startswith("+"):
            # International number outside Somalia
            if re.match(r"^\+[1-9]\d{6,14}$", cleaned):
                return cleaned, None
            return None, f"Invalid international phone number: '{val}'"
        national = cleaned

    if not national.isdigit() or len(national) not in (8, 9):
        return (
            None,
            f"Invalid Somali phone number '{val}': expected 8 or 9 national digits (e.g. 612345678 or +252612345678)",
        )

    return f"+252{national}", None


def _parse_date(date_val: str | None) -> date | None:
    if not date_val:
        return None
    val_str = str(date_val).strip()
    if not val_str:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(val_str, fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class RowError:
    row_number: int
    column: str
    error_message: str


@dataclass
class RowPreview:
    row_number: int
    is_valid: bool
    data: dict[str, Any]
    errors: list[str]


@dataclass
class ImportValidationResult:
    resource_type: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    errors: list[RowError]
    preview: list[RowPreview]


@dataclass
class ImportCommitResult:
    resource_type: str
    created_count: int
    updated_count: int
    skipped_count: int
    total_processed: int
    errors: list[str]


class ImportApplicationService:
    """Enterprise-grade Bulk Data Ingestion Service for Students and Parents."""

    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        user_provisioning: UserProvisioningPort | None = None,
        student_billing: StudentBillingPort | None = None,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._user_provisioning = user_provisioning
        self._student_billing = student_billing

    def generate_template(
        self, resource_type: str, format_type: str = "xlsx"
    ) -> tuple[bytes, str, str]:
        """Generates downloadable starter template (.xlsx or .csv) with documented column headers."""
        norm_type = resource_type.strip().lower()
        if norm_type not in ("bus_manifest", "students", "parents"):
            raise ValidationError(
                f"Unsupported resource type '{resource_type}'. Supported: 'bus_manifest', 'students', 'parents'."
            )

        norm_format = format_type.strip().lower()
        if norm_format not in ("xlsx", "csv"):
            raise ValidationError(
                f"Unsupported template format '{format_type}'. Supported: 'xlsx', 'csv'."
            )

        if norm_type == "bus_manifest":
            columns = BUS_MANIFEST_TEMPLATE_COLUMNS
            sample_rows = BUS_MANIFEST_SAMPLE_ROWS
            sheet_title = "Bus Ingestion Template"
        elif norm_type == "students":
            columns = STUDENT_TEMPLATE_COLUMNS
            sample_rows = STUDENT_SAMPLE_ROWS
            sheet_title = "Students Template"
        else:
            columns = PARENT_TEMPLATE_COLUMNS
            sample_rows = PARENT_SAMPLE_ROWS
            sheet_title = "Parents Template"

        if norm_format == "xlsx":
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = sheet_title

            header_fill = PatternFill(
                start_color="1E3A8A", end_color="1E3A8A", fill_type="solid"
            )
            header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            example_font = Font(name="Calibri", size=10, italic=True, color="555555")

            # Row 1: Headers
            headers = [col[0] for col in columns]
            for col_idx, header in enumerate(headers, start=1):
                cell = ws.cell(row=1, column=col_idx, value=header)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Row 2: Human Descriptions
            for col_idx, (_, label, desc) in enumerate(columns, start=1):
                cell = ws.cell(row=2, column=col_idx, value=f"{label} ({desc})")
                cell.font = example_font
                cell.alignment = Alignment(horizontal="left", vertical="center")

            # Rows 3..N: Example Data
            for row_idx, sample_row in enumerate(sample_rows, start=3):
                for col_idx, val in enumerate(sample_row, start=1):
                    ws.cell(row=row_idx, column=col_idx, value=val)

            for col_idx in range(1, len(columns) + 1):
                col_letter = get_column_letter(col_idx)
                ws.column_dimensions[col_letter].width = 24

            output = io.BytesIO()
            wb.save(output)
            return (
                output.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                f"{norm_type}_import_template.xlsx",
            )
        else:
            output = io.StringIO()
            writer = csv.writer(output)
            # Headers
            writer.writerow([col[0] for col in columns])
            # Sample rows
            for sample_row in sample_rows:
                writer.writerow(sample_row)

            return (
                output.getvalue().encode("utf-8"),
                "text/csv",
                f"{norm_type}_import_template.csv",
            )

    def _parse_file(self, file_bytes: bytes, filename: str) -> list[tuple[int, dict[str, str]]]:
        """Parses CSV or Excel bytes into a list of (row_number, row_dict)."""
        filename_lower = filename.lower()
        rows: list[tuple[int, dict[str, str]]] = []

        if filename_lower.endswith(".xlsx") or file_bytes.startswith(b"PK"):
            try:
                wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            except Exception as exc:
                raise ValidationError(f"Invalid or corrupted Excel workbook: {exc}") from exc
            ws = wb.active
            if ws is None:
                raise ValidationError("Excel workbook contains no active worksheet.")
            header_keys: list[str] = []
            for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                if row_idx == 1:
                    header_keys = [
                        str(cell).strip().lower().replace(" ", "_").replace("-", "_")
                        if cell is not None
                        else f"col_{idx}"
                        for idx, cell in enumerate(row)
                    ]
                    continue

                # Skip human description row if present (e.g. contains 'e.g.')
                row_values = [str(c).strip() if c is not None else "" for c in row]
                if not any(row_values):
                    continue
                if row_idx == 2 and any("e.g." in v.lower() for v in row_values):
                    continue

                row_dict = {}
                for h, val in zip(header_keys, row_values):
                    if h:
                        row_dict[h] = val
                rows.append((row_idx, row_dict))
        else:
            text: str | None = None
            for enc in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    text = file_bytes.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if text is None:
                raise ValidationError("Unable to decode uploaded file. Please provide UTF-8 encoded CSV or Excel.")

            reader = csv.reader(io.StringIO(text))
            header_keys = []
            for row_idx, raw_row in enumerate(reader, start=1):
                if row_idx == 1:
                    header_keys = [
                        col.strip().lower().replace(" ", "_").replace("-", "_")
                        for col in raw_row
                    ]
                    continue
                row_values = [col.strip() for col in raw_row]
                if not any(row_values):
                    continue
                if row_idx == 2 and any("e.g." in v.lower() for v in row_values):
                    continue

                row_dict = {}
                for h, val in zip(header_keys, row_values):
                    if h:
                        row_dict[h] = val
                rows.append((row_idx, row_dict))

        return rows

    def _normalize_row_keys(self, raw_dict: dict[str, str]) -> dict[str, str]:
        """Maps column aliases to standardized keys."""
        normalized: dict[str, str] = {}
        alias_map = {
            "name": "full_name",
            "student_name": "full_name",
            "student_full_name": "full_name",
            "parent_full_name": "full_name",
            "guardian_name": "parent_name",
            "guardian_phone": "parent_phone",
            "admission_no": "admission_number",
            "student_id": "admission_number",
            "external_ref": "admission_number",
            "grade": "grade_level",
            "class": "grade_level",
            "route": "route_code",
            "route_name": "route_code",
            "dob": "date_of_birth",
            "birth_date": "date_of_birth",
            "sex": "gender",
            "phone_number": "phone",
            "mobile": "phone",
            "email_address": "email",
            "home_address": "address",
            "emergency_name": "emergency_contact_name",
            "emergency_phone": "emergency_contact_phone",
        }
        for k, v in raw_dict.items():
            clean_k = alias_map.get(k, k)
            normalized[clean_k] = v
        return normalized

    async def validate_import(
        self,
        resource_type: str,
        file_bytes: bytes,
        filename: str,
        organization_id: str,
        *,
        uow: TransportOpsUnitOfWork,
    ) -> ImportValidationResult:
        """Dry-run validation of the uploaded file without persisting to DB."""
        norm_type = resource_type.strip().lower()
        if norm_type not in ("bus_manifest", "students", "parents"):
            raise ValidationError(
                f"Unsupported resource type '{resource_type}'. Supported: 'bus_manifest', 'students', 'parents'."
            )

        if not file_bytes:
            raise ValidationError("Uploaded file is empty.")

        parsed_rows = self._parse_file(file_bytes, filename)
        if not parsed_rows:
            raise ValidationError("File contains no data rows.")

        errors: list[RowError] = []
        previews: list[RowPreview] = []

        seen_admission_numbers: dict[str, int] = {}
        seen_phones: dict[str, int] = {}
        seen_emails: dict[str, int] = {}

        # Fetch existing routes for route_code verification
        async with uow:
            existing_routes = await uow.routes.list_all()
            route_names = {r.name.lower(): r for r in existing_routes}

        for row_num, raw_dict in parsed_rows:
            row_data = self._normalize_row_keys(raw_dict)
            row_errors: list[str] = []

            if norm_type in ("students", "parents"):
                # 1. Full name validation
                full_name = row_data.get("full_name", "").strip()
                if not full_name:
                    err = "Full name is required."
                    row_errors.append(err)
                    errors.append(RowError(row_num, "full_name", err))

            if norm_type == "students":
                # Admission number duplicate in file
                adm_no = row_data.get("admission_number", "").strip()
                if adm_no:
                    if adm_no in seen_admission_numbers:
                        first_row = seen_admission_numbers[adm_no]
                        err = f"Duplicate admission number '{adm_no}' (already in row {first_row})."
                        row_errors.append(err)
                        errors.append(RowError(row_num, "admission_number", err))
                    else:
                        seen_admission_numbers[adm_no] = row_num

                # Somali phone normalization for parent_phone
                parent_phone = row_data.get("parent_phone", "").strip()
                if parent_phone:
                    norm_phone, phone_err = normalize_somali_phone(parent_phone)
                    if phone_err:
                        row_errors.append(phone_err)
                        errors.append(RowError(row_num, "parent_phone", phone_err))
                    else:
                        row_data["parent_phone"] = norm_phone or ""

                # Route validation
                route_code = row_data.get("route_code", "").strip()
                if route_code and route_code.lower() not in route_names:
                    err = f"Route '{route_code}' does not exist in your organization."
                    row_errors.append(err)
                    errors.append(RowError(row_num, "route_code", err))

                # Gender validation
                gender = row_data.get("gender", "").strip().lower()
                if gender and gender not in ("male", "female", "other"):
                    err = f"Invalid gender '{gender}'. Expected 'male', 'female', or 'other'."
                    row_errors.append(err)
                    errors.append(RowError(row_num, "gender", err))

                # Date of birth validation
                dob_raw = row_data.get("date_of_birth", "").strip()
                if dob_raw:
                    parsed_dob = _parse_date(dob_raw)
                    if not parsed_dob:
                        err = f"Invalid date of birth format '{dob_raw}'. Expected YYYY-MM-DD."
                        row_errors.append(err)
                        errors.append(RowError(row_num, "date_of_birth", err))

            elif norm_type == "parents":
                phone = row_data.get("phone", "").strip()
                email = row_data.get("email", "").strip()

                if not phone and not email:
                    err = "At least one contact method (phone or email) is required."
                    row_errors.append(err)
                    errors.append(RowError(row_num, "phone", err))

                if phone:
                    norm_phone, phone_err = normalize_somali_phone(phone)
                    if phone_err:
                        row_errors.append(phone_err)
                        errors.append(RowError(row_num, "phone", phone_err))
                    else:
                        row_data["phone"] = norm_phone or ""
                        if norm_phone in seen_phones:
                            first_row = seen_phones[norm_phone]
                            err = f"Duplicate phone '{norm_phone}' (already in row {first_row})."
                            row_errors.append(err)
                            errors.append(RowError(row_num, "phone", err))
                        else:
                            seen_phones[norm_phone] = row_num

                if email:
                    if "@" not in email or "." not in email:
                        err = f"Invalid email format: '{email}'."
                        row_errors.append(err)
                        errors.append(RowError(row_num, "email", err))
                    elif email.lower() in seen_emails:
                        first_row = seen_emails[email.lower()]
                        err = f"Duplicate email '{email}' (already in row {first_row})."
                        row_errors.append(err)
                        errors.append(RowError(row_num, "email", err))
                    else:
                        seen_emails[email.lower()] = row_num

                em_phone = row_data.get("emergency_contact_phone", "").strip()
                if em_phone:
                    norm_em_phone, em_err = normalize_somali_phone(em_phone)
                    if em_err:
                        row_errors.append(em_err)
                        errors.append(RowError(row_num, "emergency_contact_phone", em_err))
                    else:
                        row_data["emergency_contact_phone"] = norm_em_phone or ""

            elif norm_type == "bus_manifest":
                bus_name = str(row_data.get("bus_name") or row_data.get("route_code") or "").strip()
                if not bus_name:
                    err = "Bus Name is required."
                    row_errors.append(err)
                    errors.append(RowError(row_num, "bus_name", err))

                parent_name = str(row_data.get("parent_name") or row_data.get("full_name") or "").strip()
                if not parent_name:
                    err = "Parent full name is required."
                    row_errors.append(err)
                    errors.append(RowError(row_num, "parent_name", err))

                parent_phone = str(row_data.get("parent_phone") or row_data.get("phone") or "").strip()
                if not parent_phone:
                    err = "Parent phone number is required."
                    row_errors.append(err)
                    errors.append(RowError(row_num, "parent_phone", err))
                else:
                    norm_phone, phone_err = normalize_somali_phone(parent_phone)
                    if phone_err:
                        row_errors.append(phone_err)
                        errors.append(RowError(row_num, "parent_phone", phone_err))
                    else:
                        row_data["parent_phone"] = norm_phone or ""

                parent_email = str(row_data.get("parent_email") or row_data.get("email") or "").strip()
                if parent_email:
                    if "@" not in parent_email or "." not in parent_email:
                        err = f"Invalid email format: '{parent_email}'."
                        row_errors.append(err)
                        errors.append(RowError(row_num, "parent_email", err))

                # Extract children (supports multi-column student_1_name..student_10_name and single student_name)
                children: list[dict[str, Any]] = []
                for i in range(1, 11):
                    c_name = str(row_data.get(f"student_{i}_name", "") or "").strip()
                    c_fee_raw = str(row_data.get(f"student_{i}_fee", "") or "").strip()
                    if c_name:
                        fee_val = Decimal("0.00")
                        if c_fee_raw:
                            try:
                                fee_clean = c_fee_raw.replace("$", "").replace(",", "").strip()
                                fee_val = Decimal(fee_clean)
                                if fee_val < 0:
                                    err = f"Fee for student '{c_name}' cannot be negative: '{c_fee_raw}'."
                                    row_errors.append(err)
                                    errors.append(RowError(row_num, f"student_{i}_fee", err))
                            except Exception:
                                err = f"Invalid fee amount for student '{c_name}': '{c_fee_raw}'."
                                row_errors.append(err)
                                errors.append(RowError(row_num, f"student_{i}_fee", err))
                        children.append({"name": c_name, "fee": fee_val})

                if not children:
                    single_name = str(row_data.get("student_name", "") or "").strip()
                    single_fee_raw = str(row_data.get("student_fee", "") or row_data.get("fee", "") or "").strip()
                    if single_name:
                        fee_val = Decimal("0.00")
                        if single_fee_raw:
                            try:
                                fee_clean = single_fee_raw.replace("$", "").replace(",", "").strip()
                                fee_val = Decimal(fee_clean)
                                if fee_val < 0:
                                    err = f"Fee for student '{single_name}' cannot be negative: '{single_fee_raw}'."
                                    row_errors.append(err)
                                    errors.append(RowError(row_num, "student_fee", err))
                            except Exception:
                                err = f"Invalid fee amount for student '{single_name}': '{single_fee_raw}'."
                                row_errors.append(err)
                                errors.append(RowError(row_num, "student_fee", err))
                        children.append({"name": single_name, "fee": fee_val})

                if not children:
                    err = "At least one student name is required."
                    row_errors.append(err)
                    errors.append(RowError(row_num, "student_1_name", err))
                else:
                    row_data["children"] = children

            is_valid = len(row_errors) == 0
            previews.append(
                RowPreview(
                    row_number=row_num,
                    is_valid=is_valid,
                    data=row_data,
                    errors=row_errors,
                )
            )

        valid_count = sum(1 for p in previews if p.is_valid)
        invalid_count = len(previews) - valid_count

        return ImportValidationResult(
            resource_type=norm_type,
            total_rows=len(previews),
            valid_rows=valid_count,
            invalid_rows=invalid_count,
            errors=errors,
            preview=previews,
        )

    async def commit_import(
        self,
        resource_type: str,
        file_bytes: bytes,
        filename: str,
        organization_id: str,
        principal: Principal,
        *,
        uow: TransportOpsUnitOfWork,
    ) -> ImportCommitResult:
        """Atomic batch upsert/insert in a single database transaction.

        If any fatal constraint fails, rolls back cleanly.
        """
        validation = await self.validate_import(
            resource_type,
            file_bytes,
            filename,
            organization_id,
            uow=uow,
        )

        norm_type = resource_type.strip().lower()
        created_count = 0
        updated_count = 0
        skipped_count = 0
        fatal_errors: list[str] = []

        async with uow:
            # Load existing records in org scope
            existing_students = await uow.students.list_all()
            students_by_ref = {
                s.external_ref: s for s in existing_students if s.external_ref
            }

            existing_parents = await uow.parents.list_all()
            parents_by_phone = {
                str(p.phone): p for p in existing_parents if p.phone
            }

            existing_routes = await uow.routes.list_all()
            routes_by_name = {r.name.lower(): r for r in existing_routes}

            for preview in validation.preview:
                if not preview.is_valid:
                    skipped_count += 1
                    continue

                row_data = preview.data

                if norm_type in ("students", "parents"):
                    full_name = row_data.get("full_name", "")

                if norm_type == "students":
                    adm_no = row_data.get("admission_number", "").strip() or None
                    grade = row_data.get("grade_level", "").strip()
                    parent_name = row_data.get("parent_name", "").strip()
                    parent_phone = row_data.get("parent_phone", "").strip()
                    route_code = row_data.get("route_code", "").strip()
                    gender_str = row_data.get("gender", "").strip().lower()
                    dob = _parse_date(row_data.get("date_of_birth"))
                    user_notes = row_data.get("notes", "").strip()

                    notes_parts = []
                    if grade:
                        notes_parts.append(f"Grade: {grade}")
                    if user_notes:
                        notes_parts.append(user_notes)
                    combined_notes = " | ".join(notes_parts) if notes_parts else None

                    gender_val = Gender(gender_str) if gender_str in ("male", "female", "other") else None

                    if adm_no and adm_no in students_by_ref:
                        # Existing student -> update
                        student = students_by_ref[adm_no]
                        student.update_details(
                            full_name=full_name,
                            external_ref=adm_no,
                            date_of_birth=dob or student.date_of_birth,
                            gender=gender_val or student.gender,
                            notes=combined_notes or student.notes,
                            clock=self._clock,
                            actor_id=principal.user_id,
                        )
                        uow.record_events(student.pull_domain_events())
                        updated_count += 1
                    else:
                        # New student -> enroll
                        student = Student.enroll(
                            id=StudentId(self._id_generator.new_id()),
                            organization_id=OrganizationId(organization_id),
                            full_name=full_name,
                            external_ref=adm_no,
                            date_of_birth=dob,
                            gender=gender_val,
                            notes=combined_notes,
                            clock=self._clock,
                            actor_id=principal.user_id,
                        )
                        uow.students.add(student)
                        uow.record_events(student.pull_domain_events())
                        if adm_no:
                            students_by_ref[adm_no] = student
                        created_count += 1

                    # Parent linking if parent_phone or parent_name provided
                    if parent_phone or parent_name:
                        matched_parent: Parent | None = None
                        if parent_phone and parent_phone in parents_by_phone:
                            matched_parent = parents_by_phone[parent_phone]
                        elif parent_name:
                            # Provision parent user & aggregate
                            p_user_id: str
                            if self._user_provisioning:
                                p_user_id, _ = (
                                    await self._user_provisioning.create_user_with_temporary_password(
                                        organization_id=organization_id,
                                        role=Role.PARENT,
                                        email=None,
                                        phone=parent_phone or None,
                                        full_name=parent_name,
                                        actor=principal,
                                    )
                                )
                            else:
                                p_user_id = self._id_generator.new_id()

                            matched_parent = Parent.register(
                                id=ParentId(self._id_generator.new_id()),
                                organization_id=OrganizationId(organization_id),
                                user_id=UserId(p_user_id),
                                full_name=parent_name,
                                phone=PhoneNumber(parent_phone) if parent_phone else None,
                                clock=self._clock,
                                actor_id=principal.user_id,
                            )
                            uow.parents.add(matched_parent)
                            uow.record_events(matched_parent.pull_domain_events())
                            if parent_phone:
                                parents_by_phone[parent_phone] = matched_parent

                        if matched_parent is not None:
                            existing_link = await uow.student_parents.get(
                                student.id, matched_parent.id
                            )
                            if existing_link is None:
                                link = StudentParent.link(
                                    student_id=student.id,
                                    student_organization_id=student.organization_id,
                                    parent_id=matched_parent.id,
                                    parent_organization_id=matched_parent.organization_id,
                                    relationship="Parent",
                                    is_primary=True,
                                    clock=self._clock,
                                    actor_id=principal.user_id,
                                )
                                uow.student_parents.add(link)

                elif norm_type == "parents":
                    phone = row_data.get("phone", "").strip() or None
                    email = row_data.get("email", "").strip() or None
                    address = row_data.get("address", "").strip() or None
                    em_name = row_data.get("emergency_contact_name", "").strip() or None
                    em_phone = row_data.get("emergency_contact_phone", "").strip() or None
                    notes = row_data.get("notes", "").strip() or None

                    if phone and phone in parents_by_phone:
                        # Existing parent -> update
                        parent = parents_by_phone[phone]
                        parent.update_details(
                            full_name=full_name,
                            phone=PhoneNumber(phone) if phone else parent.phone,
                            address=address or parent.address,
                            emergency_contact_name=em_name or parent.emergency_contact_name,
                            emergency_contact_phone=PhoneNumber(em_phone)
                            if em_phone
                            else parent.emergency_contact_phone,
                            notes=notes or parent.notes,
                            clock=self._clock,
                            actor_id=principal.user_id,
                        )
                        uow.record_events(parent.pull_domain_events())
                        updated_count += 1
                    else:
                        # New parent -> register
                        user_id: str
                        if self._user_provisioning:
                            user_id, _ = (
                                await self._user_provisioning.create_user_with_temporary_password(
                                    organization_id=organization_id,
                                    role=Role.PARENT,
                                    email=email,
                                    phone=phone,
                                    full_name=full_name,
                                    actor=principal,
                                )
                            )
                        else:
                            user_id = self._id_generator.new_id()

                        parent = Parent.register(
                            id=ParentId(self._id_generator.new_id()),
                            organization_id=OrganizationId(organization_id),
                            user_id=UserId(user_id),
                            full_name=full_name,
                            phone=PhoneNumber(phone) if phone else None,
                            address=address,
                            emergency_contact_name=em_name,
                            emergency_contact_phone=PhoneNumber(em_phone) if em_phone else None,
                            notes=notes,
                            clock=self._clock,
                            actor_id=principal.user_id,
                        )
                        uow.parents.add(parent)
                        uow.record_events(parent.pull_domain_events())
                        if phone:
                            parents_by_phone[phone] = parent
                        created_count += 1

                elif norm_type == "bus_manifest":
                    bus_name = str(row_data.get("bus_name") or row_data.get("route_code") or "").strip()
                    parent_name = str(row_data.get("parent_name") or row_data.get("full_name") or "").strip()
                    parent_phone = row_data.get("parent_phone", "").strip()
                    parent_email = str(row_data.get("parent_email") or row_data.get("email") or "").strip() or None
                    children = row_data.get("children", [])

                    # 1. Bus / Route lookup or auto-creation
                    route: Route
                    if bus_name.lower() in routes_by_name:
                        route = routes_by_name[bus_name.lower()]
                    else:
                        route = Route.create(
                            id=RouteId(self._id_generator.new_id()),
                            organization_id=OrganizationId(organization_id),
                            name=bus_name,
                            clock=self._clock,
                            actor_id=principal.user_id,
                        )
                        uow.routes.add(route)
                        uow.record_events(route.pull_domain_events())
                        routes_by_name[bus_name.lower()] = route

                    # 2. Parent lookup or auto-registration
                    parent: Parent
                    if parent_phone and parent_phone in parents_by_phone:
                        parent = parents_by_phone[parent_phone]
                    else:
                        # Provision IAM user with initial password "1234"
                        user_id: str
                        if self._user_provisioning:
                            user_id, _ = await self._user_provisioning.create_user_with_temporary_password(
                                organization_id=organization_id,
                                role=Role.PARENT,
                                email=parent_email,
                                phone=parent_phone,
                                full_name=parent_name,
                                actor=principal,
                                initial_password="1234",
                            )
                        else:
                            user_id = self._id_generator.new_id()

                        parent = Parent.register(
                            id=ParentId(self._id_generator.new_id()),
                            organization_id=OrganizationId(organization_id),
                            user_id=UserId(user_id),
                            full_name=parent_name,
                            phone=PhoneNumber(parent_phone) if parent_phone else None,
                            clock=self._clock,
                            actor_id=principal.user_id,
                        )
                        uow.parents.add(parent)
                        uow.record_events(parent.pull_domain_events())
                        if parent_phone:
                            parents_by_phone[parent_phone] = parent
                        created_count += 1

                    # 3. Children enrollment, parent linking, and billing setup
                    for child in children:
                        child_name = child["name"]
                        child_fee = child["fee"]

                        student = Student.enroll(
                            id=StudentId(self._id_generator.new_id()),
                            organization_id=OrganizationId(organization_id),
                            full_name=child_name,
                            notes=f"Bus: {bus_name}",
                            clock=self._clock,
                            actor_id=principal.user_id,
                        )
                        uow.students.add(student)
                        uow.record_events(student.pull_domain_events())
                        created_count += 1

                        link = StudentParent.link(
                            student_id=student.id,
                            student_organization_id=student.organization_id,
                            parent_id=parent.id,
                            parent_organization_id=parent.organization_id,
                            relationship="Parent",
                            is_primary=True,
                            clock=self._clock,
                            actor_id=principal.user_id,
                        )
                        uow.student_parents.add(link)

                        if child_fee is not None and self._student_billing:
                            try:
                                await self._student_billing.set_student_monthly_fee(
                                    organization_id=organization_id,
                                    student_id=str(student.id),
                                    monthly_fee=child_fee,
                                    currency="USD",
                                    actor=principal,
                                )
                            except Exception:
                                pass

            # Single atomic commit for the batch
            await uow.commit()

        return ImportCommitResult(
            resource_type=norm_type,
            created_count=created_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            total_processed=len(validation.preview),
            errors=fatal_errors,
        )
