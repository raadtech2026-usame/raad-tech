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

from datetime import datetime

from raad.core.errors.exceptions import DomainError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.logging.setup import get_logger
from raad.core.pagination import OffsetPage
from raad.core.tenancy.principal import Role
from raad.core.time.clock import Clock
from raad.modules.organization.application.commands import (
    ActivateRegionCommand,
    CreateRegionCommand,
    DeactivateOrganizationCommand,
    DeactivateRegionCommand,
    GrantRegionAssignmentCommand,
    GrantSupportAssignmentCommand,
    OnboardOrganizationCommand,
    ReactivateOrganizationCommand,
    RegisterOrganizationCommand,
    RevokeRegionAssignmentCommand,
    RevokeSupportAssignmentCommand,
    SuspendOrganizationCommand,
    UpdateOrganizationApproachingDistanceCommand,
    UpdateOrganizationGeofenceCommand,
)
from raad.modules.organization.application.ports import (
    BillingProvisioningPort,
    IamProvisioningPort,
    OrganizationUnitOfWork,
)
from raad.modules.organization.application.queries import (
    GetOrganizationByIdQuery,
    GetRegionByIdQuery,
    ListOrganizationsQuery,
    ListRegionsQuery,
    OrganizationDTO,
    OrganizationStatsDTO,
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


logger = get_logger("raad.organization.onboarding")


class OrganizationApplicationService:
    """Organization lifecycle use-cases: register, suspend, reactivate, deactivate, and the
    `GetOrganizationByIdQuery` read path. `onboard_organization` (ADR-0017) additionally
    provisions the Organization's first Org Admin user via `IamProvisioningPort`."""

    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        iam_provisioning: IamProvisioningPort,
        billing_provisioning: BillingProvisioningPort | None = None,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._iam_provisioning = iam_provisioning
        #: ADR-0040 §5. Optional so the service stays constructible without `billing` wired —
        #: onboarding then simply skips subscription creation, exactly as it did before.
        self._billing_provisioning = billing_provisioning

    async def onboard_organization(
        self, command: OnboardOrganizationCommand, *, uow: OrganizationUnitOfWork
    ) -> tuple[OrganizationDTO, str, str]:
        """ADR-0017: creates the `Organization` first (committing this module's own Unit of
        Work), then calls `IamProvisioningPort` — a second, independent commit, real and
        durable the moment it returns — to create the Org Admin `iam.User` scoped to the
        just-created `organization_id`. Returns `(OrganizationDTO, admin_user_id,
        temporary_password)`; the temporary password is surfaced exactly once, for hand-off.

        **ADR-0040 §5 adds plan selection.** When `command.plan_id` is supplied, a third,
        independent commit opens the subscription and issues the first invoice via
        `BillingProvisioningPort`.

        **This is a saga, and it fails loudly (revised 2026-09-09).** It previously caught and
        logged a subscription-provisioning failure and returned success anyway. That is how a
        total billing outage went unnoticed: every onboarding answered `201 Created` while
        `open_organization_subscription` raised an `IntegrityError` on every single call, so the
        platform accumulated organizations that could never be billed and were never reported as
        broken. Three changes together close it:

        1. **Fail fast.** The plan is validated before *anything* is committed, which removes the
           likeliest failure from the window where compensation is needed at all.
        2. **Compensate.** A failure after the organization commits disables the admin account
           and deactivates the organization (`_compensate_onboarding`), so no half-provisioned
           tenant is left live.
        3. **Re-raise.** The caller sees the real error and the route answers 4xx/5xx — never
           `201` for an onboarding that did not complete.

        True cross-module atomicity remains impossible by design: three modules own three Units
        of Work and `.claude/rules/backend.md` #3 keeps each module's persistence its own. A saga
        with compensation is the correct pattern under that constraint, and is what ADR-0003's
        Failure Handling section anticipated rather than the silent partial state it settled for.
        """
        # --- Step 0: validate everything that can be validated before anything is written ----
        #
        # Onboarding spans three modules and therefore three Units of Work; one database
        # transaction cannot cover them (`.claude/rules/backend.md` #3). The next best guarantee
        # is to make the likely failures happen while there is still nothing to undo. A plan id
        # that does not exist, or a plan that is no longer sold, is by far the most likely — so
        # it is checked here, before the `Organization` row exists.
        if command.plan_id:
            if self._billing_provisioning is None:
                raise DomainError(
                    "A plan was selected but billing is not configured on this deployment; "
                    "the organization was not created."
                )
            await self._billing_provisioning.ensure_plan_is_offerable(
                plan_id=command.plan_id
            )

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
                parent_org_id=parent_org_id,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.organizations.add(organization)
            uow.record_events(organization.pull_domain_events())
            await uow.commit()

        # --- Steps 1-2: the two cross-module commits, with compensation on failure ----------
        #
        # Anything that fails from here on leaves committed state behind, so each failure runs
        # the saga's compensating actions and then **re-raises**. Nothing is swallowed: the
        # route must not answer 201 for an organization that did not finish onboarding.
        admin_user_id: str | None = None
        try:
            admin_user_id, temporary_password = (
                await self._iam_provisioning.create_user_with_temporary_password(
                    organization_id=str(organization.id),
                    role=Role.ORG_ADMIN,
                    email=command.admin_email,
                    phone=command.admin_phone,
                    full_name=command.admin_full_name,
                    actor=command.actor,
                )
            )
            if command.plan_id and self._billing_provisioning is not None:
                await self._billing_provisioning.open_subscription_for_organization(
                    organization_id=str(organization.id),
                    plan_id=command.plan_id,
                    actor=command.actor,
                )
        except Exception:
            await self._compensate_onboarding(
                organization_id=str(organization.id),
                admin_user_id=admin_user_id,
                command=command,
                uow=uow,
            )
            raise

        return organization_to_dto(organization), admin_user_id, temporary_password

    async def _compensate_onboarding(
        self,
        *,
        organization_id: str,
        admin_user_id: str | None,
        command: OnboardOrganizationCommand,
        uow: OrganizationUnitOfWork,
    ) -> None:
        """Undo the committed steps of a failed onboarding, best-effort, then let the caller
        re-raise the original failure.

        **Compensation, not rollback.** The organization and the admin user were each committed
        by their own module's Unit of Work; no later transaction can revert them. What it can do
        is leave the tenant in a state that is inert and obviously incomplete rather than
        half-live: the `Organization` is deactivated and the admin account disabled, both through
        their owning aggregate's own transition, so both raise their domain event and land in
        `audit_entries`. An operator sees an inactive organization with a disabled admin and a
        logged reason — not an active tenant that silently cannot bill.

        **Compensation failures are logged, never raised.** The caller is already unwinding a
        real error, and replacing it with a secondary failure from the cleanup would hide the
        cause. Each step is independent so that one failing does not skip the other.
        """
        if admin_user_id is not None:
            try:
                await self._iam_provisioning.disable_user(
                    user_id=admin_user_id, actor=command.actor
                )
            except Exception:  # noqa: BLE001 - see docstring
                logger.exception(
                    "onboarding_compensation_failed_disabling_admin",
                    extra={
                        "onboarded_organization_id": organization_id,
                        "onboarded_admin_user_id": admin_user_id,
                    },
                )

        try:
            async with uow:
                organization = await uow.organizations.get(
                    OrganizationId(organization_id)
                )
                if organization is not None:
                    organization.deactivate(
                        clock=self._clock, actor_id=command.actor.user_id
                    )
                    uow.record_events(organization.pull_domain_events())
                    await uow.commit()
        except Exception:  # noqa: BLE001 - see docstring
            logger.exception(
                "onboarding_compensation_failed_deactivating_organization",
                extra={"onboarded_organization_id": organization_id},
            )

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

    async def update_organization_geofence(
        self, command: UpdateOrganizationGeofenceCommand, *, uow: OrganizationUnitOfWork
    ) -> OrganizationDTO:
        """ADR-0014. No approved HTTP route yet — see `UpdateOrganizationGeofenceCommand`'s
        own docstring."""
        async with uow:
            organization = await self._get_organization_or_raise(
                uow, command.organization_id
            )
            organization.set_geofence(
                latitude=command.latitude,
                longitude=command.longitude,
                radius_m=command.radius_m,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(organization.pull_domain_events())
            await uow.commit()
            return organization_to_dto(organization)

    async def update_organization_approaching_distance(
        self,
        command: UpdateOrganizationApproachingDistanceCommand,
        *,
        uow: OrganizationUnitOfWork,
    ) -> OrganizationDTO:
        """ADR-0014 amendment. No approved HTTP route yet — see
        `UpdateOrganizationApproachingDistanceCommand`'s own docstring."""
        async with uow:
            organization = await self._get_organization_or_raise(
                uow, command.organization_id
            )
            organization.set_approaching_distance_m(
                approaching_distance_m=command.approaching_distance_m,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
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
    ) -> OffsetPage[OrganizationDTO]:
        """Backs `GET /organizations` (API Contracts §4.1/§7/§8) — pagination/filtering/
        sorting added under the Tier 2 pagination phase, on top of the Backend Stabilization
        phase's original `list_all`-backed addition (still used by other callers, e.g. the
        Founder-bootstrap CLI's own precondition check via `uow.users.list_all()` in `iam`)."""
        async with uow:
            page = await uow.organizations.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[organization_to_dto(o) for o in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    async def get_organization_stats(
        self, *, since_today: datetime, uow: OrganizationUnitOfWork
    ) -> OrganizationStatsDTO:
        """ADR-0020: "Total/Active/Suspended Organizations" + "New Organizations Today" KPIs,
        backing `platform_audit.PlatformStatsApplicationService`. `since_today` (the start of
        "today") is resolved by the caller, once, for the whole composed response — not
        re-derived per module — matching `SessionLimitPolicy`'s own "policy resolved by caller"
        discipline (ADR-0019)."""
        async with uow:
            by_status = await uow.organizations.count_by_status()
            created_today = await uow.organizations.count_created_since(since_today)
            return OrganizationStatsDTO(
                total=sum(by_status.values()),
                by_status=by_status,
                created_today=created_today,
            )

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
    ) -> OffsetPage[RegionDTO]:
        """Backs `GET /regions` (API Contracts §4.1/§7/§8)."""
        async with uow:
            page = await uow.regions.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[region_to_dto(r) for r in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

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

    async def list_region_assignments(
        self, user_id: str, *, uow: OrganizationUnitOfWork
    ) -> frozenset[str]:
        """Priority 1 Item 6 (`PROJECT_STATUS.md`, RBAC grant/revoke route) — the read half of
        the same grant/revoke primitive above, previously reachable only by calling the
        repository directly (never through this service, since no caller needed it before an
        HTTP route existed)."""
        async with uow:
            return await uow.scope_assignments.list_assigned_region_ids(user_id)

    async def list_organization_assignments(
        self, user_id: str, *, uow: OrganizationUnitOfWork
    ) -> frozenset[str]:
        async with uow:
            return await uow.scope_assignments.list_assigned_organization_ids(user_id)
