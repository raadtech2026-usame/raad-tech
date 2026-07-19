"""`SubscriptionAccessPolicy` — CR-1 (Backend LLD §5.4, revising the former D4
`SafetyCapabilityPolicy`). Governs whether the **Parent** role/app may access any parent
feature (live GPS, notifications, trip history — "the whole parent surface", LLD §5.4).

**Ownership, corrected here.** Backend LLD §17's own core-module table places this policy's
"home" explicitly inside `core/policies` (*"`policies` — Base policy abstractions incl.
`SubscriptionAccessPolicy` (CR-1) and `VideoAccessPolicy` (D5) homes — Access-critical"*), not
inside the `billing` bounded-context module. This module's own package docstring previously read
*"added once their owning modules (`billing`, `video`) exist"* — that phrasing was never grounded
in an approved document (confirmed by a dedicated documentation audit before this phase) and is
corrected in `__init__.py`. `billing`/`transport_ops`/`organization` supply this policy's three
*inputs*; they do not host the policy object itself.

**Purity (LLD §5.4 verbatim): "Inputs (all resolved before the policy is called; the policy
itself is pure)."** `evaluate()` performs no I/O and imports nothing from `raad.modules.*` — the
three inputs below are primitives/local enums, never another module's domain objects, matching
the same "cross-module data is opaque, resolved by the caller" convention every bounded-context
module already uses for its own cross-module references (e.g. `transport_ops.domain.
value_objects.VehicleId`).

**Decision table (LLD §5.4 verbatim, assignment gate has highest precedence — business rule
3):**

| assignment_state | billing_model | subscription_state | Decision | required_action |
|---|---|---|---|---|
| not `ACTIVE` | *(any)* | *(any)* | DENY — `ASSIGNMENT_INACTIVE` | `NONE` |
| `ACTIVE` | `ORGANIZATION_PAYS` | *(ignored)* | GRANT | `NONE` |
| `ACTIVE` | `PARENT_PAYS` | `ACTIVE` | GRANT | `NONE` |
| `ACTIVE` | `PARENT_PAYS` | expired / inactive | DENY — `SUBSCRIPTION_EXPIRED` | `REDIRECT_TO_PAYMENT` |

`required_action`'s documented value set is `{NONE, REDIRECT_TO_PAYMENT}` (LLD §5.4's own
`AccessDecision` shape) — represented here as `None`/`"REDIRECT_TO_PAYMENT"` on
`PolicyDecision.required_action`, the natural Python reading of "NONE" as "no action", not a
third invented value.

**Not implemented here (out of this phase's scope, flagged rather than silently built):**
- **Enforcement** — *where* this policy gets called (`parent_access_guard`, the parent
  session/context endpoint, the WebSocket subscribe gate, the Notification Worker's recipient
  filter — all named in LLD §5.4/§11.3/§16.2) is a later phase's application/API-layer
  responsibility. This file only provides the pure decision function.
- **Caching / re-evaluation on events** — LLD §5.4 documents that cached decisions must be
  invalidated by `SubscriptionExpired`/`SubscriptionRenewed`, the four `StudentAssignment*`
  events, and `OrganizationBillingModelChanged`. Caching is an infra/worker concern, not this
  policy's; not built here.
- **Role scope note.** LLD §5.4: *"this policy governs the Parent role only. Org Admin, Driver,
  and RAAD staff access is unaffected."* This is a statement about *who a caller invokes this
  policy for*, not an input the policy itself consumes — LLD's own "Inputs" section lists exactly
  three, no `role`/`principal` parameter. Adding one would be inventing a fourth input no
  document names.
"""

from __future__ import annotations

from enum import Enum

from raad.core.policies.base import Policy, PolicyDecision


class AssignmentState(str, Enum):
    """LLD §5.4: "the state of the parent<->student transportation assignment: ACTIVE, or one
    of REMOVED / TRANSFERRED / GRADUATED / DISABLED (all treated as inactive)." Values match
    Database Design §6.7's `student_assignments.status` enum exactly (and, transitively,
    `transport_ops.domain.value_objects.StudentAssignmentStatus`'s values) so a caller can
    convert a resolved `StudentAssignmentDTO.status` string directly via
    `AssignmentState(value)` — without this module importing that module's domain type."""

    ACTIVE = "active"
    REMOVED = "removed"
    TRANSFERRED = "transferred"
    GRADUATED = "graduated"
    DISABLED = "disabled"


class BillingModel(str, Enum):
    """LLD §5.4 / Database Design (`organizations.billing_model`): the organization's chosen
    subscription model (Project Brief Ch. 9.2)."""

    ORGANIZATION_PAYS = "organization_pays"
    PARENT_PAYS = "parent_pays"


class SubscriptionState(str, Enum):
    """Database Design §8.2: `subscriptions.status ENUM(trial,active,suspended,expired,
    cancelled)`. LLD §5.4's own decision table only ever distinguishes `ACTIVE` from
    "expired / inactive" as a single bucket — every non-`ACTIVE` value here is treated
    uniformly as non-granting, matching that binary framing exactly rather than inventing a
    richer per-status rule the table doesn't draw."""

    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


_REASON_ASSIGNMENT_INACTIVE = "ASSIGNMENT_INACTIVE"
_REASON_SUBSCRIPTION_EXPIRED = "SUBSCRIPTION_EXPIRED"
_ACTION_REDIRECT_TO_PAYMENT = "REDIRECT_TO_PAYMENT"


class SubscriptionAccessPolicy(Policy):
    """CR-1. See module docstring for the full decision table and its citations."""

    def evaluate(
        self,
        *,
        assignment_state: AssignmentState,
        billing_model: BillingModel,
        subscription_state: SubscriptionState | None = None,
    ) -> PolicyDecision:
        """`subscription_state` defaults to `None` since LLD §5.4 documents it as "consulted
        only for `PARENT_PAYS`" — an `ORGANIZATION_PAYS` caller need not resolve it at all."""
        if assignment_state != AssignmentState.ACTIVE:
            return PolicyDecision(
                allowed=False, reason=_REASON_ASSIGNMENT_INACTIVE, required_action=None
            )

        if billing_model == BillingModel.ORGANIZATION_PAYS:
            return PolicyDecision(allowed=True)

        # PARENT_PAYS
        if subscription_state == SubscriptionState.ACTIVE:
            return PolicyDecision(allowed=True)

        return PolicyDecision(
            allowed=False,
            reason=_REASON_SUBSCRIPTION_EXPIRED,
            required_action=_ACTION_REDIRECT_TO_PAYMENT,
        )


__all__ = [
    "AssignmentState",
    "BillingModel",
    "SubscriptionState",
    "SubscriptionAccessPolicy",
]
