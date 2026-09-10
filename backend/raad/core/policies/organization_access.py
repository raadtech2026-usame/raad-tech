"""`OrganizationAccessPolicy` (ADR-0039) — the single, tenant-wide decision object governing
whether an organization's users may use the RAAD application at all, based on that
organization's own SaaS subscription state.

**How this differs from `SubscriptionAccessPolicy`, which it does not replace.** The two look
similar and are deliberately separate:

| | `SubscriptionAccessPolicy` (CR-1) | `OrganizationAccessPolicy` (ADR-0039) |
|---|---|---|
| Governs | the **Parent** surface only | **every** user of the tenant |
| Also consumes | `assignment_state` (parent↔student link) | nothing else |
| Answers | "may this parent see their child's bus?" | "is this school's account in good standing?" |
| Called from | `policy_guards.resolve_cr1_decision` | `subscription_guard`, on every `/api/v1` route |

CR-1's own safety-over-billing carve-out (`.claude/rules/security.md` #6 — a genuinely live
position during an active trip is never revoked by a billing lapse) lives entirely in
`SubscriptionAccessPolicy`'s caller and is unaffected by this policy. This one is the coarser,
outer gate: it decides whether the tenant is inside the building at all.

**Purity, matching `SubscriptionAccessPolicy`'s established contract exactly.** `evaluate()`
performs no I/O and imports nothing from `raad.modules.*`. Both inputs are resolved by the
caller and passed as primitives/local enums. This is what makes the policy trivially testable
against all seven states × both role classes without a database.

**The state→access mapping lives here and nowhere else.** `.claude/rules/backend.md` #6's
principle ("granted by a single, tested capability policy ... never by scattered
`if subscription_active` checks") is the whole point of this file. Never re-derive "is this
state allowed in?" at a call site — ask this policy.
"""

from __future__ import annotations

from enum import Enum

from raad.core.policies.base import Policy, PolicyDecision

#: Machine-readable denial code surfaced in the standard error envelope
#: (`{error: {code, message, correlation_id}}`, `.claude/rules/api.md` #4). Clients — including
#: the web dashboard's own interceptor — branch on this string, so it is part of the wire
#: contract and must not be renamed without a version bump.
ORGANIZATION_SUBSCRIPTION_INACTIVE = "ORGANIZATION_SUBSCRIPTION_INACTIVE"


class OrganizationSubscriptionState(str, Enum):
    """Mirrors `billing.domain.value_objects.SubscriptionStatus`'s wire values exactly, so a
    caller can convert a resolved `SubscriptionDTO.status` string directly via
    `OrganizationSubscriptionState(value)` — without `core` importing `raad.modules.billing`
    (which the architecture-gate module-boundary test forbids, and which would invert the
    dependency direction `.claude/rules/backend.md` #2 fixes).

    Kept as its own enum rather than reusing `subscription_access.SubscriptionState` because
    that one predates ADR-0039 and deliberately models only the original five values, with a
    binary ACTIVE-vs-everything-else reading its own LLD §5.4 decision table requires. Widening
    it in place would silently change CR-1's parent-surface behaviour for `past_due` and
    `grace_period` — a real behavioural change to a safety-adjacent policy, made as a side
    effect. Two enums, each honest about its own decision table, is the safer shape.
    """

    TRIAL = "trial"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    GRACE_PERIOD = "grace_period"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


#: States in which the tenant may use the application.
#:
#: **Amended 2026-09-09 (direct user directive), narrowing ADR-0039 §1's original table.**
#: `PAST_DUE` used to grant; it now denies. The rule the platform owner asked for is "an unpaid
#: invoice closes the dashboard", and `past_due` is precisely the state that means *unpaid and
#: past the due date*. It was the single widest hole in the enforcement: an organization could
#: stop paying and keep full access indefinitely, because nothing escalated `past_due` on its own
#: without the scheduled sweep completing.
#:
#: `GRACE_PERIOD` still grants, and that distinction is the whole point of the amendment. A grace
#: period that does not grant access is not a grace period — it is just a slower `suspended`, and
#: ADR-0039's lifecycle would have no state left that means "we know you are late, keep working
#: while you sort it out". Access ends when grace *ends*, which is exactly what the platform owner
#: described. For a product whose users are schools tracking children, that ordering matters:
#: the cutoff is deliberate and dated, never a surprise at the stroke of a billing hour.
#:
#: `TRIAL` grants because a subscription that has not started billing has nothing to be
#: delinquent about.
_GRANTING_STATES = frozenset(
    {
        OrganizationSubscriptionState.TRIAL,
        OrganizationSubscriptionState.ACTIVE,
        OrganizationSubscriptionState.GRACE_PERIOD,
    }
)

#: Denial reason for a tenant that has no subscription row at all, distinct from a tenant whose
#: subscription has lapsed. The two need different copy and different operator action — "nobody
#: ever sold this school a plan" is a provisioning problem, "they stopped paying" is a billing
#: one — so the wire contract distinguishes them rather than making the client guess.
ORGANIZATION_SUBSCRIPTION_MISSING = "ORGANIZATION_SUBSCRIPTION_MISSING"


class OrganizationAccessPolicy(Policy):
    """Pure decision: may a user of this organization use the application right now?"""

    def evaluate(  # type: ignore[override]
        self,
        *,
        subscription_state: OrganizationSubscriptionState | None,
        is_platform_role: bool,
    ) -> PolicyDecision:
        """
        `is_platform_role` — the caller is RAAD's own staff (Founder / Regional Manager /
        Support Staff / Finance Staff), not a member of the tenant. Requirement 39G is explicit
        that these must keep working against a suspended organization, otherwise nobody could
        ever inspect or reactivate one. Resolved by the caller from `Principal.role`; see
        `interfaces/http/subscription_guard` for why the bypass keys off role rather than a
        permission.

        `subscription_state` — the organization's own subscription status, or `None` when the
        organization has **no subscription row at all**.

        **`None` now denies (amended 2026-09-09, direct user directive).** It used to grant, on
        the reasoning that an organization with no subscription is un-onboarded rather than
        delinquent, and that denying would turn a provisioning bug into a total outage for that
        school. That reasoning was sound and the outcome was still wrong: a provisioning bug is
        exactly what happened — `open_organization_subscription` failed on every call for the
        entire life of the feature — and this fail-open is what made it invisible. Every
        organization on the platform had unrestricted access with no subscription, and no surface
        anywhere reported it. Fail-open turned a loud, one-organization failure into a silent,
        platform-wide one.

        Two things make denying safe now, and both had to land first: onboarding no longer
        reports success when provisioning fails (it compensates and re-raises), so this state can
        no longer be *created* silently; and `/billing` stays exempt from the guard, so an
        affected organization can still reach the page that fixes it.
        """
        if is_platform_role:
            return PolicyDecision(allowed=True)

        if subscription_state is None:
            return PolicyDecision(
                allowed=False,
                reason=ORGANIZATION_SUBSCRIPTION_MISSING,
                required_action="REDIRECT_TO_PAYMENT",
            )

        if subscription_state in _GRANTING_STATES:
            return PolicyDecision(allowed=True)

        return PolicyDecision(
            allowed=False,
            reason=ORGANIZATION_SUBSCRIPTION_INACTIVE,
            #: Same documented value set `SubscriptionAccessPolicy` already uses for its own
            #: denial, so a client that already handles one handles this too.
            required_action="REDIRECT_TO_PAYMENT",
        )


__all__ = [
    "ORGANIZATION_SUBSCRIPTION_INACTIVE",
    "ORGANIZATION_SUBSCRIPTION_MISSING",
    "OrganizationAccessPolicy",
    "OrganizationSubscriptionState",
]
