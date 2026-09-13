# ADR-0041: Parent-Centric Registration + Parent Invoice Read Model + Report Preview

## Status

**Accepted** (direct user directive, 2026-09-10: "RAAD-TECH — REVISE CURRENT IMPLEMENTATION BEFORE
COMMIT" — Parent+Student nested registration, Student Invoices → Parent Invoices, quick-payment
workflow, Finance page redesign, Reports preview + filters + vehicle reporting). Written before
implementation per `.claude/rules/workflow.md` #7/#8.

## Context

The previous phase (this same day, no separate commit yet) built Parent and Student as two
registration workflows joined only by an after-the-fact "link guardian" step, and billed each
child through `school_erp.StudentInvoice` with no family-level invoice concept beyond the
already-existing `ParentFinanceApplicationService` summary/payment endpoints. The new directive
asks for: (1) one form that creates a Parent and N children together, transactionally; (2) the
Finance page's primary concept to become "Parent Invoice" rather than "Student Invoice", without
losing per-child attribution; (3) a real payment quick-action, already built last phase and kept;
(4) a Reports page with in-app preview before export, report-specific filters, and vehicle-level
reporting; (5) no destructive migration of financial history.

### Audit performed before deciding anything

- `school_erp.StudentInvoice` (`domain/entities.py`) captures `route_id`/`vehicle_id`/`driver_id`
  **at issue time** (ADR-0040 §3) specifically so a bill is a historical record and per-vehicle
  revenue is one indexed `GROUP BY`. This is the exact per-child/per-bus attribution the new
  directive says must not be destroyed.
- No `parent_id` column exists anywhere in `erp_student_invoices`/`erp_student_payments` — the
  only route from an invoice to a parent is `StudentInvoice.student_id → student_parents →
  Parent`, a cross-module hop `.claude/rules/backend.md` #3 forbids inside `school_erp` itself.
  `ParentFinanceApplicationService` (built last phase) already resolves this correctly by
  composing `transport_ops`'s application services, never a cross-module DB read.
- `reporting.application.catalog.ReportDefinition` already carries `accepts: tuple[str, ...]` —
  a per-report filter whitelist mechanism already exists; the frontend `ReportsPage` already reads
  it. `ReportExportService.export` already does exactly one thing worth reusing: resolve the
  definition, permission-check it, call `definition.build(request)`, hand the result to a
  renderer. There is no JSON-returning counterpart.
- `StudentAssignment` (`domain/entities.py`) requires `route_id`, `pickup_stop_id`,
  `dropoff_stop_id` as non-nullable constructor arguments; `vehicle_id` is optional metadata on
  top of a route assignment, not a standalone "assign to a bus" primitive. There is no supported
  way to create a valid assignment from a vehicle id alone.
- `org.student_billing`, `org.vehicle_revenue` (Vehicle Financial Overview), `org.bus_report` (
  per-vehicle roster), `org.outstanding_balances`, `org.profit_and_loss`, and `org.parent_payments`
  (despite the internal name `student_payments`, already titled "Parent Payments") already exist
  as registered report definitions reading real data. The catalogue the directive asks for is
  largely already built; what is missing is grouping-by-parent, an in-app preview, and two new
  reports.

## Decision

### 1. `ParentInvoice` is a read-model grouping of `StudentInvoice`, not a new aggregate or table

**No migration, no new financial system.** A "Parent Invoice" is computed on read: every
non-cancelled `StudentInvoice` belonging to one parent's children, for one `period`, grouped into
one row. `StudentInvoice`/`StudentPayment` remain the sole source of truth — unchanged schema,
unchanged domain methods, unchanged per-vehicle/per-child attribution. This is the same
"composing, not owning" pattern `ParentFinanceApplicationService` already established last phase
for the all-time family summary; this ADR extends it to a *period-grouped, organization-wide,
listable* shape.

Rejected alternative: a new `ParentInvoice` aggregate/table that `StudentInvoice` rows reference.
Rejected because (a) it duplicates a financial system the directive explicitly forbids
("do NOT create a second competing invoice system"), (b) migrating `erp_student_invoices` rows to
point at a new parent-invoice id is exactly the kind of financial-history rewrite Part 12 says to
stop and report on rather than guess at, and there is no genuine ambiguity here to resolve that
way — the non-destructive read-model is strictly safer and equally correct, and (c) it would
require re-deriving `vehicle_id`/`route_id` attribution at the new aggregate's grain, which the
per-student aggregate already gets right.

**Consequence — no data migration.** Every existing `StudentInvoice`/`StudentPayment` row already
carries everything the grouped view needs (`student_id`, resolvable to a parent via
`student_parents`). Nothing is moved, nothing is renumbered, no historical row changes shape.

**Grouping key:** `(parent_id, period)`. A synthesized, display-only invoice number —
`{period}-{parent_id[-6:].upper()}` — is shown in the UI and reports; it is never persisted or
treated as a real sequence, because inventing a persisted numbering scheme is exactly the kind of
second invoice system this decision avoids.

**Status** for a grouped row reuses the identical paid/partially_paid/unpaid/no_invoices logic
`ParentFinancialSummaryDTO` already computes (sum `net_amount`/`amount_paid`/`balance_due` across
the group's non-cancelled invoices) — the same rule, applied per period-group instead of
all-time.

### 2. Nested Parent + Students registration is one `TransportOpsUnitOfWork` transaction

`ParentApplicationService` gains `register_parent_with_children`: provisions the IAM login (its
own, independently-committed transaction — ADR-0003's existing, accepted pattern, unavoidable
across the module boundary, unchanged) and then opens **one** `TransportOpsUnitOfWork`, inside
which it creates the `Parent`, then for each child calls `Student.enroll(...)` and
`StudentParent.link(...)` directly (the same domain factories `StudentApplicationService`/
`StudentParentApplicationService` already call, invoked here in one shared transaction instead of
three separate ones), then commits exactly once. If any child fails validation (or a duplicate
link, though duplicates cannot occur here — every link is against a `Parent` just created in the
same transaction), the whole transaction rolls back: no orphan Parent, no orphan Student, no
partial link set.

**One accepted, disclosed gap, extending ADR-0003's own existing one**: if `Parent`+children
creation fails *after* the IAM user was already created, that `User` (role=parent, no linked
`Parent`) is left orphaned — identical to the single-parent `register_parent` path today, not a
new gap this change introduces.

Editing stays independent exactly as before: `PATCH /parents/{id}` and `PATCH /students/{id}` are
unchanged. "Add another child to an existing Parent" reuses the existing, unchanged
`POST /students` + `POST /students/{id}/parents` pair (`CreateStudentForm.tsx` + inline guardian
link) — no new endpoint needed for that path.

**Vehicle/Bus per child, at creation time: deferred by design, not invented.** `StudentAssignment`
has no valid "vehicle only" construction (see audit above) — assigning a bus is inseparable from
assigning a route and two stops. Building a second, weaker "just pick a vehicle" assignment
primitive would invent transportation-domain behavior the approved architecture does not have,
which Part 18's own "do not modify Route/Fleet architecture" instruction rules out. The nested
form instead shows each child's assignment as "Not yet assigned" with an **[Assign]** action that
opens the existing, full `AssignStudentForm` (route + stops + vehicle) after the family is saved —
the identical chained-secondary-step pattern `StudentsPage.tsx`'s `onCreated` handler already uses
for a single student today, now offered per child.

**"Registration date" = the existing `created_at` audit column, shown read-only.** No new column:
`.claude/rules/database.md` #4 already makes `created_at` the canonical creation timestamp for
every business row, and a second, independently-editable "registration date" field would let the
two diverge from the audit trail for no real benefit. Displayed as "Registered on" in the child
list and detail view; not a form input.

**Child count is always `len(children)` from a real query** (`GET /parents/{id}/students`),
exactly as already built — no stored counter, confirmed unchanged by this ADR.

### 3. Report preview reuses the exact export code path — one source of truth

`ReportExportService` gains `build_table(definition_key, request) -> ReportTable`: the same
lookup + `roles` permission re-check `export` already performs, factored out so `export` calls it
too instead of duplicating the logic. A new route, `GET /reports/{key}/preview`, calls
`build_table` and returns the `ReportTable` as JSON; `export` is otherwise unchanged. The frontend
renders that JSON as a table before offering PDF/XLSX — the same `ReportTable` the renderers
consume, so a preview can never show different numbers than the export.

`ReportRequest` gains two optional fields, `parent_id` and `payment_method` — both already
filterable columns at the repository layer (`student_id`/`vehicle_id`/`period`/`status` already
were; `method` already is on `StudentPaymentRepository`), so no new query capability is invented,
only two new optional filters plumbed through to builders that already do this kind of filtering.

### 4. Two new report definitions; the rest of the catalogue is reused, not rebuilt

- **`org.parent_invoices`** — the grouped Parent Invoice list (per decision 1), replacing
  `org.student_billing`'s per-student rows as the Finance page's primary invoice report.
  `org.student_billing` itself is **kept**, unchanged, as the per-student detail report (Part 4:
  "do not delete existing functionality").
- **`org.parent_payment_status`** — one row per parent with a non-cancelled invoice in the window:
  total due, paid, outstanding, status. The "Parent Payment Status Report" Part 9 names.

`org.vehicle_revenue`/`org.bus_report` (vehicle reporting), `org.outstanding_balances`
(receivables), `org.profit_and_loss` (P&L, already `start`/`end` filterable — this *is* the
monthly/yearly report once the frontend offers period-preset filters), and `org.parent_payments`
(payment collection) are reused unchanged, matching Part 4's "reuse existing architecture
wherever possible."

### 5. Finance page: rename and re-home the primary tab, keep every other tab

`OrgFinancePage`'s `invoices` tab becomes **Parent invoices** (the grouped view, with an
expandable per-child breakdown — decision 1's "internally retain which children/services
generated the amount"). `payments`, `income`, `expenses`, `feePlans`, `categories` tabs are
unchanged in behaviour; only the invoices tab's data shape and the KPI row's labels change.

## Consequences

- Zero schema migrations this phase. Verified by `alembic check` after implementation (see the
  session's own final report for the run).
- Every number in a report preview and its exported PDF/XLSX is provably the same call
  (`build_table`), closing Part 8's "one source of truth" requirement structurally, not by
  convention.
- Per-vehicle and per-student financial attribution is unchanged and unweakened — nothing about
  ADR-0040 §3's transport-context-at-issue-time design is touched.
- The deferred vehicle assignment on nested child rows is a real, disclosed UX gap versus the
  directive's literal mockup (which shows "Vehicle: Bus 01" inline) — it trades a small amount of
  one-screen convenience for not inventing a second, weaker transportation-assignment path. If a
  future requirement genuinely wants one-shot route+stop+vehicle assignment during child creation,
  that is a `transport_ops` change, evaluated on its own.
