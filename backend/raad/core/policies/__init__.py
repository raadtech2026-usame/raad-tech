"""Access-critical domain policies (Backend LLD §17 `policies`; §5.1/§5.3): encapsulated
decision objects returning `PolicyDecision` (`allowed` plus an optional `reason`/
`required_action`), enforced in application/domain code, never re-derived ad hoc at a call site
(LLD §5.3's own rationale — "cannot be bypassed by a forgotten call-site check").

**Ownership — corrected in Phase 14.** This package's own docstring previously read *"added
once their owning modules (`billing`, `video`) exist"*. That was never grounded in an approved
document: Backend LLD §17's core-module table places both concrete policies' "home" here, in
`core/policies`, explicitly — not inside a bounded-context module. A dedicated documentation
audit (before this phase) confirmed no document ever assigns `SubscriptionAccessPolicy` to
`billing` or `VideoAccessPolicy` to `video`; `billing`/`transport_ops`/`organization`/
`fleet_device` only supply pre-resolved *inputs*, the same "opaque, caller-resolved cross-module
data" treatment every bounded-context module already gives its own cross-module references.

**Phase 14 addition:** `SubscriptionAccessPolicy` (CR-1, `subscription_access.py`) and
`VideoAccessPolicy` (D5, `video_access.py`) are now implemented — see each module's own
docstring for its full decision table/derivation and the documentation gaps flagged along the
way. `Policy`/`PolicyDecision` moved to `base.py` (this file no longer holds logic directly),
matching `core/errors/__init__.py`/`core/tenancy/__init__.py`'s established thin-re-export-hub
shape.
"""

from raad.core.policies.base import Policy, PolicyDecision
from raad.core.policies.subscription_access import (
    AssignmentState,
    BillingModel,
    SubscriptionAccessPolicy,
    SubscriptionState,
)
from raad.core.policies.video_access import VideoAccessPolicy

__all__ = [
    "AssignmentState",
    "BillingModel",
    "Policy",
    "PolicyDecision",
    "SubscriptionAccessPolicy",
    "SubscriptionState",
    "VideoAccessPolicy",
]
