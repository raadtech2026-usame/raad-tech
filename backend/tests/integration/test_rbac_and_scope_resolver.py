"""PostgreSQL-backed integration tests for the RBAC permission matrix
(`iam.infra.adapters.IamPermissionEvaluator`, Database Design §4.4) and `ScopeResolver`
(`organization.infra.adapters.OrganizationScopeResolver`, Database Design §4.6) — the Backend
Stabilization phase's resolution of two of the review's Critical/High findings (RBAC stub;
Tracking/CR-1/D5 enforcement blocked on scope resolution). Stdlib `unittest`, live-DB
skip-guard pattern, mirroring every other integration test in this codebase.

Covers: the live-seeded matrix (`role_permissions`, migration `5437a5d1651b`) actually grants/
denies correctly for a representative sample of roles; grant/revoke round-trips; and
`ScopeResolver`'s four branches (Founder unrestricted, Regional Manager region-derived,
Support/Finance directly-assigned, tenant roles own-org-only).
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import SystemClock
from raad.modules.iam.infra.adapters import IamPermissionEvaluator
from raad.modules.iam.infra.repositories import SqlAlchemyIamUnitOfWork
from raad.modules.organization.domain.entities import Organization, Region
from raad.modules.organization.domain.value_objects import (
    BillingModel,
    OrgType,
    OrganizationId,
    RegionId,
)
from raad.modules.organization.infra.adapters import OrganizationScopeResolver
from raad.modules.organization.infra.repositories import (
    SqlAlchemyOrganizationUnitOfWork,
)
from sqlalchemy import text


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class IamPermissionEvaluatorRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.tag = uuid.uuid4().hex[:8]
        self._granted: list[tuple[str, str]] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            for role, permission in self._granted:
                await conn.execute(
                    text(
                        "DELETE FROM role_permissions WHERE role = :role "
                        "AND permission = :permission"
                    ),
                    {"role": role, "permission": permission},
                )
        await self.engine.dispose()

    def _evaluator(self) -> IamPermissionEvaluator:
        return IamPermissionEvaluator(
            lambda: SqlAlchemyIamUnitOfWork(self.session_factory, self.outbox_writer)
        )

    async def test_seeded_matrix_grants_org_admin_transport_ops_create(self) -> None:
        evaluator = self._evaluator()
        principal = Principal(user_id="u1", role=Role.ORG_ADMIN, org_id="org1")
        result = await evaluator.has_permission(
            principal, Permission("transport_ops.students.create")
        )
        self.assertTrue(result)

    async def test_seeded_matrix_denies_org_admin_platform_admin_action(self) -> None:
        evaluator = self._evaluator()
        principal = Principal(user_id="u1", role=Role.ORG_ADMIN, org_id="org1")
        result = await evaluator.has_permission(
            principal, Permission("organization.organizations.create")
        )
        self.assertFalse(result)

    async def test_seeded_matrix_denies_parent_fleet_device_write(self) -> None:
        evaluator = self._evaluator()
        principal = Principal(user_id="u1", role=Role.PARENT, org_id="org1")
        result = await evaluator.has_permission(
            principal, Permission("fleet_device.vehicles.create")
        )
        self.assertFalse(result)

    async def test_grant_then_revoke_round_trips(self) -> None:
        evaluator = self._evaluator()
        test_permission = f"test.custom.permission.{self.tag}"
        principal = Principal(user_id="u1", role=Role.DRIVER, org_id="org1")

        before = await evaluator.has_permission(principal, Permission(test_permission))
        self.assertFalse(before)

        async with SqlAlchemyIamUnitOfWork(
            self.session_factory, self.outbox_writer
        ) as uow:
            await uow.role_permissions.grant(Role.DRIVER, test_permission)
            await uow.commit()
        self._granted.append(("driver", test_permission))

        after_grant = await evaluator.has_permission(
            principal, Permission(test_permission)
        )
        self.assertTrue(after_grant)

        async with SqlAlchemyIamUnitOfWork(
            self.session_factory, self.outbox_writer
        ) as uow:
            await uow.role_permissions.revoke(Role.DRIVER, test_permission)
            await uow.commit()

        after_revoke = await evaluator.has_permission(
            principal, Permission(test_permission)
        )
        self.assertFalse(after_revoke)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class OrganizationScopeResolverRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_org_ids: list[str] = []
        self._created_region_ids: list[str] = []
        self._staff_user_id = self.id_generator.new_id()

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM region_assignments WHERE user_id = :uid"),
                {"uid": self._staff_user_id},
            )
            await conn.execute(
                text("DELETE FROM support_assignments WHERE user_id = :uid"),
                {"uid": self._staff_user_id},
            )
            if self._created_org_ids:
                await conn.execute(
                    text("DELETE FROM organizations WHERE id = ANY(:ids)"),
                    {"ids": self._created_org_ids},
                )
            if self._created_region_ids:
                await conn.execute(
                    text("DELETE FROM regions WHERE id = ANY(:ids)"),
                    {"ids": self._created_region_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyOrganizationUnitOfWork:
        return SqlAlchemyOrganizationUnitOfWork(self.session_factory, self.outbox_writer)

    def _resolver(self) -> OrganizationScopeResolver:
        return OrganizationScopeResolver(self._new_uow)

    async def _seed_region_and_org(self) -> tuple[str, str]:
        async with self._new_uow() as uow:
            region = Region.create(
                id=RegionId(self.id_generator.new_id()),
                name=f"Region {self.tag}",
                clock=self.clock,
            )
            uow.regions.add(region)
            uow.record_events(region.pull_domain_events())
            await uow.commit()
            self._created_region_ids.append(str(region.id))

            organization = Organization.register(
                id=OrganizationId(self.id_generator.new_id()),
                name=f"Org {self.tag}",
                org_type=OrgType.SCHOOL,
                region_id=region.id,
                billing_model=BillingModel.ORGANIZATION_PAYS,
                clock=self.clock,
            )
            uow.organizations.add(organization)
            uow.record_events(organization.pull_domain_events())
            await uow.commit()
            self._created_org_ids.append(str(organization.id))
        return str(region.id), str(organization.id)

    async def test_founder_scope_is_unrestricted(self) -> None:
        resolver = self._resolver()
        principal = Principal(user_id="u-founder", role=Role.FOUNDER, org_id=None)
        scope = await resolver.effective_org_scope(principal)
        self.assertTrue(scope.is_unrestricted)

    async def test_tenant_role_scope_is_own_org_only(self) -> None:
        resolver = self._resolver()
        principal = Principal(
            user_id="u-org-admin", role=Role.ORG_ADMIN, org_id="org-xyz"
        )
        scope = await resolver.effective_org_scope(principal)
        self.assertFalse(scope.is_unrestricted)
        self.assertTrue(scope.allows("org-xyz"))
        self.assertFalse(scope.allows("some-other-org"))

    async def test_regional_manager_scope_derives_orgs_from_assigned_regions(
        self,
    ) -> None:
        region_id, org_id = await self._seed_region_and_org()
        async with self._new_uow() as uow:
            await uow.scope_assignments.grant_region(
                self._staff_user_id, region_id, granted_by=None
            )
            await uow.commit()

        resolver = self._resolver()
        principal = Principal(
            user_id=self._staff_user_id, role=Role.REGIONAL_MANAGER, org_id=None
        )
        scope = await resolver.effective_org_scope(principal)
        self.assertFalse(scope.is_unrestricted)
        self.assertTrue(scope.allows(org_id))

    async def test_support_staff_scope_is_directly_assigned_orgs(self) -> None:
        _, org_id = await self._seed_region_and_org()
        async with self._new_uow() as uow:
            await uow.scope_assignments.grant_organization(
                self._staff_user_id, org_id, granted_by=None
            )
            await uow.commit()

        resolver = self._resolver()
        principal = Principal(
            user_id=self._staff_user_id, role=Role.SUPPORT_STAFF, org_id=None
        )
        scope = await resolver.effective_org_scope(principal)
        self.assertTrue(scope.allows(org_id))

    async def test_support_staff_with_no_grants_has_empty_scope(self) -> None:
        resolver = self._resolver()
        principal = Principal(
            user_id="u-no-grants", role=Role.SUPPORT_STAFF, org_id=None
        )
        scope = await resolver.effective_org_scope(principal)
        self.assertFalse(scope.is_unrestricted)
        self.assertFalse(scope.allows("any-org"))


if __name__ == "__main__":
    unittest.main()
