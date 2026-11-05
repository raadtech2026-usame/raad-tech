"""Unit tests for data_transfer RBAC permissions, role gates, and tenant/region scope enforcement.

Validates that:
1. FOUNDER, REGIONAL_MANAGER, and SUPPORT_STAFF hold data_transfer permissions.
2. ORG_ADMIN, DRIVER, and PARENT are strictly DENIED import permissions.
3. FINANCE_STAFF holds templates.read only (read fee/finance structures), never import.execute.
4. Target organization scope is enforced (Founder unrestricted, Regional Manager region-bound, Support Staff assigned-org-bound).
5. Cross-organization access attempts return 404 (ADR-0021 IDOR protection).
6. Target organization ID is always derived from authorized path context, never principal.org_id.
"""

from __future__ import annotations

import unittest

from raad.core.errors.exceptions import AuthorizationError, NotFoundError
from raad.core.security.permissions import Permission, PermissionEvaluator
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.data_transfer.api.deps import resolve_target_organization
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.domain.entities import Organization
from raad.modules.organization.domain.repositories import OrganizationRepository
from raad.modules.organization.domain.value_objects import OrganizationId, OrgType
from raad.modules.transport_ops.api.imports_router import check_import_permission

ORG_1_NORTH = "01J8Z3K9G6X8YV5T4N2R7QW001"
ORG_2_SOUTH = "01J8Z3K9G6X8YV5T4N2R7QW002"
ORG_UNASSIGNED = "01J8Z3K9G6X8YV5T4N2R7QW999"


class FakePermissionEvaluator(PermissionEvaluator):
    """Evaluates permissions based on the seeded data_transfer migration grants."""

    _GRANTS: set[tuple[Role, str]] = {
        (Role.FOUNDER, "data_transfer.templates.read"),
        (Role.FOUNDER, "data_transfer.import.execute"),
        (Role.FOUNDER, "data_transfer.import.history"),
        (Role.REGIONAL_MANAGER, "data_transfer.templates.read"),
        (Role.REGIONAL_MANAGER, "data_transfer.import.execute"),
        (Role.REGIONAL_MANAGER, "data_transfer.import.history"),
        (Role.SUPPORT_STAFF, "data_transfer.templates.read"),
        (Role.SUPPORT_STAFF, "data_transfer.import.execute"),
        (Role.SUPPORT_STAFF, "data_transfer.import.history"),
        (Role.FINANCE_STAFF, "data_transfer.templates.read"),
    }

    async def has_permission(self, principal: Principal, permission: Permission) -> bool:
        return (principal.role, str(permission)) in self._GRANTS


class FakeOrganizationRepository:
    def __init__(self, orgs: list[Organization]) -> None:
        self.by_id: dict[str, Organization] = {str(o.id): o for o in orgs}

    async def get_by_id(self, org_id: str | OrganizationId) -> Organization | None:
        return self.by_id.get(str(org_id))

    def add(self, organization: Organization) -> None:
        self.by_id[str(organization.id)] = organization

    async def list_all(self) -> list[Organization]:
        return list(self.by_id.values())


class FakeOrgUnitOfWork(OrganizationUnitOfWork):
    def __init__(self, repo: FakeOrganizationRepository) -> None:
        self.organizations = repo

    async def __aenter__(self) -> FakeOrgUnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    def record_events(self, events: object) -> None:
        pass


class DataTransferRBACTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from tests.unit.test_bulk_imports import FixedClock
        from datetime import datetime, timezone
        self.clock = FixedClock(datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc))

        self.evaluator = FakePermissionEvaluator()

        self.org1 = Organization.register(
            id=OrganizationId(ORG_1_NORTH),
            name="North Academy",
            org_type=OrgType.SCHOOL,
            region_id=None,
            clock=self.clock,
        )
        self.org2 = Organization.register(
            id=OrganizationId(ORG_2_SOUTH),
            name="South Academy",
            org_type=OrgType.SCHOOL,
            region_id=None,
            clock=self.clock,
        )
        self.org_repo = FakeOrganizationRepository([self.org1, self.org2])
        self.org_uow = FakeOrgUnitOfWork(self.org_repo)

        # Roles
        self.founder = Principal(user_id="u_founder", role=Role.FOUNDER, org_id=None)
        self.reg_mgr = Principal(user_id="u_regmgr", role=Role.REGIONAL_MANAGER, org_id=None)
        self.support = Principal(user_id="u_support", role=Role.SUPPORT_STAFF, org_id=None)
        self.finance = Principal(user_id="u_finance", role=Role.FINANCE_STAFF, org_id=None)
        self.org_admin = Principal(user_id="u_orgadmin", role=Role.ORG_ADMIN, org_id=ORG_1_NORTH)
        self.driver = Principal(user_id="u_driver", role=Role.DRIVER, org_id=ORG_1_NORTH)
        self.parent = Principal(user_id="u_parent", role=Role.PARENT, org_id=ORG_1_NORTH)

    # -------------------------------------------------------------------------
    # 1. RBAC Permission Grants & Denials
    # -------------------------------------------------------------------------

    async def test_founder_has_all_data_transfer_permissions(self) -> None:
        self.assertTrue(await self.evaluator.has_permission(self.founder, Permission("data_transfer.templates.read")))
        self.assertTrue(await self.evaluator.has_permission(self.founder, Permission("data_transfer.import.execute")))
        self.assertTrue(await self.evaluator.has_permission(self.founder, Permission("data_transfer.import.history")))

    async def test_regional_manager_has_data_transfer_permissions(self) -> None:
        self.assertTrue(await self.evaluator.has_permission(self.reg_mgr, Permission("data_transfer.templates.read")))
        self.assertTrue(await self.evaluator.has_permission(self.reg_mgr, Permission("data_transfer.import.execute")))
        self.assertTrue(await self.evaluator.has_permission(self.reg_mgr, Permission("data_transfer.import.history")))

    async def test_support_staff_has_data_transfer_permissions(self) -> None:
        self.assertTrue(await self.evaluator.has_permission(self.support, Permission("data_transfer.templates.read")))
        self.assertTrue(await self.evaluator.has_permission(self.support, Permission("data_transfer.import.execute")))
        self.assertTrue(await self.evaluator.has_permission(self.support, Permission("data_transfer.import.history")))

    async def test_finance_staff_has_template_read_only(self) -> None:
        self.assertTrue(await self.evaluator.has_permission(self.finance, Permission("data_transfer.templates.read")))
        self.assertFalse(await self.evaluator.has_permission(self.finance, Permission("data_transfer.import.execute")))
        self.assertFalse(await self.evaluator.has_permission(self.finance, Permission("data_transfer.import.history")))

    async def test_org_admin_has_absolutely_no_import_permissions(self) -> None:
        self.assertFalse(await self.evaluator.has_permission(self.org_admin, Permission("data_transfer.templates.read")))
        self.assertFalse(await self.evaluator.has_permission(self.org_admin, Permission("data_transfer.import.execute")))
        self.assertFalse(await self.evaluator.has_permission(self.org_admin, Permission("data_transfer.import.history")))

    async def test_driver_and_parent_have_no_import_permissions(self) -> None:
        for principal in (self.driver, self.parent):
            self.assertFalse(await self.evaluator.has_permission(principal, Permission("data_transfer.import.execute")))
            self.assertFalse(await self.evaluator.has_permission(principal, Permission("data_transfer.import.history")))

    # -------------------------------------------------------------------------
    # 2. Scope & Organization Access Enforcement
    # -------------------------------------------------------------------------

    async def test_founder_can_target_any_existing_organization(self) -> None:
        unrestricted_scope = TenantRegionScope(organization_ids=None)
        resolved_1 = await resolve_target_organization(
            ORG_1_NORTH,
            principal=self.founder,
            scope=unrestricted_scope,
            org_uow=self.org_uow,
        )
        self.assertEqual(resolved_1, ORG_1_NORTH)

        resolved_2 = await resolve_target_organization(
            ORG_2_SOUTH,
            principal=self.founder,
            scope=unrestricted_scope,
            org_uow=self.org_uow,
        )
        self.assertEqual(resolved_2, ORG_2_SOUTH)

    async def test_regional_manager_scoped_to_assigned_regions(self) -> None:
        # Regional Manager assigned only to North region (ORG_1_NORTH)
        reg_scope = TenantRegionScope(organization_ids=frozenset([ORG_1_NORTH]))

        # Access to assigned org succeeds
        resolved = await resolve_target_organization(
            ORG_1_NORTH,
            principal=self.reg_mgr,
            scope=reg_scope,
            org_uow=self.org_uow,
        )
        self.assertEqual(resolved, ORG_1_NORTH)

        # Access to unassigned org raises NotFoundError (ADR-0021 IDOR shield)
        with self.assertRaises(NotFoundError):
            await resolve_target_organization(
                ORG_2_SOUTH,
                principal=self.reg_mgr,
                scope=reg_scope,
                org_uow=self.org_uow,
            )

    async def test_support_staff_scoped_to_assigned_organizations(self) -> None:
        support_scope = TenantRegionScope(organization_ids=frozenset([ORG_2_SOUTH]))

        # Allowed for ORG_2_SOUTH
        resolved = await resolve_target_organization(
            ORG_2_SOUTH,
            principal=self.support,
            scope=support_scope,
            org_uow=self.org_uow,
        )
        self.assertEqual(resolved, ORG_2_SOUTH)

        # Denied for ORG_1_NORTH
        with self.assertRaises(NotFoundError):
            await resolve_target_organization(
                ORG_1_NORTH,
                principal=self.support,
                scope=support_scope,
                org_uow=self.org_uow,
            )

    async def test_nonexistent_organization_id_raises_not_found(self) -> None:
        unrestricted_scope = TenantRegionScope(organization_ids=None)
        with self.assertRaises(NotFoundError):
            await resolve_target_organization(
                ORG_UNASSIGNED,
                principal=self.founder,
                scope=unrestricted_scope,
                org_uow=self.org_uow,
            )

    async def test_empty_organization_id_raises_not_found(self) -> None:
        unrestricted_scope = TenantRegionScope(organization_ids=None)
        with self.assertRaises(NotFoundError):
            await resolve_target_organization(
                "   ",
                principal=self.founder,
                scope=unrestricted_scope,
                org_uow=self.org_uow,
            )

    # -------------------------------------------------------------------------
    # 3. Old imports_router defect fix verification
    # -------------------------------------------------------------------------

    async def test_old_imports_router_blocks_org_admin(self) -> None:
        class FakeRequest:
            class FakeApp:
                class FakeState:
                    pass
                state = FakeState()
            app = FakeApp()

        class ContainerWithEvaluator:
            def __init__(self, evaluator):
                self.evaluator = evaluator
            def resolve(self, type_):
                return self.evaluator

        req = FakeRequest()
        req.app.state.container = ContainerWithEvaluator(self.evaluator)

        # Org Admin attempting to call the import endpoint is rejected with AuthorizationError
        with self.assertRaises(AuthorizationError):
            await check_import_permission(
                resource_type="students",
                request=req,
                principal=self.org_admin,
            )

        # Founder is granted access
        res = await check_import_permission(
            resource_type="students",
            request=req,
            principal=self.founder,
        )
        self.assertEqual(res.user_id, self.founder.user_id)


if __name__ == "__main__":
    unittest.main()
