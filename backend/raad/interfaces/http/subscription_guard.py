"""Tenant-wide SaaS subscription enforcement (ADR-0039 §2/§3).

**This is the single place a suspended organization is actually stopped.** It is attached once,
as a dependency on `api_router` itself (`interfaces/http/api_v1.py`), so it covers **every**
`/api/v1` route — including routes added later. A new endpoint cannot forget to opt in; it has
to deliberately opt *out* by being added to `_EXEMPT_PATH_PREFIXES` below, which is a visible,
reviewable change.

**Why a router dependency rather than middleware.** `SecurityContextMiddleware` runs before
FastAPI has routed the request, so a middleware implementation would have to re-implement path
matching to apply the exemption list, and would run before the `Principal` is attached. A
router-level dependency runs after both — which is exactly the information this decision needs.

**Why this is not in `policy_guards.py`.** That module orchestrates *per-resource* decisions
(CR-1 tracking visibility, D5 video access) and reaches into several modules' application
services to resolve ownership facts. This guard asks one question about the tenant as a whole
and is wired at a completely different level (once, globally, versus per-route). Keeping them
separate keeps `policy_guards`' own already-dense responsibilities intact.

**Cost.** One indexed lookup per authenticated tenant-role request; platform roles short-circuit
before any I/O at all. Deliberately uncached: requirement 39M demands that the *next* request
after suspension be rejected, and a cache is precisely what would break that guarantee. If this
ever needs optimising, the right shape is a short-TTL cache invalidated by the
`SubscriptionSuspended`/`SubscriptionReactivated` events the domain already emits — not a
longer TTL.
"""

from __future__ import annotations

from fastapi import Depends, Request

from raad.core.di.container import Container
from raad.core.errors.exceptions import OrganizationSubscriptionInactiveError
from raad.core.policies.organization_access import (
    OrganizationAccessPolicy,
    OrganizationSubscriptionState,
)
from raad.core.tenancy.principal import Principal, Role
from raad.interfaces.http.deps import get_container
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.application.services import BillingApplicationService

#: RAAD's own staff. Not members of any tenant, so a tenant's subscription state says nothing
#: about whether they may work. Requirement 39G is explicit that these must keep functioning
#: against a suspended organization — otherwise nobody could inspect one, and reactivating a
#: suspended school would be impossible, making suspension irreversible.
#:
#: Keyed off `Role`, not off a permission, deliberately: this is a statement about *who the
#: caller is*, not *what they may do*. A permission-keyed bypass would also be self-granting —
#: a suspended tenant's own Org Admin holds `iam` permission-management routes, so a
#: permission-based check could be edited into a bypass from inside the suspended tenant.
_PLATFORM_ROLES = frozenset(
    {
        Role.FOUNDER,
        Role.REGIONAL_MANAGER,
        Role.SUPPORT_STAFF,
        Role.FINANCE_STAFF,
    }
)

#: Routes a suspended organization must still reach. Each one is here for a specific reason, and
#: the list is deliberately short enough to audit at a glance.
#:
#: - `/auth`  — login/refresh must keep working. Blocking here would make the state
#:              undiagnosable: the user would see a credentials failure and conclude their
#:              password was wrong.
#: - `/me`    — the caller must be able to find out *why* they are blocked. `GET /me` is
#:              self-scoped from `principal.user_id` alone and exposes no billing internals.
#: - `/billing` — **the recovery path, and the most important entry here.** An Org Admin who
#:              cannot reach billing can never pay, so suspension would be permanent and
#:              self-sealing: a trap, not a business rule. This is what makes the whole
#:              lifecycle reversible.
#:
#: `/health*` and `/metrics` need no entry — they are mounted on the app directly, outside
#: `api_router`, so this dependency never runs for them.
_EXEMPT_PATH_PREFIXES: tuple[str, ...] = (
    "/api/v1/auth",
    "/api/v1/me",
    "/api/v1/billing",
)


def _is_exempt(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _EXEMPT_PATH_PREFIXES)


def _details_for(principal: Principal, subscription) -> dict | None:
    """Requirement 39K's graded disclosure. An ordinary member (Driver, Parent, and any future
    non-admin tenant role) gets nothing beyond the generic message — a driver has no business
    reading their school's billing position, and leaking "amount due" to every parent would be
    a real disclosure problem. An Org Admin gets what they need to act."""
    if principal.role is not Role.ORG_ADMIN or subscription is None:
        return None
    return {
        "subscription_status": subscription.status,
        "current_period_end": (
            subscription.current_period_end.isoformat()
            if subscription.current_period_end is not None
            else None
        ),
        "grace_period_ends_at": (
            subscription.grace_period_ends_at.isoformat()
            if subscription.grace_period_ends_at is not None
            else None
        ),
    }


async def _resolve_subscription_state(
    principal: Principal, *, container: Container
) -> tuple[bool, object | None]:
    """Resolves the caller's organization subscription, returning
    `(enforcement_is_possible, subscription_dto_or_None)`.

    **`try_resolve`, not `resolve`, and the distinction matters.** The billing subsystem is
    bound only when a database is configured (`core/di/bootstrap.py`). If it is genuinely
    *unbound*, this deployment has no subscription data at all — there is nothing to enforce
    against, and hard-failing here would turn every route and every WebSocket into a 500 rather
    than a meaningful denial. That is reported as "enforcement not possible" and the caller
    allows, on the same bounded-blast-radius reasoning `OrganizationAccessPolicy` documents for
    a `None` subscription: an un-deployed billing subsystem must not read as "every tenant is
    delinquent".

    This is **not** a general fail-open. If billing *is* bound and the lookup then raises (a
    database error, say), the exception propagates and the request fails — never silently
    granted. The only thing treated as "allow" is the explicit absence of the subsystem.
    """
    policy = container.try_resolve(OrganizationAccessPolicy)
    billing_service = container.try_resolve(BillingApplicationService)
    uow = container.try_resolve(BillingUnitOfWork)
    if policy is None or billing_service is None or uow is None:
        return False, None

    subscription = await billing_service.get_current_subscription_for_organization(
        principal.org_id, uow=uow
    )
    return True, subscription


def _decide(
    container: Container, subscription: object | None
) -> "PolicyDecision":  # noqa: F821 - forward ref for readability only
    policy = container.resolve(OrganizationAccessPolicy)
    state = (
        OrganizationSubscriptionState(subscription.status)
        if subscription is not None
        else None
    )
    return policy.evaluate(subscription_state=state, is_platform_role=False)


async def is_organization_access_allowed(
    principal: Principal, *, container: Container
) -> bool:
    """ADR-0039 §4 — the same decision `enforce_organization_subscription` makes, as a plain
    boolean for callers that cannot raise an HTTP error.

    Used by the two WebSocket connect handlers (`/ws/tracking`, `/ws/notifications`), which must
    close the socket with a close code rather than return a JSON envelope. Sharing this function
    is the point: a suspended tenant must not keep consuming realtime services just because that
    surface forgot to ask (requirement 39M), and two independent implementations of the same
    rule would eventually disagree.
    """
    if principal.role in _PLATFORM_ROLES:
        return True
    if principal.org_id is None:
        return True

    enforceable, subscription = await _resolve_subscription_state(
        principal, container=container
    )
    if not enforceable:
        return True
    return _decide(container, subscription).allowed


async def enforce_organization_subscription(
    request: Request,
    container: Container = Depends(get_container),
) -> None:
    """Raises `OrganizationSubscriptionInactiveError` (403) when the caller's organization has
    no usable subscription. Returns `None` on success — this is a side-effecting guard, not a
    value provider.

    **The `Principal` is read from `request.state`, deliberately not via
    `Depends(get_principal)`.** FastAPI resolves a dependency's own sub-dependencies *before*
    calling it, so a `Depends(get_principal)` parameter here would raise `AuthenticationError`
    on every genuinely public route — `POST /auth/login` most importantly — turning login into
    a 401 for everyone. Reading `request.state.principal` directly lets an unauthenticated
    request fall through to the route, which then applies its own `require_permission` (or, for
    the public auth routes, deliberately applies none). Authentication is not this guard's job;
    it only asks whether an *already-authenticated* tenant user's organization is in good
    standing.

    Order of the cheap checks matters: unauthenticated requests, exempt paths and platform roles
    all short-circuit *before* any database work, so the common platform-admin case and the
    login path add no query at all.
    """
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None:
        return

    if _is_exempt(request.url.path):
        return

    if principal.role in _PLATFORM_ROLES:
        return

    if principal.org_id is None:
        # A tenant role with no organization cannot be checked against one. This should be
        # unreachable (`Principal.org_id` is populated for every tenant role at token issue),
        # and is deliberately fail-open rather than fail-closed for the same bounded-blast-
        # radius reason `OrganizationAccessPolicy` documents for a `None` subscription: a
        # token-shape bug should not lock every user of a paying customer out of the platform.
        return

    enforceable, subscription = await _resolve_subscription_state(
        principal, container=container
    )
    if not enforceable:
        # No billing subsystem bound in this deployment — see `_resolve_subscription_state`.
        return

    decision = _decide(container, subscription)
    if decision.allowed:
        return

    raise OrganizationSubscriptionInactiveError(
        "Your organization's RAAD subscription is inactive. Please contact your "
        "organization administrator or RAAD support.",
        reason=decision.reason,
        required_action=decision.required_action,
        details=_details_for(principal, subscription),
    )


__all__ = [
    "enforce_organization_subscription",
    "_EXEMPT_PATH_PREFIXES",
    "_PLATFORM_ROLES",
]
