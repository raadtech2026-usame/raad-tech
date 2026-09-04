"""Audit finding B12 — `GET /parents/{parent_id}/students` cross-parent ownership guard.

**The shape of the bug this closes.** The route takes `parent_id` straight from the URL and,
until now, checked nothing about whose record it named. It was safe only because of a fact
outside the function: `transport_ops.student_parents.list` happens to be held by
founder/regional_manager/support_staff/org_admin and **not** by `parent`, so no caller who could
abuse it could reach it. That is an accident of the RBAC matrix, not a property of the code — a
single future grant would have turned it into a live cross-parent data leak with no code change
and no test failure anywhere.

ADR-0023 closed this class of bug *structurally* for the parent-facing path (`/me/students` has
no client-supplied identifier at all). This route keeps its path parameter because staff
legitimately query any parent in their scope, so it gets an explicit check instead — and this
file is what stops that check being deleted as "dead code" by someone who notices parents can't
currently reach the route.

The handler is a plain `async def`, so it is called directly here with fakes rather than through
an HTTP client — the guard is the unit under test, not FastAPI's routing.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from raad.core.errors.exceptions import NotFoundError
from raad.core.tenancy.principal import Principal, Role
from raad.modules.transport_ops.api.routers import list_students_for_parent

ORG = "01J8Z3K9G6X8YV5T4N2RAAAAA1"
OWN_PARENT_ID = "01J8Z3K9G6X8YV5T4N2RPPPPP1"
OTHER_PARENT_ID = "01J8Z3K9G6X8YV5T4N2RPPPPP2"
USER_ID = "01J8Z3K9G6X8YV5T4N2REEEEE1"


@dataclass
class _ParentDTO:
    id: str


class _FakeParentService:
    """Stands in for `ParentApplicationService.get_parent_by_user_id`."""

    def __init__(self, parent: _ParentDTO | None) -> None:
        self._parent = parent
        self.calls = 0

    async def get_parent_by_user_id(self, user_id: str, *, uow):  # noqa: ANN001
        self.calls += 1
        return self._parent


@dataclass
class _StudentForParentDTO:
    student_id: str
    full_name: str
    status: str
    relationship: str | None
    is_primary: bool


class _FakeStudentParentService:
    def __init__(self) -> None:
        self.queried_parent_ids: list[str] = []

    async def list_students_for_parent(self, query, *, uow):  # noqa: ANN001
        self.queried_parent_ids.append(query.parent_id)
        return [
            _StudentForParentDTO(
                student_id="01J8Z3K9G6X8YV5T4N2RSSSSS1",
                full_name="Ahmed Ali",
                status="active",
                relationship="father",
                is_primary=True,
            )
        ]


def _principal(role: Role) -> Principal:
    return Principal(user_id=USER_ID, role=role, org_id=ORG)


async def _call(role: Role, parent_id: str, own_parent: _ParentDTO | None):
    parent_service = _FakeParentService(own_parent)
    student_parent_service = _FakeStudentParentService()
    result = await list_students_for_parent(
        parent_id=parent_id,
        principal=_principal(role),
        student_parent_service=student_parent_service,
        parent_service=parent_service,
        uow=object(),
    )
    return result, parent_service, student_parent_service


class ParentStudentsOwnershipGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_parent_may_read_their_own_record(self) -> None:
        result, _, sp = await _call(
            Role.PARENT, OWN_PARENT_ID, _ParentDTO(id=OWN_PARENT_ID)
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(sp.queried_parent_ids, [OWN_PARENT_ID])

    async def test_a_parent_reading_another_parents_record_gets_404(self) -> None:
        """404, not 403 — this codebase's established convention for out-of-scope resource
        access, so a probing caller cannot distinguish "exists but not yours" from "does not
        exist"."""
        with self.assertRaises(NotFoundError):
            await _call(Role.PARENT, OTHER_PARENT_ID, _ParentDTO(id=OWN_PARENT_ID))

    async def test_the_repository_is_never_queried_on_a_denied_request(self) -> None:
        """The guard must run *before* the read, not filter its results afterwards — otherwise
        another parent's children would still have been loaded into memory."""
        parent_service = _FakeParentService(_ParentDTO(id=OWN_PARENT_ID))
        student_parent_service = _FakeStudentParentService()
        with self.assertRaises(NotFoundError):
            await list_students_for_parent(
                parent_id=OTHER_PARENT_ID,
                principal=_principal(Role.PARENT),
                student_parent_service=student_parent_service,
                parent_service=parent_service,
                uow=object(),
            )
        self.assertEqual(student_parent_service.queried_parent_ids, [])

    async def test_a_parent_with_no_linked_record_gets_404(self) -> None:
        with self.assertRaises(NotFoundError):
            await _call(Role.PARENT, OWN_PARENT_ID, None)

    async def test_staff_roles_may_query_any_parent_and_skip_the_lookup(self) -> None:
        """Staff legitimately query any parent within their scope (cross-tenant access is closed
        separately by ADR-0021's repository scoping). They must also not pay for a parent lookup
        that can never apply to them."""
        for role in (
            Role.ORG_ADMIN,
            Role.FOUNDER,
            Role.REGIONAL_MANAGER,
            Role.SUPPORT_STAFF,
        ):
            with self.subTest(role=role):
                result, parent_service, sp = await _call(role, OTHER_PARENT_ID, None)
                self.assertEqual(len(result), 1)
                self.assertEqual(parent_service.calls, 0)
                self.assertEqual(sp.queried_parent_ids, [OTHER_PARENT_ID])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
