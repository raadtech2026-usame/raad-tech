"""`SubscriptionAccessPolicy` — CR-1 (Backend LLD §5.4, revising the former D4
`SafetyCapabilityPolicy`). Governs whether the **Parent** role/app may access any parent
feature (live GPS, notifications, trip history — "the whole parent surface", LLD §5.4).

**Ownership, corrected here.** Backend LLD §17's own core-module table places this policy's
"home" explicitly inside `core/policies` (*"`policies` — Base policy abstractions incl.
`SubscriptionAccessPolicy` (CR-1) and `VideoAccessPolicy` (D5) homes — Access-critical"*), not
inside the `billing` bounded-context module. This module's own package docstring previously read
*"added once their owning modules (`billing`, `video`) exist"* — that phrasing was never grounded
in an approved document (confirmed by a dedicated documentation audit before this phase) and is
corrected in `__init__.py`. `billing`/`transport_ops` supply this policy's two *inputs*; they do
not host the policy object itself.

**Purity (LLD §5.4 verbatim): "Inputs (all resolved before the policy is called; the policy
itself is pure)."** `evaluate()` performs no I/O and imports nothing from `raad.modules.*` — the
two inputs below are primitives/local enums, never another module's domain objects, matching
the same "cross-module data is opaque, resolved by the caller" convention every bounded-context
module already uses for its own cross-module references (e.g. `transport_ops.domain.
value_objects.VehicleId`).

**ADR-0016 amendment (RAAD business model realignment) — `billing_model` input removed.** The
original LLD §5.4 decision table conditioned `subscription_state` on a `billing_model` input
(`ORGANIZATION_PAYS` skipped the check; `PARENT_PAYS` didn't) — that distinction no longer
exists now that RAAD bills Organizations only (ADR-0016). `subscription_state` is now a single,
unconditional check against the organization's own subscription:

| assignment_state | subscription_state | Decision | required_action |
|---|---|---|---|
| not `ACTIVE` | *(any)* | DENY — `ASSIGNMENT_INACTIVE` | `NONE` |
| `ACTIVE` | `ACTIVE` | GRANT | `NONE` |
| `ACTIVE` | expired / inactive | DENY — `SUBSCRIPTION_EXPIRED` | `REDIRECT_TO_PAYMENT` |

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
  invalidated by `SubscriptionExpired`/`SubscriptionRenewed` and the four `StudentAssignment*`
  events (`OrganizationBillingModelChanged` no longer applies — that concept was removed by
  ADR-0016). Caching is an infra/worker concern, not this policy's; not built here.
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


def parse_subscription_state(status: str | None) -> SubscriptionState | None:
    """Total mapping from a stored `subscriptions.status` onto this enum's five values.

    ADR-0039 added `past_due` and `grace_period` to the *column* while deliberately leaving this
    enum at the original five (see `core.policies.organization_access` for why: widening it here
    would silently change CR-1's parent-notification behaviour as a side effect of a billing
    change). The consequence was a crash rather than a decision - `SubscriptionState("past_due")`
    raises `ValueError`, and the notification worker would turn that into a retried, dead-lettered
    event for every parent notification on an organization in either new state.

    An unmodelled status therefore resolves to `None`, which `SubscriptionAccessPolicy` already
    treats exactly as this enum's own decision table requires: "not ACTIVE", and so non-granting
    (LLD 5.4's binary ACTIVE-vs-everything-else reading). That preserves the documented behaviour
    instead of inventing a richer rule the table does not draw.

    **Flagged, deliberately not decided here:** this means a parent loses non-safety notifications
    the moment their school goes `past_due`, while ADR-0039 grants that same school continued API
    access for the whole grace window. The two surfaces disagree. Reconciling them is a product
    decision about the CR-1 decision table, which ADR-0039 explicitly declined to make; it needs
    its own ADR, not a quiet edit here.
    """
    if status is None:
        return None
    try:
        return SubscriptionState(status)
    except ValueError:
        return None


_REASON_ASSIGNMENT_INACTIVE = "ASSIGNMENT_INACTIVE"
_REASON_SUBSCRIPTION_EXPIRED = "SUBSCRIPTION_EXPIRED"
_ACTION_REDIRECT_TO_PAYMENT = "REDIRECT_TO_PAYMENT"


class SubscriptionAccessPolicy(Policy):
    """CR-1. See module docstring for the full decision table and its citations."""

    def evaluate(
        self,
        *,
        assignment_state: AssignmentState,
        subscription_state: SubscriptionState | None = None,
    ) -> PolicyDecision:
        """ADR-0016: `subscription_state` is now always consulted (no more `billing_model`
        branch to skip it) — `None` means "the organization has no subscription row at all",
        treated the same as a non-`ACTIVE` one."""
        if assignment_state != AssignmentState.ACTIVE:
            return PolicyDecision(
                allowed=False, reason=_REASON_ASSIGNMENT_INACTIVE, required_action=None
            )

        if subscription_state == SubscriptionState.ACTIVE:
            return PolicyDecision(allowed=True)

        return PolicyDecision(
            allowed=False,
            reason=_REASON_SUBSCRIPTION_EXPIRED,
            required_action=_ACTION_REDIRECT_TO_PAYMENT,
        )


__all__ = [
    "AssignmentState",
    "parse_subscription_state",
    "SubscriptionState",
    "SubscriptionAccessPolicy",
]
