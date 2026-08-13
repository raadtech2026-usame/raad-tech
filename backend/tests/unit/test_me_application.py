"""Unit tests for `iam.application.services.MeApplicationService` (ADR-0023 — closes
`PROJECT_STATUS.md` Known Issue #17). Stdlib `unittest` — no `pytest`. Fake doubles for the
three constructor-injected `transport_ops` application services, mirroring
`test_platform_stats_application.py`'s pattern exactly: this service takes its dependencies as
plain constructor arguments (not resolved from a `Container`), so plain fakes recording what
they were called with are enough — no DI-container-binding trick needed.

The load-bearing assertion throughout: every fake records the *exact* `user_id`/`parent_id`
it was called with, so each test can prove the only identity ever used is the one derived from
the given `Principal` — never a client-supplied id, since these methods have no such parameter
to accept in the first place.
"""

from __future__ import annotations

import unittest

from raad.core.errors.exceptions import NotFoundError
from raad.core.tenancy.principal import Principal, Role
from raad.modules.iam.application.services import MeApplicationService
from raad.modules.transport_ops.application.queries import (
    DriverDTO,
    ListStudentsForParentQuery,
    ParentDTO,
    StudentForParentDTO,
)


def _parent_dto(
    *,
    id: str = "parent-1",
    user_id: str = "user-parent-1",
    has_video_live_access: bool = False,
    has_video_playback_access: bool = False,
) -> ParentDTO:
    return ParentDTO(
        id=id,
        organization_id="org-1",
        user_id=user_id,
        full_name="Parent One",
        phone=None,
        status="active",
        has_video_live_access=has_video_live_access,
        has_video_playback_access=has_video_playback_access,
        created_at=None,  # type: ignore[arg-type]
        updated_at=None,  # type: ignore[arg-type]
    )


def _driver_dto(*, id: str = "driver-1", user_id: str = "user-driver-1") -> DriverDTO:
    return DriverDTO(
        id=id,
        organization_id="org-1",
        user_id=user_id,
        license_no="LIC-1",
        status="active",
        created_at=None,  # type: ignore[arg-type]
        updated_at=None,  # type: ignore[arg-type]
    )


class _FakeParentService:
    def __init__(self, *, by_user_id: dict[str, ParentDTO] | None = None) -> None:
        self._by_user_id = by_user_id or {}
        self.calls: list[dict] = []

    async def get_parent_by_user_id(self, user_id: str, *, uow) -> ParentDTO | None:
        self.calls.append({"user_id": user_id, "uow": uow})
        return self._by_user_id.get(user_id)


class _FakeDriverService:
    def __init__(self, *, by_user_id: dict[str, DriverDTO] | None = None) -> None:
        self._by_user_id = by_user_id or {}
        self.calls: list[dict] = []

    async def get_driver_by_user_id(self, user_id: str, *, uow) -> DriverDTO | None:
        self.calls.append({"user_id": user_id, "uow": uow})
        return self._by_user_id.get(user_id)


class _FakeStudentParentService:
    def __init__(
        self, *, by_parent_id: dict[str, list[StudentForParentDTO]] | None = None
    ) -> None:
        self._by_parent_id = by_parent_id or {}
        self.calls: list[dict] = []

    async def list_students_for_parent(
        self, query: ListStudentsForParentQuery, *, uow
    ) -> list[StudentForParentDTO]:
        self.calls.append({"parent_id": query.parent_id, "uow": uow})
        return self._by_parent_id.get(query.parent_id, [])


def make_service(
    *,
    parents: dict[str, ParentDTO] | None = None,
    drivers: dict[str, DriverDTO] | None = None,
    students_by_parent: dict[str, list[StudentForParentDTO]] | None = None,
) -> tuple[
    MeApplicationService, _FakeParentService, _FakeDriverService, _FakeStudentParentService
]:
    parent_service = _FakeParentService(by_user_id=parents)
    driver_service = _FakeDriverService(by_user_id=drivers)
    student_parent_service = _FakeStudentParentService(by_parent_id=students_by_parent)
    service = MeApplicationService(
        parent_service=parent_service,
        driver_service=driver_service,
        student_parent_service=student_parent_service,
    )
    return service, parent_service, driver_service, student_parent_service


class MeIdentityResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_parent_principal_resolves_parent_id_and_leaves_driver_id_null(self) -> None:
        principal = Principal(user_id="user-parent-1", role=Role.PARENT, org_id="org-1")
        service, parent_service, driver_service, _sp = make_service(
            parents={"user-parent-1": _parent_dto(id="parent-1", user_id="user-parent-1")}
        )

        identity = await service.get_my_identity(principal, uow="uow")

        self.assertEqual(identity.user_id, "user-parent-1")
        self.assertEqual(identity.role, "PARENT")
        self.assertEqual(identity.organization_id, "org-1")
        self.assertEqual(identity.parent_id, "parent-1")
        self.assertIsNone(identity.driver_id)
        # Only the PARENT lookup should ever run - resolving DRIVER too would be a wasted query.
        self.assertEqual(len(driver_service.calls), 0)
        self.assertEqual(parent_service.calls[0]["user_id"], "user-parent-1")
        # ADR-0026 §5: no grant on this fixture parent - both flags stay false.
        self.assertFalse(identity.has_video_live_access)
        self.assertFalse(identity.has_video_playback_access)

    async def test_granted_parent_surfaces_video_access_flags(self) -> None:
        """ADR-0026 §5: `GET /me` is the mobile client's only way to know whether to show the
        video affordance at all - must reflect a real grant, not always default to false."""
        principal = Principal(user_id="user-parent-1", role=Role.PARENT, org_id="org-1")
        service, _parent_service, _driver_service, _sp = make_service(
            parents={
                "user-parent-1": _parent_dto(
                    id="parent-1",
                    user_id="user-parent-1",
                    has_video_live_access=True,
                    has_video_playback_access=False,
                )
            }
        )

        identity = await service.get_my_identity(principal, uow="uow")

        self.assertTrue(identity.has_video_live_access)
        self.assertFalse(identity.has_video_playback_access)

    async def test_driver_principal_resolves_driver_id_and_leaves_parent_id_null(self) -> None:
        principal = Principal(user_id="user-driver-1", role=Role.DRIVER, org_id="org-1")
        service, parent_service, driver_service, _sp = make_service(
            drivers={"user-driver-1": _driver_dto(id="driver-1", user_id="user-driver-1")}
        )

        identity = await service.get_my_identity(principal, uow="uow")

        self.assertEqual(identity.driver_id, "driver-1")
        self.assertIsNone(identity.parent_id)
        self.assertEqual(len(parent_service.calls), 0)
        self.assertEqual(driver_service.calls[0]["user_id"], "user-driver-1")

    async def test_parent_role_with_no_linked_parent_row_returns_null_not_an_error(self) -> None:
        """A data-inconsistency case (role says PARENT, no Parent row exists) - /me stays
        defensive and returns null rather than raising, unlike the dedicated sub-resource
        routes below."""
        principal = Principal(user_id="user-orphan", role=Role.PARENT, org_id="org-1")
        service, *_rest = make_service(parents={})

        identity = await service.get_my_identity(principal, uow="uow")

        self.assertIsNone(identity.parent_id)

    async def test_org_admin_principal_needs_no_secondary_lookup_at_all(self) -> None:
        principal = Principal(user_id="user-admin-1", role=Role.ORG_ADMIN, org_id="org-1")
        service, parent_service, driver_service, _sp = make_service()

        identity = await service.get_my_identity(principal, uow="uow")

        self.assertIsNone(identity.parent_id)
        self.assertIsNone(identity.driver_id)
        self.assertEqual(identity.organization_id, "org-1")
        self.assertEqual(len(parent_service.calls), 0)
        self.assertEqual(len(driver_service.calls), 0)

    async def test_founder_principal_has_no_organization_and_no_secondary_identity(self) -> None:
        principal = Principal(user_id="user-founder-1", role=Role.FOUNDER, org_id=None)
        service, *_rest = make_service()

        identity = await service.get_my_identity(principal, uow="uow")

        self.assertIsNone(identity.organization_id)
        self.assertIsNone(identity.parent_id)
        self.assertIsNone(identity.driver_id)


class MeStudentsOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_students_only_through_the_callers_own_resolved_parent_id(
        self,
    ) -> None:
        principal = Principal(user_id="user-parent-1", role=Role.PARENT, org_id="org-1")
        service, parent_service, _driver, student_parent_service = make_service(
            parents={"user-parent-1": _parent_dto(id="parent-1", user_id="user-parent-1")},
            students_by_parent={
                "parent-1": [
                    StudentForParentDTO(
                        student_id="student-1",
                        full_name="Kid One",
                        status="active",
                        relationship="mother",
                        is_primary=True,
                    )
                ]
            },
        )

        students = await service.get_my_students(principal, uow="uow")

        self.assertEqual(len(students), 1)
        self.assertEqual(students[0].student_id, "student-1")
        # The only parent_id ever passed downstream is the one resolved from the Principal.
        self.assertEqual(student_parent_service.calls[0]["parent_id"], "parent-1")
        self.assertEqual(parent_service.calls[0]["user_id"], "user-parent-1")

    async def test_two_parents_are_fully_isolated_from_each_others_students(self) -> None:
        """The actual security property Known Issue #17 was about: Parent A must never be able
        to reach Parent B's children through this service, for any input."""
        service, _parent, _driver, _sp = make_service(
            parents={
                "user-a": _parent_dto(id="parent-a", user_id="user-a"),
                "user-b": _parent_dto(id="parent-b", user_id="user-b"),
            },
            students_by_parent={
                "parent-a": [
                    StudentForParentDTO(
                        student_id="student-a",
                        full_name="Kid A",
                        status="active",
                        relationship=None,
                        is_primary=True,
                    )
                ],
                "parent-b": [
                    StudentForParentDTO(
                        student_id="student-b",
                        full_name="Kid B",
                        status="active",
                        relationship=None,
                        is_primary=True,
                    )
                ],
            },
        )
        principal_a = Principal(user_id="user-a", role=Role.PARENT, org_id="org-1")
        principal_b = Principal(user_id="user-b", role=Role.PARENT, org_id="org-1")

        students_a = await service.get_my_students(principal_a, uow="uow")
        students_b = await service.get_my_students(principal_b, uow="uow")

        self.assertEqual([s.student_id for s in students_a], ["student-a"])
        self.assertEqual([s.student_id for s in students_b], ["student-b"])

    async def test_raises_not_found_when_no_parent_profile_is_linked(self) -> None:
        """Covers both a genuine role mismatch (e.g. an Org Admin calling this route) and a
        Parent-role principal with a missing row - one honest 404 code path for both, never a
        distinct 403 that would confirm/deny which case it was."""
        principal = Principal(user_id="user-admin-1", role=Role.ORG_ADMIN, org_id="org-1")
        service, *_rest = make_service(parents={})

        with self.assertRaises(NotFoundError):
            await service.get_my_students(principal, uow="uow")


class MeDriverProfileOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_the_callers_own_driver_profile_only(self) -> None:
        principal = Principal(user_id="user-driver-1", role=Role.DRIVER, org_id="org-1")
        service, _parent, driver_service, _sp = make_service(
            drivers={
                "user-driver-1": _driver_dto(id="driver-1", user_id="user-driver-1")
            }
        )

        profile = await service.get_my_driver_profile(principal, uow="uow")

        self.assertEqual(profile.driver_id, "driver-1")
        self.assertEqual(profile.organization_id, "org-1")
        self.assertEqual(profile.license_no, "LIC-1")
        self.assertEqual(driver_service.calls[0]["user_id"], "user-driver-1")

    async def test_raises_not_found_when_no_driver_profile_is_linked(self) -> None:
        principal = Principal(user_id="user-parent-1", role=Role.PARENT, org_id="org-1")
        service, *_rest = make_service(drivers={})

        with self.assertRaises(NotFoundError):
            await service.get_my_driver_profile(principal, uow="uow")


if __name__ == "__main__":
    unittest.main()
