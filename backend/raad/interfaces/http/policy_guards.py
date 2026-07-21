"""CR-1 (`SubscriptionAccessPolicy`) and D5 (`VideoAccessPolicy`) enforcement points (Backend
LLD §5.4/§16.2; API Contracts §3.1's four-layer authorization model: Authentication -> RBAC ->
Tenant/region scope -> Domain policies). **Architecture Resolution (Backend Stabilization
phase, Critical findings #1/#3 of the pre-production review):** both policies have existed as
pure, fully-tested decision objects since Phase 14 (`core/policies`), but — as the review found
by exhaustive repo-wide search — neither was ever actually invoked anywhere. This module is that
missing enforcement point.

Lives in `interfaces/http/`, not any single bounded-context module, because evaluating either
policy requires orchestrating **application services from multiple modules** (`transport_ops`
for assignment/ownership facts, `organization` for billing model, `billing` for subscription
state) — exactly the kind of cross-cutting, request-scoped orchestration `interfaces/http/deps.py`
already does for `get_scope`/`require_permission`. Each call resolves every input via the owning
module's own **application service** (never a repository directly), matching
`.claude/rules/backend.md` #3's "cross-context data comes from the owning module's application
service" rule exactly — no cross-module DB read anywhere in this file.
"""

from __future__ import annotations

from raad.core.errors.exceptions import (
    NotFoundError,
    ParentAccessDeniedError,
    VideoForbiddenError,
)
from raad.core.di.container import Container
from raad.core.policies.base import PolicyDecision
from raad.core.policies.subscription_access import (
    AssignmentState,
    BillingModel,
    SubscriptionAccessPolicy,
    SubscriptionState,
)
from raad.core.policies.video_access import VideoAccessPolicy
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.resolver import ScopeResolver
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.application.queries import GetOrganizationByIdQuery
from raad.modules.organization.application.services import OrganizationApplicationService
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import ListStudentsForParentQuery
from raad.modules.transport_ops.application.services import (
    ParentApplicationService,
    StudentAssignmentApplicationService,
    StudentParentApplicationService,
)
from raad.modules.tracking.domain.policies import TrackingVisibilityPolicy


async def resolve_cr1_decision(
    *,
    principal: Principal,
    student_id: str,
    container: Container,
    safety_override: bool = False,
) -> PolicyDecision:
    """CR-1 (Backend LLD §5.4). Resolves the three documented inputs for the given `student_id`
    and evaluates `SubscriptionAccessPolicy`. Raises `NotFoundError` (404, not 403 — this
    codebase's established cross-tenant-probing-avoidance convention, `notifications.
    application.queries.GetNotificationByIdQuery`'s own precedent) if `principal` is not a
    Parent of `student_id` at all — CR-1 itself only governs Parent access to a **known-own**
    child (LLD §5.4: "this policy governs the Parent role only"), not a stranger's.

    **`safety_override` — the D4/CR-1 reconciliation (ADR-0006), resolved here per this phase's
    explicit conflict-resolution authority.** `tracking.domain.policies`'s own module docstring
    flags an unresolved tension between Phase 2 §9.6/§23.2 (D4: parent live-GPS during an
    active trip "never revoked by subscription lapse") and this policy's own LLD §5.4 text
    ("supersedes" D4). `.claude/rules/security.md` #6 and `.claude/rules/backend.md` #6 —
    themselves approved derivations from the same business documents — are unambiguous and
    *not* flagged as open questions: "Safety capabilities are never billing-gated... enforced
    by one policy object" (not scattered `if subscription_active` checks). Resolution: the
    `assignment_state` gate (business rule 3, highest precedence) always applies unchanged —
    an inactive assignment is an eligibility question, not a billing one. The
    `subscription_state` gate is skipped (treated as granting) only when `safety_override=True`
    — the caller's own signal that this is specifically "live GPS during a currently active
    trip," D4's exact protected scenario, never for trip *history* (`flutter.md` #4: "Outside
    active trips, show history... only — never a stale/misleading 'live' indicator", which
    itself implies history stays normally billing-gated).
    """
    student_parent_service = container.resolve(StudentParentApplicationService)
    assignment_service = container.resolve(StudentAssignmentApplicationService)

    parent_id = await _resolve_parent_id(principal, container)
    own_children = await student_parent_service.list_students_for_parent(
        ListStudentsForParentQuery(parent_id=parent_id),
        uow=container.resolve(TransportOpsUnitOfWork),
    )
    if not any(s.student_id == student_id for s in own_children):
        raise NotFoundError(f"Student {student_id} not found.")

    assignment = await assignment_service.get_active_assignment_for_student(
        student_id, uow=container.resolve(TransportOpsUnitOfWork)
    )
    assignment_state = (
        AssignmentState(assignment.status) if assignment is not None else AssignmentState.REMOVED
    )

    if safety_override and assignment_state == AssignmentState.ACTIVE:
        return PolicyDecision(allowed=True)

    organization_service = container.resolve(OrganizationApplicationService)
    organization_uow = container.resolve(OrganizationUnitOfWork)
    organization = await organization_service.get_organization_by_id(
        GetOrganizationByIdQuery(organization_id=principal.org_id), uow=organization_uow
    )
    billing_model = BillingModel(organization.billing_model)

    subscription_state = None
    if billing_model == BillingModel.PARENT_PAYS:
        billing_service = container.resolve(BillingApplicationService)
        billing_uow = container.resolve(BillingUnitOfWork)
        subscription = await billing_service.get_active_subscription_for_subscriber(
            "parent", principal.user_id, uow=billing_uow
        )
        subscription_state = (
            SubscriptionState(subscription.status) if subscription is not None else None
        )

    policy = SubscriptionAccessPolicy()
    return policy.evaluate(
        assignment_state=assignment_state,
        billing_model=billing_model,
        subscription_state=subscription_state,
    )


async def enforce_cr1(
    *,
    principal: Principal,
    student_id: str,
    container: Container,
    safety_override: bool = False,
) -> None:
    """Raises `AuthorizationError` (403) on a CR-1 denial. Only applies to the Parent role —
    LLD §5.4: "Org Admin, Driver, and RAAD staff access is unaffected" — a no-op for every
    other role, matching that exact scope note."""
    if principal.role != Role.PARENT:
        return
    decision = await resolve_cr1_decision(
        principal=principal,
        student_id=student_id,
        container=container,
        safety_override=safety_override,
    )
    if not decision.allowed:
        raise ParentAccessDeniedError(
            reason=decision.reason, required_action=decision.required_action
        )


async def _resolve_parent_id(principal: Principal, container: Container) -> str:
    parent_service = container.resolve(ParentApplicationService)
    parent_uow = container.resolve(TransportOpsUnitOfWork)
    parent = await parent_service.get_parent_by_user_id(principal.user_id, uow=parent_uow)
    if parent is None:
        raise NotFoundError("No Parent profile for this user.")
    return parent.id


async def find_owned_student_id_for_vehicle(
    *, principal: Principal, vehicle_id: str, container: Container
) -> str | None:
    """Resolves "which of this Parent's children is this vehicle about" — needed because the
    tracking routes are identified by `vehicle_id`/`trip_id`, not `student_id` (API Contracts
    §4.4), while CR-1 itself is evaluated per-child (LLD §5.4). Returns `None` (caller raises
    `NotFoundError`, not `AuthorizationError` — same 404-over-403 posture) if none of the
    Parent's children is currently assigned to this vehicle at all."""
    parent_id = await _resolve_parent_id(principal, container)
    student_parent_service = container.resolve(StudentParentApplicationService)
    assignment_service = container.resolve(StudentAssignmentApplicationService)

    children = await student_parent_service.list_students_for_parent(
        ListStudentsForParentQuery(parent_id=parent_id),
        uow=container.resolve(TransportOpsUnitOfWork),
    )
    for child in children:
        assignment = await assignment_service.get_active_assignment_for_student(
            child.student_id, uow=container.resolve(TransportOpsUnitOfWork)
        )
        if assignment is not None and assignment.vehicle_id == vehicle_id:
            return child.student_id
    return None


async def resolve_tracking_decision(
    *,
    principal: Principal,
    organization_id: str,
    vehicle_id: str,
    is_trip_active: bool,
    container: Container,
) -> PolicyDecision:
    """`TrackingVisibilityPolicy` (`.claude/rules/security.md` #4's mandatory four-dimension
    predicate), wired for real for the first time (pre-production review Critical/High finding:
    "never invoked anywhere"). Composes the four inputs from mechanisms this phase already
    built, rather than re-deriving them: `has_capability`/`within_scope` from RBAC
    (`require_permission`, already gates the route before this runs) + `ScopeResolver`;
    `has_ownership`/`within_time_window` from CR-1 (`resolve_cr1_decision`, called with
    `safety_override=is_trip_active` — the D4/CR-1 reconciliation, see that function's own
    docstring) for Parent callers, or unconditionally granted for Org Admin/RAAD staff (API
    Contracts §3.2: "Ops monitoring... Org Admin 24/7").
    """
    resolver = container.resolve(ScopeResolver)
    org_scope = await resolver.effective_org_scope(principal)
    within_scope = org_scope.allows(organization_id)

    if principal.role == Role.PARENT:
        student_id = await find_owned_student_id_for_vehicle(
            principal=principal, vehicle_id=vehicle_id, container=container
        )
        if student_id is None:
            has_ownership = False
            has_capability = False
            within_time_window = False
        else:
            cr1_decision = await resolve_cr1_decision(
                principal=principal,
                student_id=student_id,
                container=container,
                safety_override=is_trip_active,
            )
            has_ownership = True
            has_capability = cr1_decision.allowed
            within_time_window = is_trip_active
    else:
        # Org Admin / RAAD staff — capability already enforced by `require_permission`, no
        # per-request CR-1 evaluation (LLD §5.4: "Org Admin... access is unaffected"),
        # ownership reduces to tenant/region scope, and visibility is 24/7 (API Contracts §3.2).
        has_capability = True
        has_ownership = within_scope
        within_time_window = True

    policy = TrackingVisibilityPolicy()
    return policy.evaluate(
        has_capability=has_capability,
        within_scope=within_scope,
        has_ownership=has_ownership,
        within_time_window=within_time_window,
    )


async def resolve_d5_decision(
    *, principal: Principal, device_organization_id: str, container: Container
) -> PolicyDecision:
    """D5 (Backend LLD §5.2/§5.4; `.claude/rules/jt1078.md` #1: "Parents have zero reachable
    path to video, anywhere, ever"). Resolves `org_scope` via the same `ScopeResolver` used
    everywhere else (`interfaces/http/deps.get_scope`'s identical resolution), then evaluates
    `VideoAccessPolicy` — a pure role + scope check, no cross-module orchestration needed
    beyond scope resolution itself.
    """
    resolver = container.resolve(ScopeResolver)
    org_scope: TenantRegionScope = await resolver.effective_org_scope(principal)
    policy = VideoAccessPolicy()
    return policy.evaluate(
        principal=principal,
        device_organization_id=device_organization_id,
        org_scope=org_scope,
    )


async def enforce_d5(
    *, principal: Principal, device_organization_id: str, container: Container
) -> None:
    """Raises `VideoForbiddenError` (403, `VIDEO_FORBIDDEN` per API Contracts §5.2) on a D5
    denial. Unlike CR-1, this applies unconditionally — D5 is not role-scoped the way CR-1 is;
    `VideoAccessPolicy.evaluate` itself already returns `denied` for every non-eligible role
    (Parent/Driver included), so no role short-circuit is needed here."""
    decision = await resolve_d5_decision(
        principal=principal,
        device_organization_id=device_organization_id,
        container=container,
    )
    if not decision.allowed:
        raise VideoForbiddenError("Video access denied.")
