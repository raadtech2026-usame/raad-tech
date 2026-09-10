# ADR-0040: ERP Finance Implementation — `school_erp`, `platform_finance`, and Real Report Rendering

## Status

**Accepted** (direct user directive, 2026-09-05: *"The previous implementation created only a
Finance UI foundation. That is not enough. The Finance and ERP system must now become a real
integrated part of the RAAD Platform."*). The four decisions this ADR turns on were each put to
the user via `AskUserQuestion` before any code was written, because each is governed by a project
rule that forbids resolving it unilaterally.

## Context

ADR-0038 opened the School ERP charter and placed school finance in a new `school_erp` bounded
context — then added **no code** ("This ADR adds no code. It records scope and placement.").
ADR-0039 then implemented the organization subscription lifecycle, which the user sequenced
first. This ADR is the implementation design for what remains.

### Audit performed before writing any code

Verified against the running repository and the live database, not assumed:

| Claim | Finding |
|---|---|
| `school_erp` module | **Absent.** `backend/raad/modules/` holds the ten pre-ADR-0038 contexts. |
| Platform operating expenses | **Absent.** No table, no aggregate, no route anywhere. |
| `plans` columns | `name, billing_scope, price_amount, currency, billing_cycle, vehicle_limit, status` — **no device or user limit**. |
| Plan write routes | **None.** `billing/api/routers.py` exposes read-only `Plan`. |
| Plan selection during onboarding | **Not wired.** `OnboardOrganizationCommand`'s own docstring flags it as a "real, flagged follow-up". |
| `transport_fees` | Full aggregate + commands + queries + repository in `billing`, **no HTTP route**, zero rows in the live database. |
| `ReportRendererPort` | Defined, **unbound**. No renderer dependency in `requirements.txt`. |
| Subscription lifecycle | **Implemented** (ADR-0039): 7 states, `advance_subscription_lifecycle`, central enforcement, platform-admin actions. Not rebuilt here. |

So the subscription *engine* is real and must be reused, not reimplemented. What is missing is
(a) the plan catalogue's own management surface and its link into onboarding, (b) both ERP
finance domains, and (c) a report renderer.

## Decision

### 1. `platform_finance` is the twelfth bounded context

RAAD's own operating costs — salaries, rent, electricity, water, internet, equipment,
maintenance, fuel, marketing, travel — are a **third money flow**, and it fits neither existing
financial module:

| Flow | Issuer | Payer | Module |
|---|---|---|---|
| RAAD SaaS billing | RAAD | Organization | `billing` (C8) |
| School ERP finance | Organization | Student/Parent | `school_erp` (C11) |
| **Platform operations** | **Vendor/Employee** | **RAAD** | **`platform_finance` (C12, new)** |

Folding RAAD's cost accounting into `billing` would put revenue and opex in one module under one
permission namespace — exactly the shape ADR-0038 §2 rejected when it refused to fold school
finance into `billing`, and for the same reason: a shared module makes a cross-domain permission
leak permanently easy to reintroduce. `.claude/rules/architecture.md` #6 fixes the context set
and requires an ADR for each addition; this section is that ADR for the twelfth.

`platform_finance` is **platform-scoped, not tenant-scoped** — like `plans`, `regions` and
`device_inventory`, its tables carry **no `organization_id`**. That is the structural guarantee
that no organization can ever read RAAD's internal costs: there is no tenant column for a scope
filter to match, and no `org_admin` grant in its namespace.

### 2. `school_erp` (C11) is implemented, and `transport_fees` migrates into it

Six aggregates, exactly the set ADR-0038 §2 names:

| Aggregate | Table | Purpose |
|---|---|---|
| `FinancialCategory` | `erp_financial_categories` | Category tree for income and expenses. `kind` = `income`/`expense`. |
| `FeePlan` | `erp_fee_plans` | A named recurring transport/school fee an organization bills students against. |
| `StudentInvoice` | `erp_student_invoices` | One period's charge to one student, carrying the transportation context (route, vehicle, driver). |
| `StudentPayment` | `erp_student_payments` | A payment received against a student invoice. **Partial payments are first-class.** |
| `Income` | `erp_income` | Non-student organization income. |
| `Expense` | `erp_expenses` | Organization expenditure, optionally attributed to a vehicle. |

**`transport_fees` migrates into `erp_student_invoices` and is dropped from `billing`.** ADR-0038
left this open deliberately; the user's decision is to migrate rather than leave a dormant
duplicate. The migration copies `organization_id, student_id, period, amount, currency, status`
into the new table (`due→issued`, `paid→paid`, `overdue→overdue`, `waived→cancelled`), then drops
`transport_fees`. `billing`'s `TransportFee` aggregate, its four commands, its queries, its
repository and its `BillingUnitOfWork` slot are deleted in the same change — one fee concept, not
two. The live table holds zero rows, so the data migration is exercised by test rather than by
production data, and `downgrade()` recreates the table but cannot restore rows it never had.

**Why `StudentInvoice` is not `billing.Invoice`.** ADR-0038 §2 requires two invoice aggregates
and forbids consolidating them. `StudentInvoice` additionally carries what a school bill needs
and a SaaS bill does not: `student_id`, `route_id`, `vehicle_id`, `driver_id`, `discount_amount`,
`amount_paid`, and a `partially_paid` state. `billing.Invoice` has none of these and must not
grow them.

**Partial payment is modelled on the invoice, not derived per-read.** `StudentInvoice.amount_paid`
is maintained by `apply_payment()`, so "who owes what" is a column comparison rather than a
correlated sum over payments. Outstanding balance is therefore indexable and cheap to aggregate
per vehicle — which requirement "Vehicle Financial Overview" needs on every page load.

### 3. Transportation context is denormalised onto `StudentInvoice`, deliberately

`route_id`, `vehicle_id` and `driver_id` are copied onto the invoice at issue time rather than
resolved live from `transport_ops.StudentAssignment`. Three reasons, in order of weight:

1. **A bill is a historical record.** If a student changes bus in March, February's invoice must
   still say which bus it was for. Resolving live would silently rewrite history.
2. `.claude/rules/backend.md` #3 forbids cross-module DB reads, so a live join is not available
   to `school_erp` anyway — only an application-service call at issue time, which is exactly what
   this does once, rather than on every read.
3. Per-vehicle revenue aggregation becomes a single indexed `GROUP BY` on this module's own
   table.

They are opaque, format-validated cross-module ids with no existence check — the same posture
`Trip.vehicle_id`/`StudentAssignment.vehicle_id` already established.

### 4. `plans` gains `device_limit` and `user_limit`; pricing shape is unchanged

Additive migration only. `vehicle_limit` already means "included buses". Monthly and annual
pricing stay **one plan row per (tier × cycle)** — the shape `Subscription.open()` and invoice
issuance already compute against — so a commercial tier like "Basic" is two rows, and the
catalogue UI groups them by name. Adding an `annual_price` column instead would have made
`plans.billing_cycle` ambiguous and forced a pricing decision into invoice issuance, changing
money math that ADR-0039 just stabilised.

Plan **write** routes are added (`POST /billing/plans`, `PATCH /billing/plans/{id}`,
`POST /billing/plans/{id}/activate`, `/disable`), Founder-only. `Plan.update_details()` is a new
domain method; `Plan.activate`/`disable` already existed and are reused unchanged.

### 5. Onboarding assigns the plan and opens the subscription

`OnboardOrganizationCommand` gains an optional `plan_id`. When supplied,
`OrganizationApplicationService.onboard_organization` calls a new
`BillingProvisioningPort.open_subscription_for_organization` — the same provisioning-port pattern
ADR-0003 established and ADR-0017 reused for `IamProvisioningPort`, with its concrete adapter
placed in `core/di/` (the composition root), never as a cross-module import from `organization`
into `billing`.

The port reuses `BillingApplicationService.open_subscription`, which already computes period
dates from the plan's billing cycle and issues the first invoice. **No date arithmetic is
reimplemented.** Plan selection stays optional so the existing onboarding contract does not break.

Same accepted, bounded failure mode ADR-0017 already documents: if billing provisioning fails
after the organization commits, the organization exists without a subscription rather than being
compensated. Made visible rather than hidden — the platform Subscriptions view lists
organizations with no subscription.

### 6. Reporting renders real artifacts; `ReportRendererPort` is bound

`openpyxl` (MIT) and `reportlab` (BSD) are added to `backend/requirements.txt` — the first
dependency approval this repository has granted for rendering, per `.claude/rules/workflow.md`
#1/#2. `ReportRendererPort` gains its first concrete implementation.

**Artifacts are streamed, not stored.** Phase-2 §10.1's object store does not exist, and inventing
one is out of scope. So reporting exposes a **synchronous** `GET /reports/{definition_key}/export`
that renders and returns the bytes directly (`Content-Disposition: attachment`). The existing
asynchronous `ReportRun` aggregate is untouched and still models queued/long-running runs for a
future worker; this route is the path that actually works today. `ReportRun.artifact_url` remains
unpopulated, which is honest rather than faked.

A `ReportDataProvider` abstraction supplies rows; `school_erp`, `platform_finance` and `billing`
each register the report definitions they own. That keeps `reporting` free of cross-module domain
knowledge — it renders whatever rows a provider hands it — and is what lets both report catalogues
grow without touching the renderer.

### 7. RBAC: one new namespace per context, and no `org_admin` reach into platform finance

`school_erp.*` grants go to `org_admin` (full) and the RAAD staff roles that already hold
organization-wide read (`founder`, `regional_manager`, `support_staff`) as read-only.
`platform_finance.*` grants go to `founder` and `finance_staff` **only** — never `org_admin`,
never `regional_manager`, never `support_staff`.

Per ADR-0038's own closing constraint, **`parent` receives no `school_erp` grant in this phase.**
Parent access to school invoices must be per-student-ownership scoped, which is a separate design;
a role-wide grant here would repeat exactly the mistake ADR-0039 §7 had to clean up.

### 8. ERP access never bypasses transportation security

Restated because this ADR adds code where ADR-0038 only added scope: no `school_erp` or
`platform_finance` permission grants tracking, video, intercom or device reachability. D5, CR-1
and ADR-0026's per-parent video grants are evaluated independently and are untouched.

## Consequences

- **Twelve bounded contexts.** `.claude/rules/architecture.md` #6 grows again, with this ADR as
  justification. A thirteenth still needs its own.
- **Three financial domains, three modules, three permission namespaces.** Reviewers must not
  consolidate them; the separation is the requirement.
- **`transport_fees` is gone.** Any reader following CLAUDE.md's references to
  `billing.TransportFee` lands here. `billing` no longer has any school→student concept.
- **Two new backend dependencies.** `openpyxl` and `reportlab`, both permissively licensed, both
  used only inside `reporting/infra`.
- **Report exports are synchronous and unstored.** A very large report will block its request.
  Acceptable at this platform's scale and honest about the missing object store; the async
  `ReportRun` path remains the documented future home for long runs.
- **`Plan` becomes mutable.** It previously had no write route at all. `update_details()` does not
  retro-change any already-issued invoice — invoices capture their own amount at issue time.
- **Not built, disclosed rather than assumed done:** expense attachments (the columns and the API
  shape exist — `attachment_url`, nullable — but no upload endpoint or blob store, which needs the
  same object store reporting lacks); parent-facing school invoice access; automated recurring
  student-invoice generation from a `FeePlan` on a schedule (the aggregate and the issue path
  exist and are driven on demand; a scheduled generator is the natural next slice).

## Implementation notes (2026-09-08)

Added after the design above was implemented and then audited against a running stack. This ADR's
**decisions are unchanged**; what follows records where the first implementation did not match
them, so a reader following §6 or §7 forward lands on the current shape rather than the intended
one. Kept here rather than edited into the sections above, matching this repository's convention
of treating an ADR as a historical record.

**§7 omitted the permission the report routes actually check.** The grant list names
`school_erp.reports.read` and `platform_finance.reports.read`, but both routes ADR-0040 §6 added
are gated on `reporting.reports.request` — a string no migration granted, so the entire Reports
feature returned `403` for every role, Founder included. Migration `c2f4a9d18e37` grants it to
`founder`, `regional_manager`, `support_staff`, `finance_staff` and `org_admin`. The two
`*.reports.read` grants are currently unused by any route; they are left in place rather than
revoked, as a namespace already granted and harmless, but they are not the gate.

**§6's role filter had to become an authorization check, not a listing filter.** One permission
covers all eleven definitions, so it cannot separate "may export their own school's billing" from
"may export RAAD's own operating costs". `ReportDefinition.roles` is now enforced in
`ReportExportService.export` as well as `ReportCatalog.list_for` — a caller can name a
`definition_key` that was never listed to them, and without the export-time check an Org Admin
could export `platform.invoices`/`platform.payments`/`platform.subscriptions` (whose builders set
`organization_ids=None` on purpose) and `platform.profit_and_loss`/`platform.expenses` (which read
a module with no `organization_id` for any scope filter to match, §1). That is precisely the
cross-domain leak §1's three-module split exists to make structurally impossible, so it is now
closed structurally.

**§6's 1000-row cap was an error rather than a cap.** `OffsetPageRequest` rejects any page size
above `MAX_PAGE_SIZE` (100) in its constructor, so builders asking for 1000 rows in one page
raised `ValidationError` — seven of the eleven reports returned `422` and rendered nothing.
`core/di/report_definitions._collect` now pages within the allowed size up to the same documented
cap, and reports the true pre-cap total so a truncated report says so instead of reading as
complete.

**Report tenant scope now comes from the real `ScopeResolver`.** The first implementation derived
it in `_scoped` from `principal.org_id`, which is `None` for a Regional Manager and a Support
Staff — both of whom are restricted to a *subset* of organizations, and both of whom would
therefore have resolved to unrestricted. `ReportRequest` now carries the scope the route already
resolved via `Depends(get_scope)` (ADR-0005), which is what the repositories consume (ADR-0021).

**§2's `Decimal`/`ROUND_HALF_UP` requirement was defeated upstream of the domain.** `Money`
quantises with explicit `ROUND_HALF_UP`, but the API request schema and both application-layer
`_decimal` helpers quantised first with `quantize`'s default (ROUND_HALF_EVEN), so 10.005 reached
`Money` already rounded to 10.00 and the stated rule never applied. All three layers now round
identically.

**Per-bus cost attribution excluded nothing.** `sum_by_vehicle_between` grouped by a nullable
`vehicle_id` including NULL, and the caller keyed the result by `vehicle_id or ""` — so every
expense recorded *without* a bus was charged to the Vehicle Financial Overview's "Unassigned" row,
conflating "this expense names no bus" with "this invoice names no bus". The query now excludes
NULL; unattributed cost counts in Profit & Loss, where §2 always intended it.

**A frontend consumer existed for none of the write endpoints.** ADR-0040 built the engine; every
`school_erp` write function in the frontend client was unreferenced, so an organization could read
finance it had no way to enter, and `POST /billing/plans` and `OnboardOrganizationCommand.plan_id`
(§4/§5) had no caller at all — meaning every organization was onboarded without a subscription and
met ADR-0039's inactive-subscription gate on first login. The full workflow (fee plan → monthly
billing run → record payment → void, plus categories, manual income and vehicle-attributable
expense), plan catalogue management and plan selection during onboarding are now wired.
