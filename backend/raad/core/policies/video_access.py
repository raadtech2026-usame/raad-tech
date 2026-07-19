"""`VideoAccessPolicy` — D5 (Backend LLD §5.2's contract skeleton, §5.4's closing note; Project
Brief D5). *"Parent, Driver -> always false (no reachable path). Org Admin (own org), permitted
RAAD staff (in-scope) -> true, audited."*

**Signature translation, flagged.** LLD §5.2 gives this as a language-neutral skeleton —
`can_access_live_or_playback(principal, device, org_scope) -> bool` — explicitly "no method
bodies / no logic... design artifacts, not implementation" (§0's own notation disclaimer). This
module implements it as `evaluate(...)` instead, satisfying `Policy`'s abstract method (the same
generic shape `SubscriptionAccessPolicy.evaluate` already implements) and returning
`PolicyDecision` rather than a bare `bool` — matching this phase's own "PolicyDecision
integration" scope item, and giving both policies in this package a uniform return shape. D5
documents no `reason`/`required_action` taxonomy for video the way CR-1 does
(`ASSIGNMENT_INACTIVE`/`SUBSCRIPTION_EXPIRED`); the API-layer error code is a fixed
`VIDEO_FORBIDDEN` regardless of which ineligible case applied (API Contracts §5.2), so this
policy always returns `reason=None`.

**`device`/`org_scope` translated to primitives + the existing `core.tenancy` types, not a
`fleet_device.domain.entities.Device` import.** `core/` must not depend on any bounded-context
module (the same dependency-direction rule every module's own domain layer already follows in
reverse) — `device` becomes `device_organization_id: str` (the one fact this policy actually
needs from a `Device`/`Vehicle`), and `org_scope` reuses `core.tenancy.scope.TenantRegionScope`
(Phase 2 §17.4's own `effective_org_scope` output type) verbatim — already the exact "resolved
scope, applied as a filter" shape LLD's own pseudocode parameter name describes, and already a
`core/` package so no boundary is crossed importing it.

**Role gate, derived from API Contracts §3.2's capability matrix, not invented.** That table's
"Live video / playback" row reads: Founder `✅*`, Regional Manager `✅*(permitted)`, Support
`✅*(permitted)`, **Finance `❌`**, Org Admin `✅ own org`, Driver `❌`, Parent `❌ (D5)`. Finance
Staff is therefore excluded from the "permitted RAAD staff" LLD prose despite being RAAD staff —
confirmed against the API Contracts table rather than assumed from the LLD sentence alone, which
by itself doesn't enumerate the RAAD roles.

**"Own org" / "in-scope", unified — not two separate branches.** Both reduce to the identical
check once `org_scope` is correctly resolved per `core.tenancy.resolver.ScopeResolver`'s own
documented formula (tenant roles -> their own `organization_id` only; Founder -> unrestricted;
Regional Manager/Support -> their assigned regions/orgs) — so `org_scope.allows(device_
organization_id)` is both "is this Org Admin's own org" and "is this RAAD staff member in
scope" for the *correct* eligible roles, with no separate code path needed.

**"Permitted", flagged as a documentation gap, not invented.** LLD §5.4's phrase "**permitted**
RAAD staff (in-scope)" reads as *additional* to tenant/region scope — but no document specifies
what makes a Regional Manager/Support member "permitted" beyond their role and scope, and
CLAUDE.md's own "Known gaps" section confirms the RBAC permission matrix itself is still
"approved-open," not available to consult. Read in the context of API Contracts §3.1's four
independent authorization layers (Authentication -> RBAC -> Tenant/region scope -> Domain
policies), "permitted" is treated here as referring to **layer 2, RBAC** (`require_permission`,
already a separate, pre-existing mechanism in this codebase, itself still pending the same
matrix) — a check this policy is not responsible for re-implementing, not a fourth input this
policy silently invents. If a future-approved RBAC matrix turns out to gate video access by
something *other* than role + org-scope, this policy's role-eligibility set will need revisiting
— flagged here for that future phase, not guessed at now.

**Not implemented here:** audit logging ("audited" — D5, `.claude/rules/security.md` #8) is an
enforcement-point/`platform_audit` concern, not this pure decision function's job — same
separation `SubscriptionAccessPolicy`'s module docstring draws for its own "not implemented
here" list.
"""

from __future__ import annotations

from raad.core.policies.base import Policy, PolicyDecision
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope

_VIDEO_ELIGIBLE_ROLES = frozenset(
    {Role.FOUNDER, Role.REGIONAL_MANAGER, Role.SUPPORT_STAFF, Role.ORG_ADMIN}
)


class VideoAccessPolicy(Policy):
    """D5. See module docstring for the full role/scope derivation and its citations."""

    def evaluate(
        self,
        *,
        principal: Principal,
        device_organization_id: str,
        org_scope: TenantRegionScope,
    ) -> PolicyDecision:
        if principal.role not in _VIDEO_ELIGIBLE_ROLES:
            return PolicyDecision(allowed=False)

        return PolicyDecision(allowed=org_scope.allows(device_organization_id))


__all__ = ["VideoAccessPolicy"]
