"""The staff API's edge: request models and private-field masking (ADR-0049 §6, ADR-0051 §2).

Unit tests call application services directly and never build a request model, so anything that
lives only in a schema or a router helper is untested unless tested here.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from pydantic import ValidationError as PydanticValidationError

from raad.core.errors.exceptions import ValidationError
from raad.core.tenancy.principal import Principal, Role
from raad.modules.transport_ops.api.routers import (
    _document_to_response,
    _resolve_organization_id,
    _staff_to_response,
)
from raad.modules.transport_ops.api.schemas import (
    AssignStaffToVehicleRequest,
    StaffDocumentTypeRequest,
    UpdateStaffDocumentRequest,
    UpdateTransportStaffRequest,
)
from raad.modules.transport_ops.application.queries import StaffDocumentDTO, TransportStaffDTO

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
ORG = "01J8Z3K9G6X8YV5T4N2R7QW3MD"


def _staff_dto() -> TransportStaffDTO:
    return TransportStaffDTO(
        id="s1",
        organization_id=ORG,
        full_name="Amina Warsame",
        phone="+252611234567",
        alternate_phone=None,
        role_id=None,
        role_name=None,
        employee_ref=None,
        start_date=None,
        status="active",
        emergency_contact_name="Hodan",
        emergency_contact_phone="+252617654321",
        notes=None,
        left_on=None,
        driver=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _document_dto() -> StaffDocumentDTO:
    return StaffDocumentDTO(
        id="d1",
        organization_id=ORG,
        staff_id="s1",
        staff_name="Amina Warsame",
        type_id="t1",
        type_name="Driving licence",
        number="DL-123",
        issued_on=None,
        expires_on=date(2026, 10, 10),
        notes=None,
        status="expiring",
        days_left=10,
        replaced_by_id=None,
        created_at=NOW,
    )


ORG_ADMIN = Principal(user_id="a", role=Role.ORG_ADMIN, org_id=ORG)
READ_ONLY_ROLES = (
    Principal(user_id="f", role=Role.FOUNDER, org_id=None),
    Principal(user_id="r", role=Role.REGIONAL_MANAGER, org_id=None),
    Principal(user_id="s", role=Role.SUPPORT_STAFF, org_id=None),
)


class PrivateFieldMaskingTests(unittest.TestCase):
    def test_org_admin_sees_emergency_contact_and_document_number(self) -> None:
        staff = _staff_to_response(_staff_dto(), ORG_ADMIN)
        self.assertEqual(staff.emergency_contact_name, "Hodan")
        self.assertTrue(staff.private_fields_visible)
        self.assertEqual(_document_to_response(_document_dto(), ORG_ADMIN).number, "DL-123")

    def test_raad_staff_never_receive_them(self) -> None:
        for principal in READ_ONLY_ROLES:
            with self.subTest(role=principal.role):
                staff = _staff_to_response(_staff_dto(), principal)
                self.assertIsNone(staff.emergency_contact_name)
                self.assertIsNone(staff.emergency_contact_phone)
                self.assertFalse(staff.private_fields_visible)
                self.assertEqual(staff.full_name, "Amina Warsame")
                document = _document_to_response(_document_dto(), principal)
                self.assertIsNone(document.number)
                self.assertNotIn("DL-123", document.model_dump_json())


class RequestModelTests(unittest.TestCase):
    def test_partial_update_distinguishes_absent_from_null(self) -> None:
        body = UpdateTransportStaffRequest.model_validate({"phone": None, "notes": "x"})
        self.assertEqual(body.model_dump(include=body.model_fields_set), {"phone": None, "notes": "x"})
        doc = UpdateStaffDocumentRequest.model_validate({"expires_on": "2027-01-01"})
        self.assertEqual(
            doc.model_dump(include=doc.model_fields_set), {"expires_on": date(2027, 1, 1)}
        )

    def test_assignment_kind_is_closed(self) -> None:
        with self.assertRaises(PydanticValidationError):
            AssignStaffToVehicleRequest(staff_id="s", vehicle_id="v", kind="forever")
        self.assertEqual(AssignStaffToVehicleRequest(staff_id="s", vehicle_id="v").kind, "permanent")

    def test_document_type_defaults_to_30_and_7_days(self) -> None:
        self.assertEqual(StaffDocumentTypeRequest(name="Licence").alert_lead_days, [30, 7])

    def test_organization_is_the_org_admins_own_or_must_be_named(self) -> None:
        self.assertEqual(_resolve_organization_id(ORG_ADMIN, None), ORG)
        with self.assertRaises(ValidationError):
            _resolve_organization_id(READ_ONLY_ROLES[0], None)


if __name__ == "__main__":
    unittest.main()
