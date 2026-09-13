# ADR-0042: Parent Billing Profile + Parent Invoice as Real Aggregates (supersedes ADR-0041 §1)

## Status

**Accepted** (direct user directive, 2026-09-11: "RAAD-TECH — MASTER RE-ARCHITECTURE — PARENT
MANAGEMENT + PARENT BILLING + BUSINESS FINANCE + REPORTS"). Written before implementation per
`.claude/rules/workflow.md` #7/#8.

## Context

ADR-0041 (2026-09-10, the previous day) deliberately made "Parent Invoice" a **read-model
grouping** of `StudentInvoice` rows — no new aggregate, no new table, computed on read by grouping
every non-cancelled `StudentInvoice` belonging to one parent's children for one period. That
decision was reasoned and internally consistent at the time.

The 2026-09-11 directive explicitly and repeatedly rejects exactly that shape:

> "Do NOT create a fake 'Parent Invoice' by merely grouping Student Invoices." (Part 2)
> "DO NOT implement Parent Invoice as a read-only grouping of StudentInvoice records. Parent
> Invoice must be a real financial document/entity in the new business model." (Part 7)
> Acceptance criterion F: "Parent Invoice is a real financial object, not merely a grouping of
> Student invoices."

This is a direct, explicit reversal of ADR-0041 §1, by the same authority that accepted it one day
earlier. It is treated here exactly as this codebase treats every such reversal (ADR-0025 over
ADR-0009, ADR-0038 over the prior ERP-out-of-scope stance): the new ADR is written, the old one is
**not edited** — a reader following ADR-0041 forward should land here for §1 specifically. Every
other decision in ADR-0041 (nested Parent+Student transactional registration, the deferred
per-child vehicle assignment, report preview reusing the export code path) is unaffected and
remains in force.

### Why the grouping approach is actually wrong for this business, not just unwanted

Re-reading the requirement with this objection in mind surfaces a genuine defect the read-model
could never fix, not just a labeling preference:

- **A parent with zero children cannot be billed anything**, and a parent whose children have not
  yet been invoiced individually has no "Parent Invoice" at all — the grouping only exists once
  someone has already run *student*-level billing. The directive's own workflow (Part 4/6: enter
  one monthly fee for the parent, at registration, before any child-level billing exists) has no
  representation in a read-model built from rows that don't exist yet.
- **The monthly amount is a property of the family, not a sum of independently-priced children.**
  ADR-0041's model requires a `FeePlan`/ad-hoc amount to be chosen *per student* before a family
  total can even be computed; the new directive is explicit that the organization types one number
  ("$80/month") for the parent, full stop. Deriving that from N student-level prices is backwards.
- **Editing the family's fee must not rewrite history, but there is nothing to attach an
  effective-dated fee to** in a model where the "invoice" is synthesized from whatever
  `StudentInvoice` rows happen to exist. A real `ParentInvoice` row freezes its own amount at
  generation time; a grouped view has no row to freeze anything on.

These are correctness gaps, not style preferences — confirming the reversal is the right call on
its own merits, not only because it was directed.

## Decision

### 1. Two new aggregates, owned by `school_erp` (C11), alongside the existing five

**`ParentBillingProfile`** (`erp_parent_billing_profiles`) — one per `(organization_id,
parent_id)`. Carries `monthly_fee` (`Money`), `billing_start_period` (`BillingPeriod`, first
period this profile bills), `due_day` (1–28, so every month has that day), `status`
(active/inactive). This is the "actual charge for the Parent" Part 5 asks for — **no `FeePlan`
reference**: Part 22 is explicit that Fee Plans stay optional and must never gate Parent
registration, so this aggregate has no foreign key to one.

**`ParentInvoice`** (`erp_parent_invoices`), owning **`ParentInvoiceLine`** children
(`erp_parent_invoice_lines`) — the real financial document. `organization_id`, `parent_id`,
`period`, `invoice_date`, `due_date`, `amount` (the frozen total — never re-read from the profile
after generation), `amount_paid`, `status` (`unpaid`/`partial`/`paid`/`cancelled`), one line per
billed child carrying `student_id`, `vehicle_id`/`route_id` (captured at generation time, the
identical "a bill is a historical record" reasoning ADR-0040 §3 already established for
`StudentInvoice`), and `amount` (that child's own share of the family total). Unique on
`(organization_id, parent_id, period)` — the idempotency guard Part 18 requires, enforced by both
an application-level pre-check and a real unique index (the same two-layer pattern
`ux_erp_student_invoices__student_period` already establishes, because a check alone loses a
race).

**Per-child amount allocation is an equal split of the family total across that period's actively
billed children, remainder cents assigned to the first line.** This is the one place this ADR
invents a rule Part 8 doesn't fully specify ("if the accounting model supports defensible line
attribution... do NOT invent vehicle revenue allocation"). Equal split is the simplest rule that
is (a) defensible — every child in a family nominally shares one transportation charge, (b) fully
disclosed here and in the domain docstring rather than silently chosen, and (c) reversible without
a migration if the organization later wants a different split, since it only affects line
generation, never the invoice total. Per-vehicle revenue reporting then sums line amounts grouped
by each line's own `vehicle_id` — a real, defensible relationship (this child rides this bus),
never an invented one.

**Why not add `parent_id` to `StudentInvoice` and keep one table instead of three new ones?**
Rejected: `StudentInvoice` is priced and discounted per student against an optional `FeePlan` —
retrofitting a family-level frozen amount onto it would require either duplicating the family
total onto every child row (a normalization break inviting exactly the kind of drift this
codebase's own Permanent Engineering Lessons repeatedly warn about) or making `StudentInvoice`
itself do double duty as both a per-child record and a per-family one. A clean, real
`ParentInvoice` aggregate with `ParentInvoiceLine` children is the direct implementation of
Part 7's own conceptual chain (`Parent → Billing Profile → Parent Invoice → Payment Status →
Receivable`) and keeps `StudentInvoice` exactly as accurate as it always was for the workflow that
still uses it (see Decision 2).

### 2. `StudentInvoice`/`StudentPayment`/`FeePlan` are kept, unmodified, and become historical/legacy

**No table is dropped, no row is altered or deleted** (Part 36/37, `.claude/rules/database.md`
#5). `issue_student_invoice`/`generate_student_invoices`/`record_student_payment` and their routes
remain callable — Part 4's "do not delete existing functionality" and this codebase's own
"disclosed, not silently done" posture both argue against removing working code with real
historical data behind it. **What changes is which workflow the product surfaces**: every
forward-looking read this phase touches (Finance Overview, Vehicle Financial Overview, P&L,
Reports Center) is repointed to `ParentInvoice`/`ParentInvoiceLine`, and the Report Center
frontend (Decision 5) stops listing the per-student report as a primary destination — closing
Part 35's "no contradictory terminology" requirement without deleting the underlying capability.

### 3. One-time, non-destructive data migration: `StudentInvoice` history is copied forward, never moved

For every organization, every `(parent, period)` group of non-cancelled `StudentInvoice` rows
reachable through an unambiguous `student_parents` link is copied into one new `ParentInvoice` +
its lines: `amount` = sum of the group's `net_amount`, `amount_paid` = sum of the group's own
`amount_paid`, `status` derived by the same paid/partial/unpaid rule the application layer already
uses (`_group_status`), `vehicle_id`/`route_id` per line taken directly from the source
`StudentInvoice` row it was copied from (no re-derivation). The source rows are **untouched** —
this is a copy, not a move, so `erp_student_invoices` remains a complete, accurate historical
record independent of the new tables.

**Ambiguous cases are skipped and counted, never guessed** (Part 37's own instruction): a student
invoice whose student has no linked parent, or whose several linked parents include none marked
`is_primary`, resolves to the earliest-linked parent (`student_parents` has no `created_at`, so
"first `parent_id` by string order" is the only deterministic tiebreak available without inventing
a column) — flagged here, and in the migration's own module docstring, as an interpretive choice
for a genuinely ambiguous case, exactly as this codebase already flags such choices elsewhere
(e.g. `StudentAssignment.ended_at`'s own "ambiguous wording, flagged here" precedent). A student
with no parent link at all is skipped entirely — its `StudentInvoice` rows remain in the legacy
table, visible to nobody's new Parent Invoice, rather than silently invented a parent for.

### 4. Payment status lives directly on `ParentInvoice` — no `ParentPayment` aggregate

Part 9/10/11 are explicit that the user-facing model is exactly three statuses
(`unpaid`/`partial`/`paid`) recorded directly on the invoice, with no payment-method/reference/
history UI. `ParentInvoice.set_payment_status(status, amount_paid, clock, actor_id)` is the one
domain method: `paid` forces `amount_paid = amount`; `unpaid` forces `amount_paid = Decimal("0")`;
`partial` requires `0 < amount_paid < amount` (a caller asking for `partial` with the full amount
or zero gets a clear `DomainError` telling them which status actually applies — never silently
reinterpreted). `balance_due` is a derived property, clamped at zero in Python and in every SQL
aggregate the same way `StudentInvoice.balance_due`/`sum_by_vehicle_between` already establish.

**No separate payment-transaction table.** The invoice row itself is the sole source of truth for
amount/paid/balance/status (Part 10's own list), and every transition already flows through the
shared `outbox`+`audit_entries` write architecture (ADR-0007) via `ParentInvoicePaymentStatus
Updated` — the audit trail Part 39 implicitly requires exists for free, without inventing a
bespoke payment-history table Part 9 explicitly says not to build.

### 5. Monthly generation, reporting, and RBAC

`generate_parent_invoices(organization_id, period, actor)` — for every `active` `ParentBillingProfile`
whose `billing_start_period <= period`, skip if `(parent_id, period)` already has a non-cancelled
`ParentInvoice` (idempotent, Part 18), else resolve the parent's currently-active linked children
(`transport_ops.StudentParentApplicationService`, unchanged cross-module composition pattern
`ParentFinanceApplicationService` already established) and each child's transport context in one
batched port call, split the fee per Decision 1, and issue.

Reports: `org.parent_invoices`/`org.parent_payment_status` now read `ParentInvoiceRepository`
directly (real rows, not a grouped `StudentInvoice` scan) — `ParentFinanceApplicationService`'s
`list_parent_invoices`/`get_parent_invoice_detail` grouping logic is deleted, not kept alongside
the real thing (Part 2's "do not create a second competing invoice system" cuts both ways: having
both the real aggregate and the old grouping code live side by side would itself become the
competing system). `org.outstanding_balances` is renamed to `org.receivables` (Part 12/34) as a
catalogue-key rename — no migration, since `ReportDefinition` is a code-resident catalogue, not a
table (CLAUDE.md's own "ERP Finance & Reporting" section). `org.vehicle_revenue`/`org.bus_report`/
`org.profit_and_loss`/`get_finance_summary` are repointed to `ParentInvoiceRepository`'s grouped
queries. `org.student_billing` stays registered (Decision 2) but is removed from the frontend
Report Center's listed catalogue.

RBAC: two new permission pairs, `school_erp.parent_billing_profiles.{list,manage}` and
`school_erp.parent_invoices.{list,manage}`, granted by the identical rule the existing
`_SCHOOL_ERP_MANAGE`/`_SCHOOL_ERP_READ` split already uses (`org_admin` manage, `founder`/
`regional_manager`/`support_staff`/`finance_staff` read-only, `parent` nothing) — a new additive
migration, never an edit to the already-applied one (`.claude/rules/security.md` #3,
`.claude/rules/workflow.md` #5).

## Correction made during implementation (same session)

Decision 5's original text said `ParentFinanceApplicationService.record_parent_payment`/
`list_parent_payments` (the pre-existing allocate-across-many-outstanding-invoices quick-pay
action and its payment-history list) would be "kept, rewritten." Implementing decision 4 first
made this contradiction concrete: Part 9 of the directive specifies payment status is set
**directly on one invoice** (Unpaid/Partial/Paid, with an amount only for Partial) — there is no
"pay N invoices at once, auto-allocated oldest-first" concept left to keep once `ParentInvoice`
*is* the per-family document, and Part 9 explicitly rules out exposing payment history at all.
Both methods (and `RecordParentPaymentCommand`, `POST /school-finance/parents/{id}/payments`,
`GET /school-finance/parents/{id}/payments`) are **removed**, not kept — replaced by decision 4's
single `SetParentInvoicePaymentStatusCommand` /
`PATCH /school-finance/parent-invoices/{id}/payment-status`, which operates on exactly one
invoice and needs no allocation logic because there is nothing left to allocate across.
`get_parent_financial_summary` (the all-time family view) is unaffected and is kept, rewritten to
read `ParentInvoice` as decision 5 originally said.

## Consequences

- Two schema migrations this phase (additive tables + non-destructive backfill; RBAC grants),
  verified by `alembic check` and an upgrade→downgrade→upgrade round trip.
- `ParentFinanceApplicationService`'s grouping methods (`list_parent_invoices`,
  `get_parent_invoice_detail`) are removed; `get_parent_financial_summary`/`list_parent_payments`/
  `record_parent_payment` (the all-time family view and the existing quick-payment action) are
  **kept**, rewritten to read/write `ParentInvoice` instead of scanning `StudentInvoice` — the
  family-level financial summary and payment quick-action Parts 16/33 still need are unaffected
  in shape, only in what they read.
- Per-vehicle and per-child attribution is preserved through `ParentInvoiceLine`, using the
  disclosed equal-split rule (Decision 1) rather than `StudentInvoice`'s own already-priced-per-
  student figures — a real, flagged change in *how* a line's amount is derived, not a loss of
  attribution.
- Historical `StudentInvoice`/`StudentPayment` data is unmodified and remains queryable; nothing
  a school has already recorded is destroyed or renumbered.
- `FeePlan` remains fully functional for the (now legacy-workflow-only) per-student billing path;
  Part 22 is satisfied structurally, since the new Parent Billing Profile path never references it.
