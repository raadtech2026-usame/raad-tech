"""Since ADR-0049 every driver row references a real `transport_staff` row
(`drivers.staff_id`, NOT NULL, FK). Integration tests that insert a driver directly create its
staff member in the same Unit of Work through this helper, and delete both with
`DELETE_DRIVERS_AND_STAFF`.
"""

from __future__ import annotations

from raad.core.ids.generator import generate_ulid
from raad.modules.transport_ops.domain.entities import Driver, TransportStaff
from raad.modules.transport_ops.domain.value_objects import TransportStaffId

#: Deletes the drivers and then the staff records they pointed at, in one statement.
DELETE_DRIVERS_AND_STAFF = (
    "WITH d AS (DELETE FROM drivers WHERE id = ANY(:ids) RETURNING staff_id) "
    "DELETE FROM transport_staff WHERE id IN (SELECT staff_id FROM d)"
)


def register_test_driver(uow, *, id, organization_id, user_id, license_no, clock, **kwargs) -> Driver:
    """`Driver.register` plus the staff record it now requires, added to the same UoW."""
    staff = TransportStaff.register(
        id=TransportStaffId(generate_ulid()),
        organization_id=organization_id,
        full_name=f"Test driver {license_no}",
        clock=clock,
    )
    uow.staff.add(staff)
    uow.record_events(staff.pull_domain_events())
    return Driver.register(
        id=id,
        organization_id=organization_id,
        user_id=user_id,
        license_no=license_no,
        staff_id=staff.id,
        clock=clock,
        **kwargs,
    )
