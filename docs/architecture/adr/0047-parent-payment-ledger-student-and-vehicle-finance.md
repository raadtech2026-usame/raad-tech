# ADR-0047: Parent Payment Ledger, Student-Level Finance and Vehicle Income (amends ADR-0042 §4)

## Status

**Accepted** (user directive 2026-09-28, "Complete the existing Finance module"). The design forks
below were put to the user before any code was written and each recommended option was accepted:
payment ledger allocated to invoice lines; pro-rata default allocation, editable per payment;
replace the Unpaid/Partial/Paid control and migrate existing paid amounts; retire the legacy
per-student billing UI while keeping its history; defer expense attachments; build scheduled
parent-invoice generation behind a flag that is off by default.

ADR-0042 is not edited. A reader following ADR-0042 §4 ("no `ParentPayment` aggregate, no payment
history") forward should land here: that decision is reversed by the same authority that made it,
the same way ADR-0042 reversed ADR-0041 §1. Every other ADR-0042 decision stands — the
`ParentBillingProfile`, the `ParentInvoice` as the real monthly document, the equal-split line
amounts, the frozen historical amount, the one-time `StudentInvoice` copy-forward.

## Context

ADR-0042 made payment a status on the family invoice: an admin picked Unpaid, Partial or Paid and,
for Partial, typed a figure. That model cannot answer what the new directive requires:

- **Student-level financial history.** "Student A: invoice, payment, balance." A line on the
  family invoice records what Student A was charged, but nothing records what Student A paid —
  every per-child "paid" figure in the codebase is a pro-rata guess
  (`line.amount * invoice.amount_paid / invoice.amount`).
- **A payment against a specific student**, with method, reference and date, that the parent view
  still aggregates.
- **Traceable allocation.** If a parent pays $300 covering three children, which child's balance
  moved must be a recorded fact, not a formula.
- **Cash-basis reporting.** Profit & Loss counted parent collections by *invoice date*, because no
  payment date existed anywhere (disclosed in `sum_collected_between`). A payment received in
  October against September's invoice landed in September.
- **Per-bus income that is not student money**: daily fare collections and other bus income.
  `erp_income` had no `vehicle_id` and no way to tell a daily collection from a donation.

Two further facts shaped the decision:

- **Reviving `StudentInvoice` would double-count.** ADR-0042 §3 copied every eligible
  `StudentInvoice` into a `ParentInvoice`. Making `StudentInvoice` live again would put the same
  money in two documents, and every report would need de-duplication rules to stay correct.
- **Legacy per-student money is invisible to every report.** Summary, Vehicle overview, P&L and the
  Report Center all read `ParentInvoice` since ADR-0042. Mounting the orphaned legacy forms
  (`FeePlanForm`, `GenerateInvoicesForm`, `RecordPaymentForm`, and `IssueInvoiceForm` on the
  Students page) would let an admin record money that no total ever shows.

## Decision

### 1. `ParentPayment` — a real payment ledger, allocated to invoice lines

New aggregate `ParentPayment` (`erp_parent_payments`) owning `ParentPaymentAllocation` children
(`erp_parent_payment_allocations`):

- Payment: `organization_id`, `parent_id`, `parent_invoice_id`, `amount` (`Money`), `method`
  (the existing closed method enum), `reference`, `received_on`, `notes`, `is_voided`,
  `voided_reason`, `idempotency_key`.
- Allocation: `parent_invoice_line_id`, `student_id`, `vehicle_id` (copied from the line), `amount`.
- **One payment settles one invoice.** A parent paying two months records two payments. This keeps
  every payment traceable to exactly one document and keeps voiding simple.
- **The allocations always sum to the payment amount**, enforced by the aggregate.

**Paying a specific student** is a payment whose only allocation is that student's line. There is
no second payment type and no second table.

### 2. `ParentInvoiceLine` records what each student has paid

`erp_parent_invoice_lines` gains `amount_paid`. `ParentInvoice.apply_payment` and
`reverse_payment` move line and invoice figures together inside one aggregate:

- `invoice.amount_paid` is always the sum of its lines' `amount_paid`.
- Status is **derived**, never set: `unpaid` when nothing is paid, `partial` below the total,
  `paid` at the total. `cancelled` is unchanged.
- **Guards, all in the domain** (the P0.1 standard applied to school finance):
  - a cancelled invoice cannot be paid;
  - a fully paid invoice cannot be paid again;
  - the currency must match;
  - every allocation must be positive and name a line of this invoice, at most once;
  - no allocation may exceed that line's remaining balance, so overpayment is refused rather than
    absorbed.
- `set_payment_status` and `PATCH /school-finance/parent-invoices/{id}/payment-status` are
  **removed** (user decision). Two ways to change the paid amount would be able to disagree.

**Student balance** = line amount − line amount paid, summed over the student's lines on
non-cancelled invoices.

**Parent balance** = the sum over the parent's invoices. It is the same numbers read at a coarser
grain, so a figure cannot appear twice.

### 3. Default allocation is pro-rata to remaining balance, editable per payment

When the caller supplies no allocation, the total is split in proportion to each line's remaining
balance on that invoice:

- each share is rounded down to the cent;
- leftover cents go one at a time to lines, in line order, that still have room;
- the split sums exactly to the payment total and never exceeds any line's balance.

The payment form shows this split and the admin may change it before saving. The server
re-validates whatever arrives.

### 4. Existing paid amounts are migrated into the ledger

Production holds 6 parent invoices whose `amount_paid` was set through the old status control. The
migration converts each invoice with `amount_paid > 0` into one `ParentPayment`:

| Field | Value |
|---|---|
| method | `other` |
| reference | `Recorded before payment ledger` |
| received_on | the invoice's last `updated_at` date — the closest recorded fact about when payment was marked |
| created_by | NULL, meaning "system" |

The amount is allocated pro-rata by line amount using the same rounding rule, and
`line.amount_paid` is set to match. Invoice totals and statuses do not change. Invoices with no
lines are skipped and counted in the migration log.

### 5. Vehicle attribution is the line's snapshot, never the live assignment

`StudentAssignment` has no effective dates (no start or end), so "which bus was this student on in
March" cannot be reconstructed from it. **Historical attribution therefore uses the transport
context captured on the invoice line at generation time** (ADR-0040 §3 / ADR-0042 §1), and each
allocation copies its line's `vehicle_id`.

A student who changes buses in October leaves September's charges and payments on September's
bus. A line generated before the student had a bus has `vehicle_id = NULL` and reports under
"Unassigned". That is disclosed, not re-attributed, because re-attributing it from today's
assignment is exactly the silent historical move this rule forbids.

The Parent Invoices list's *discovery* filter by current vehicle (the 2026-09-12 fix) is
unaffected: it answers "which families ride this bus now", not "whose money belongs to this bus".

### 6. Vehicle income: `erp_income.income_type` and `erp_income.vehicle_id`

- `income_type` is a closed enum:
  - `daily_vehicle` — money a bus collected on a given day. `vehicle_id` is **required**.
  - `other` — any other income (advertising, rental, donation, grant). `vehicle_id` is optional:
    bus-related or organization-wide.
- Existing rows become `other`, which is what they always were.
- **Categories stay configurable** (the existing `FinancialCategory` tree, kind `income`) and apply
  under either type. No category name is hard-coded.
- **Student income is never an `Income` row.** It is derived from payment allocations, so it
  cannot be double-entered. That is the ADR-0040 automatic-accounting rule, unchanged.

Every financial figure is then answered by exactly one source:

| Figure | Source |
|---|---|
| Student income | `erp_parent_payment_allocations` of non-voided payments, by `received_on` |
| Daily vehicle income | `erp_income` where `income_type = daily_vehicle` |
| Other income | `erp_income` where `income_type = other` |
| Expenses | `erp_expenses` (per bus where `vehicle_id` is set) |
| Billed / receivable | `erp_parent_invoice_lines` of non-cancelled invoices |

Every total keeps its sibling `currencies_*` query with identical filters and refuses a mixed
currency (P0.5).

### 7. Reporting

Organization, vehicle, student and parent views all come from the table above:

- The Profit & Loss DTO splits income into `student_revenue`, `daily_vehicle_income` and
  `other_income`. Student revenue is now cash-basis by `received_on`, correcting the disclosed
  invoice-date approximation.
- The Vehicle Financial Overview takes a date range and reports per bus: student income, daily
  income, other income, total income, expenses and net, plus billed and outstanding from the lines.
- A per-vehicle report adds breakdowns by student, parent, daily entry, other-income entry and
  expense category.
- New catalogue reports are `org.vehicle_finance`, `org.student_statement` and
  `org.parent_statement`. `ReportRequest` gains `student_id`.
- Export stays the existing synchronous PDF/XLSX path.

### 8. Legacy per-student billing is retired from the UI, not deleted

`StudentInvoice`/`StudentPayment`/`FeePlan` rows and routes stay: API stability, and no historical
record is destroyed. In the UI:

- the four legacy forms are removed;
- a student's finance history lists legacy invoices read-only;
- a legacy payment can still be voided with a reason (P0.4), since correcting a historical mistake
  must remain possible.

### 9. Parent self-service and scheduled generation

- **`GET /me/invoices`** (iam, the ADR-0023 `/me` home) returns the calling parent's own invoices,
  lines and non-voided payments.
  - It is self-scoped from `Principal.user_id` with no client-supplied id, so it cannot be pointed
    at another family, and it needs no RBAC grant.
  - `parent` still holds no `school_erp.*` permission — the ADR-0038/0040 constraint this satisfies
    by construction.
- **Scheduled generation.** A worker job generates the current month's parent invoices for every
  organization, only when `RAAD_WORKERS__AUTO_GENERATE_PARENT_INVOICES=true`.
  - It reuses `generate_parent_invoices` and is idempotent through the existing unique index.
  - The manual button stays.

### 10. RBAC

New pair `school_erp.parent_payments.{list,manage}`, following the existing role split:

- `org_admin` gets both;
- `founder`, `regional_manager`, `support_staff` and `finance_staff` get `list`;
- `parent` gets nothing.

Student finance reads require `school_erp.parent_invoices.list`, because the data is invoice lines.
Vehicle and organization finance reads keep `school_erp.reports.read`.

## Consequences

- **Migrations.** One schema migration adds:
  - `erp_parent_payments` and `erp_parent_payment_allocations`;
  - `erp_parent_invoice_lines.amount_paid`;
  - `erp_income.income_type` and `erp_income.vehicle_id`;
  - the backfill from §4.

  One RBAC migration adds the §10 grants. Downgrade drops the new objects. Invoice totals were never
  moved, so the prior status-based model is fully restored.
- **API changes.**
  - `PATCH …/payment-status` is removed.
  - New payment, student-finance, vehicle-report and `/me/invoices` routes.
  - The Profit & Loss and vehicle overview responses gain fields and re-define `other_income` as
    non-daily income only.
- **Not done here.**
  - Expense attachments: need the `python-multipart` dependency plus a file store and a backup for
    it.
  - EVC Plus/Zaad adapters: no merchant documentation.
  - A live Stripe webhook exercise: no account.
  - Per-child pricing within a family: ADR-0042's equal split still decides line amounts.
