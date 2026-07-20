"""Organization application services (Backend LLD §4.1/§4.3). Thin, orchestration-only
handlers — business rules stay inside the `Organization`/`Region` aggregates
(`modules/organization/domain`); these services only: resolve/validate pre-conditions, load
aggregates via the repositories bound to `OrganizationUnitOfWork`, invoke domain behavior,
record the resulting `DomainEvent`s, commit, and return a DTO — the exact skeleton the LLD's
§4.3 "transaction & event ordering" steps describe, identical to `iam.application.services`.

Split into two services by natural API grouping (API Contracts rule #2: `/organizations` +
`/regions`, both routed to this module), not by some other axis — the same reasoning
`iam.application.services` gives for splitting `AuthApplicationService`/`UserApplicationService`
by `/auth/*` vs a user-management surface rather than by aggregate.
"""

from __future__ import annotations

from raad.core.errors.exceptions import NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.time.clock import Clock
from raad.modules.organization.application.commands import (
    ActivateRegionCommand,
    CreateRegionCommand,
    DeactivateOrganizationCommand,
    DeactivateRegionCommand,
    GrantRegionAssignmentCommand,
    GrantSupportAssignmentCommand,
    ReactivateOrganizationCommand,
    RegisterOrganizationCommand,
    RevokeRegionAssignmentCommand,
    RevokeSupportAssignmentCommand,
    SuspendOrganizationCommand,
)
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.application.queries import (
    GetOrganizationByIdQuery,
    GetRegionByIdQuery,
    ListOrganizationsQuery,
    ListRegionsQuery,
    OrganizationDTO,
    RegionDTO,
    organization_to_dto,
    region_to_dto,
)
from raad.modules.organization.application.validators import (
    ensure_parent_organization_exists,
    ensure_region_exists,
    ensure_region_name_available,
)
from raad.modules.organization.domain import events as org_events
from raad.modules.organization.domain.entities import Organization, Region
from raad.modules.organization.domain.value_objects import OrganizationId, RegionId


class OrganizationApplicationService:
    """Organization lifecycle use-cases: register, suspend, reactivate, deactivate, and the
    `GetOrganizationByIdQuery` read path."""

    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    async def register_organization(
        self, command: RegisterOrganizationCommand, *, uow: OrganizationUnitOfWork
    ) -> OrganizationDTO:
        async with uow:
            region_id = RegionId(command.region_id)
            await ensure_region_exists(uow, region_id)

            parent_org_id = (
                OrganizationId(command.parent_org_id) if command.parent_org_id else None
            )
            if parent_org_id is not None:
                await ensure_parent_organization_exists(uow, parent_org_id)

            organization = Organization.register(
                id=OrganizationId(self._id_generator.new_id()),
                name=command.name,
                org_type=command.org_type,
                region_id=region_id,
                billing_model=command.billing_model,
                parent_org_id=parent_org_id,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.organizations.add(organization)
            uow.record_events(organization.pull_domain_events())
            await uow.commit()
            return organization_to_dto(organization)

    async def suspend_organization(
        self, command: SuspendOrganizationCommand, *, uow: OrganizationUnitOfWork
    ) -> OrganizationDTO:
        async with uow:
            organization = await self._get_organization_or_raise(
                uow, command.organization_id
            )
            organization.suspend(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(organization.pull_domain_events())
            await uow.commit()
            return organization_to_dto(organization)

    async def reactivate_organization(
        self, command: ReactivateOrganizationCommand, *, uow: OrganizationUnitOfWork
    ) -> OrganizationDTO:
        async with uow:
            organization = await self._get_organization_or_raise(
                uow, command.organization_id
            )
            organization.reactivate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(organization.pull_domain_events())
            await uow.commit()
            return organization_to_dto(organization)

    async def deactivate_organization(
        self, command: DeactivateOrganizationCommand, *, uow: OrganizationUnitOfWork
    ) -> OrganizationDTO:
        async with uow:
            organization = await self._get_organization_or_raise(
                uow, command.organization_id
            )
            organization.deactivate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(organization.pull_domain_events())
            await uow.commit()
            return organization_to_dto(organization)

    async def get_organization_by_id(
        self, query: GetOrganizationByIdQuery, *, uow: OrganizationUnitOfWork
    ) -> OrganizationDTO:
        async with uow:
            organization = await self._get_organization_or_raise(
                uow, query.organization_id
            )
            return organization_to_dto(organization)

    async def list_organizations(
        self, query: ListOrganizationsQuery, *, uow: OrganizationUnitOfWork
    ) -> list[OrganizationDTO]:
        """Backs `GET /organizations` (API Contracts §4.1) — Backend Stabilization phase
        addition, see `domain/repositories.py`'s `OrganizationRepository.list_all` docstring
        for why this was previously deferred and what unblocked it."""
        async with uow:
            organizations = await uow.organizations.list_all()
            return [organization_to_dto(o) for o in organizations]

    @staticmethod
    async def _get_organization_or_raise(
        uow: OrganizationUnitOfWork, organization_id: str
    ) -> Organization:
        organization = await uow.organizations.get(OrganizationId(organization_id))
        if organization is None:
            raise NotFoundError(f"Organization {organization_id} not found.")
        return organization


class RegionApplicationService:
    """Region lifecycle use-cases: create, activate, deactivate, and the `GetRegionByIdQuery`
    read path."""

    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    async def create_region(
        self, command: CreateRegionCommand, *, uow: OrganizationUnitOfWork
    ) -> RegionDTO:
        async with uow:
            await ensure_region_name_available(uow, command.name)

            region = Region.create(
                id=RegionId(self._id_generator.new_id()),
                name=command.name,
                geographic_scope=command.geographic_scope,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.regions.add(region)
            uow.record_events(region.pull_domain_events())
            await uow.commit()
            return region_to_dto(region)

    async def activate_region(
        self, command: ActivateRegionCommand, *, uow: OrganizationUnitOfWork
    ) -> RegionDTO:
        async with uow:
            region = await self._get_region_or_raise(uow, command.region_id)
            region.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(region.pull_domain_events())
            await uow.commit()
            return region_to_dto(region)

    async def deactivate_region(
        self, command: DeactivateRegionCommand, *, uow: OrganizationUnitOfWork
    ) -> RegionDTO:
        async with uow:
            region = await self._get_region_or_raise(uow, command.region_id)
            region.deactivate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(region.pull_domain_events())
            await uow.commit()
            return region_to_dto(region)

    async def get_region_by_id(
        self, query: GetRegionByIdQuery, *, uow: OrganizationUnitOfWork
    ) -> RegionDTO:
        async with uow:
            region = await self._get_region_or_raise(uow, query.region_id)
            return region_to_dto(region)

    async def list_regions(
        self, query: ListRegionsQuery, *, uow: OrganizationUnitOfWork
    ) -> list[RegionDTO]:
        """Backs `GET /regions` (API Contracts §4.1) — Backend Stabilization phase addition."""
        async with uow:
            regions = await uow.regions.list_all()
            return [region_to_dto(r) for r in regions]

    @staticmethod
    async def _get_region_or_raise(
        uow: OrganizationUnitOfWork, region_id: str
    ) -> Region:
        region = await uow.regions.get(RegionId(region_id))
        if region is None:
            raise NotFoundError(f"Region {region_id} not found.")
        return region


class ScopeAssignmentApplicationService:
    """RAAD-staff scope assignment management (Database Design §4.6): grants/revokes that back
    `ScopeResolver`'s Regional Manager/Support Staff formulas. No approved HTTP route exists yet
    (`application/commands.py`'s own docstring) — reachable at the application layer only, the
    same posture `iam.application.services.PermissionApplicationService` has for the analogous
    `role_permissions` grant. No `id_generator` — composite-key grant data, no surrogate id."""

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    async def grant_region_assignment(
        self, command: GrantRegionAssignmentCommand, *, uow: OrganizationUnitOfWork
    ) -> None:
        async with uow:
            await uow.scope_assignments.grant_region(
                command.user_id, command.region_id, granted_by=command.actor.user_id
            )
            uow.record_events(
                [
                    org_events.region_assignment_granted(
                        user_id=command.user_id,
                        region_id=command.region_id,
                        occurred_at=self._clock.now(),
                        actor_id=command.actor.user_id,
                    )
                ]
            )
            await uow.commit()

    async def revoke_region_assignment(
        self, command: RevokeRegionAssignmentCommand, *, uow: OrganizationUnitOfWork
    ) -> None:
        async with uow:
            await uow.scope_assignments.revoke_region(
                command.user_id, command.region_id
            )
            uow.record_events(
                [
                    org_events.region_assignment_revoked(
                        user_id=command.user_id,
                        region_id=command.region_id,
                        occurred_at=self._clock.now(),
                        actor_id=command.actor.user_id,
                    )
                ]
            )
            await uow.commit()

    async def grant_support_assignment(
        self, command: GrantSupportAssignmentCommand, *, uow: OrganizationUnitOfWork
    ) -> None:
        async with uow:
            await uow.scope_assignments.grant_organization(
                command.user_id,
                command.organization_id,
                granted_by=command.actor.user_id,
            )
            uow.record_events(
                [
                    org_events.support_assignment_granted(
                        user_id=command.user_id,
                        organization_id=command.organization_id,
                        occurred_at=self._clock.now(),
                        actor_id=command.actor.user_id,
                    )
                ]
            )
            await uow.commit()

    async def revoke_support_assignment(
        self, command: RevokeSupportAssignmentCommand, *, uow: OrganizationUnitOfWork
    ) -> None:
        async with uow:
            await uow.scope_assignments.revoke_organization(
                command.user_id, command.organization_id
            )
            uow.record_events(
                [
                    org_events.support_assignment_revoked(
                        user_id=command.user_id,
                        organization_id=command.organization_id,
                        occurred_at=self._clock.now(),
                        actor_id=command.actor.user_id,
                    )
                ]
            )
            await uow.commit()
