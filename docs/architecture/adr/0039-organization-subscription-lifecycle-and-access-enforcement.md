# ADR-0039: Organization Subscription Lifecycle and Tenant-Wide Access Enforcement

## Status

**Accepted** (direct user directive, 2026-09-04, requirement 39B–39M: *"This must be a REAL
system, not a UI-only subscription page ... Subscription enforcement MUST happen server-side ...
ALL users belonging to that organization must be blocked"*). Sequenced first, ahead of the ERP
build, by the user's own explicit choice via `AskUserQuestion`.

## Context

RAAD's intended business model is a multi-tenant SaaS: RAAD sells plans, an Organization
subscribes, the Organization pays monthly, and an Organization that stops paying eventually
loses access — every user of that tenant, not just its admin — while RAAD platform staff retain
full management access.

A deep audit of the existing implementation ran before any code was written (requirement 39's
own mandated first step). What it found:

### What genuinely exists

`plans`, `subscriptions`, `invoices`, `payments` tables with sane shapes; a real
`StripePaymentAdapter` (Payment Intents, HMAC-SHA256 webhook verification); a wired
`POST /billing/payments/callback`; and a same-state idempotency guard on `Payment.mark_paid`
with a regression test proving a replayed webhook cannot double-advance a billing period.
`Subscription.renew`/`expire`/`suspend`/`cancel` all exist as domain methods.

### Finding 1 — enforcement covers the Parent role only, on ~2 of 106 routes

`core.policies.subscription_access.SubscriptionAccessPolicy` exists and is DI-bound, but its own
module docstring states the scope verbatim:

> *"this policy governs the **Parent role only**. Org Admin, Driver, and RAAD staff access is
> unaffected."*

and, under "Not implemented here":

> *"**Enforcement** — where this policy gets called ... is a later phase's application/API-layer
> responsibility. This file only provides the pure decision function."*

That later phase never happened. The policy is invoked from exactly one call site —
`policy_guards.resolve_cr1_decision` — reaching only the two `/tracking` routes and the tracking
WebSocket's subscribe path. **An organization whose subscription is `suspended` or `expired`
today retains full access to ~104 of 106 API routes for `org_admin`, `driver` and staff users.**

### Finding 2 — there is no billing lifecycle, only an expiry guillotine

`sweep_expired_subscriptions` is the entire automation. Read in full, it scans every
subscription and expires any `trial`/`active`/`suspended` whose `current_period_end` has passed.
It transitions **ACTIVE → EXPIRED directly**. It never checks whether payment was received,
never attempts renewal despite `auto_renew` existing on the table, and there is no `past_due` or
grace concept anywhere. The live enum is `trial, active, suspended, expired, cancelled`.

### Finding 3 — recurring invoices are never generated

`Subscription.renew()` has exactly one call site: the payment-paid side-effect path.
`Invoice.issue()` runs when a subscription is first opened. **No job issues an invoice when a
billing period rolls over**, so the intended loop (*billing date arrives → payment must be
completed*) cannot even begin — period two never gets an invoice to pay.

### Finding 4 — stale Parent grants on the SaaS billing surface

The live `role_permissions` matrix grants `parent`: `billing.invoices.list`,
`billing.payments.create`, `billing.subscriptions.list`, `billing.plans.list`. These date to the
original RBAC seed (`5437a5d1651b`, 2026-07-21); ADR-0016's migration (`f4a1c9e7b302`,
2026-07-28) dropped the parent-billing *schema* but never revoked the *grants*. A parent can
therefore enumerate **RAAD's SaaS invoices to their school** and initiate payments against them.

## Decision

### 1. Seven subscription states, with `past_due` and `grace_period` given distinct meanings

`past_due` and `grace_period` are both named in the directive. Modelled naively they collapse
into one another, so each is given a meaning the other cannot serve:

| State | Meaning | App access |
|---|---|---|
| `TRIAL` | Opened, first period not yet started/billed | **Granted** |
| `ACTIVE` | Paid and inside the current period | **Granted** |
| `PAST_DUE` | Period ended with an unpaid invoice; the **automatic** grace window is running | **Granted** |
| `GRACE_PERIOD` | A platform admin **explicitly extended** grace beyond the automatic window | **Granted** |
| `SUSPENDED` | Grace exhausted, or suspended by a platform admin | **Denied** |
| `EXPIRED` | Terminal, ended without renewal | **Denied** |
| `CANCELLED` | Terminal, ended deliberately | **Denied** |

`GRACE_PERIOD` as *"a human decided to give this school more time"* is what makes requirement
39G's "Extend grace period where authorized" a real, auditable state transition rather than a
silent date edit — and it is distinguishable in reporting from schools that merely drifted into
`PAST_DUE`.

New columns on `subscriptions`: `past_due_since`, `grace_period_ends_at`, `suspended_at`,
`cancelled_at`, `expired_at`. The existing `current_period_end` already serves as the next
billing date; no separate column is invented for it.

### 2. Enforcement is one central dependency at the router aggregation point

`.claude/rules/backend.md` #6's principle — *"granted by a single, tested capability policy ...
never by scattered `if subscription_active` checks"* — is applied literally. Two new pieces:

- **`core/policies/organization_access.OrganizationAccessPolicy`** — pure and I/O-free, matching
  `SubscriptionAccessPolicy`'s established shape exactly: inputs resolved by the caller, no
  imports from `raad.modules.*`, no I/O. Decides GRANT/DENY from `(subscription_state,
  is_platform_role)`.
- **`interfaces/http/subscription_guard.enforce_organization_subscription`** — the single call
  site, attached as a dependency on `api_router` itself in `interfaces/http/api_v1.py`, so it
  covers **all** `/api/v1` routes including any route added later. A new endpoint cannot forget
  to opt in; it must deliberately opt *out*.

**Why a router dependency and not middleware.** `SecurityContextMiddleware` runs before FastAPI
routing and would have to re-implement path matching to apply an exemption list. A router-level
dependency runs after the `Principal` is resolved and after the route is known, which is exactly
the information the decision needs.

### 3. Platform roles are never blocked, and the recovery path is never blocked

Two exemptions, both deliberate and both tested:

**Platform roles bypass entirely** — `founder`, `regional_manager`, `support_staff`,
`finance_staff`. They are RAAD's own staff, not members of the tenant; requirement 39G is
explicit that they must retain access to view, inspect and reactivate a suspended organization.
The bypass keys off `Role`, not off a permission, because it is a statement about *who the
caller is* rather than *what they may do* — and because a suspended tenant must not be able to
grant itself a bypass by editing its own users' permissions.

**An exempt path allowlist** keeps a suspended organization able to dig itself out:

| Path prefix | Why |
|---|---|
| `/api/v1/auth` | Login/refresh must still work; blocking here would make the state undiagnosable |
| `/api/v1/me` | The caller must be able to learn *why* they are blocked |
| `/api/v1/billing` | **The recovery path.** An Org Admin who cannot reach billing can never pay, so suspension would be permanent — a trap, not a business rule |

`/health*` and `/metrics` are mounted outside `api_router` and are unaffected.

### 4. WebSockets are enforced at connect, not only at HTTP

A suspended tenant must not keep consuming realtime services because a socket was opened before
suspension (requirement 39M). `/ws/tracking` and `/ws/notifications` both evaluate the same
policy during their connect handshake and close with a policy-violation code when denied.

**Disclosed limitation, not silently assumed away:** an *already-open* socket is not torn down
at the instant of suspension. Enforcement happens at connect and on the tracking socket's own
subscribe path (which re-resolves per subscription change). A socket opened while active and
never re-subscribing can continue receiving frames until it disconnects. Closing that residual
window needs a suspension-event-driven connection registry — real work, deliberately out of this
ADR's scope and recorded as open rather than claimed done.

### 5. One scheduled job owns the whole lifecycle, and it is idempotent

`sweep_expired_subscriptions` is **replaced in place** by
`advance_subscription_lifecycle`, registered in the existing `ScheduledJob` registry under the
existing `RedisLockPort` — no second scheduler is introduced (requirement 39J). Per tick:

```
ACTIVE/TRIAL, period_end passed, invoice for the period unpaid  → PAST_DUE (grace clock starts)
ACTIVE/TRIAL, period_end passed, auto_renew, invoice paid       → renew + issue next invoice
PAST_DUE,     grace_period_ends_at passed                       → SUSPENDED
GRACE_PERIOD, grace_period_ends_at passed                       → SUSPENDED
ACTIVE/TRIAL, period_end passed, not auto_renew                 → EXPIRED
```

Idempotency comes from state, not from a run marker: every transition is guarded by its own
same-state no-op, and invoice issuance is guarded by "does an invoice already exist for this
period". Running the job twice in a row is a no-op the second time; that is asserted by test.

### 6. Denial is machine-readable, and says less to a parent than to an admin

A blocked request returns **`403`** with the standard error envelope and code
`ORGANIZATION_SUBSCRIPTION_INACTIVE`. `403`, not `402 Payment Required`: the caller is
authenticated and the resource exists; this is an authorization outcome, and `402` has no
established handling anywhere in this codebase's error contract.

Detail is graded by role, per requirement 39K — ordinary users get the generic message, Org
Admins additionally get status and amount due. Ordinary members never receive the organization's
billing internals.

### 7. The stale Parent SaaS-billing grants are revoked in this phase

`billing.invoices.list`, `billing.payments.create` and `billing.subscriptions.list` are revoked
from `parent` in the same migration. This is squarely in scope: it is a live exposure *on the
SaaS billing surface this ADR governs*, and requirement 39's own text calls for exactly this
re-check. `billing.plans.list` is deliberately **retained** — the plan catalogue is
platform-level, non-tenant, non-financial reference data already granted to five other roles.

Parent access to *school* (ERP) invoices is a separate, future concern under `school_erp.*`, and
per ADR-0038 must be per-student-ownership scoped, never a role-wide grant.

## Consequences

- **Every `/api/v1` route is now subject to tenant subscription state.** That is the point, and
  it is a behavioural change for every existing endpoint. The exemption list is the only escape
  hatch, and it is small enough to read in one screen.
- **One extra indexed query per authenticated request** for tenant-role callers (platform roles
  short-circuit before any I/O). Acceptable at this platform's scale; a short-TTL cache is the
  obvious optimisation, deliberately not built now because requirement 39M demands the *next*
  request after suspension be rejected, and a cache is exactly what would break that guarantee.
- **`suspend`/`cancel` stop being "documented but never triggered".** Their own docstrings said
  no caller wired them; the lifecycle job and the platform-admin routes now do.
- **`sweep_expired_subscriptions` changes behaviour.** It no longer expires an unpaid active
  subscription outright — it routes through `PAST_DUE` first. Any operator expecting the old
  immediate-expiry semantics gets a grace window instead. Deliberate, and the whole point.
- **Enum values cannot be removed by a downgrade.** PostgreSQL supports `ALTER TYPE ... ADD
  VALUE` but has no `DROP VALUE`. The migration's `downgrade()` therefore restores the columns
  and grants but leaves the two new enum labels in place, documented in the migration itself
  rather than silently.
- **Not built by this ADR, disclosed:** tearing down already-open WebSockets at the moment of
  suspension (§4); a subscription-state cache; the Org Admin and Platform Admin subscription UI
  (requirements 39R/39S) — backend first, frontend in the next slice; and the entire School ERP
  (ADR-0038), which the user sequenced after this.

## Amendment (2026-09-09) — the access rule narrows, and why it had to

Recorded here rather than edited into the sections above, matching this repository's convention
of treating an ADR as a historical record.

**Two states move from granting to denying.** `_GRANTING_STATES` was
`{TRIAL, ACTIVE, PAST_DUE, GRACE_PERIOD}` and a `None` subscription granted outright. It is now
`{TRIAL, ACTIVE, GRACE_PERIOD}`, and `None` denies with its own reason code
(`ORGANIZATION_SUBSCRIPTION_MISSING`, distinct from `..._INACTIVE`).

- **`PAST_DUE` now denies.** The platform owner's rule is that an unpaid invoice closes the
  dashboard, and `past_due` is precisely the state meaning *unpaid and past the due date*. It was
  the widest hole in the enforcement: an organization could stop paying and keep working
  indefinitely, because nothing escalated it without the scheduled sweep completing.
- **`GRACE_PERIOD` still grants**, deliberately, and this distinction is the point of the
  amendment. A grace period that does not grant access is not a grace period — it is a slower
  suspension, and the lifecycle would have no state left meaning "we know you are late, keep
  working while you sort it out". Access ends when grace *ends*.
- **`None` now denies.** §1's original reasoning — that a never-subscribed organization is
  un-onboarded rather than delinquent, and that denying would turn a provisioning bug into a
  total outage — was sound, and the outcome was still wrong. A provisioning bug is exactly what
  happened: `open_organization_subscription` raised on every call for the entire life of the
  feature (a flush-ordering defect, see ADR-0040's own implementation notes), so **no
  subscription had ever been persisted on a live database**. This fail-open is what made a
  platform-wide billing outage invisible: every organization had unrestricted access with no
  subscription and no surface reported it. Fail-open converted a loud, single-organization
  failure into a silent, total one.

**Two things had to land before denying on `None` was safe, and both did.** Onboarding no longer
reports success when provisioning fails — it validates the plan before writing anything,
compensates by deactivating the organization and disabling the admin account, and re-raises — so
this state can no longer be *created* silently. And `/billing` remains exempt from the guard, so
an affected organization can still reach the page that fixes it.

**Existing organizations were backfilled, not locked out.**
`python -m raad.interfaces.cli.backfill_subscriptions --plan-id <ULID> --apply` opens a
subscription for every organization that has none, through `open_organization_subscription`
itself, so period dates come from the plan's own billing cycle and the domain events and audit
rows are identical to an onboarding-created subscription. It is dry-run by default and
idempotent. Organizations with no user account at all — the residue of the failed onboarding
retries — are reported and deliberately skipped rather than billed; see
`docs/runbooks/orphaned-onboarding-cleanup.sql`.

**Three platform-admin routes were dead and are now fixed.**
`POST /billing/subscriptions/{id}/suspend`, `/reactivate` and `/extend-grace` referenced command
classes that `billing/api/routers.py` never imported, so every call raised `NameError` and
answered 500 — the whole admin half of this ADR's lifecycle was unreachable. Neither the contract
suite (which inspects `app.openapi()` without issuing a request) nor the unit tests (which call
the application service directly) executed a router module. `tests/architecture/
test_no_undefined_names.py` now fails on this class of defect anywhere in the codebase.

**Frontend.** `SubscriptionGate` wraps `AppShell` on `/org/*` and redirects a blocked tenant to
`/org/subscription` **before** any protected page mounts; that route sits outside the gated
branch, or the redirect would loop. `SubscriptionRequiredPage` shows the plan, status, invoice
amount, due date and instructions, and distinguishes "never assigned a plan" from "subscription
lapsed" because the operator action differs. Presentation only — the server guard is unchanged as
the real enforcement.
