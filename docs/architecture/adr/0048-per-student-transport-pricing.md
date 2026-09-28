# ADR-0048: Per-Student Transport Pricing (amends ADR-0042 §1 and ADR-0047 §3)

## Status

**Accepted** (user directive 2026-09-28: "I DO NOT want equal splitting anymore. The fee must be
assigned individually to each student.").

ADR-0042 and ADR-0047 are not edited. A reader following ADR-0042 §1 ("one family fee, split
equally across the children") forward should land here. Every other ADR-0042/ADR-0047 decision
stands:

- the Parent Invoice as the family's real monthly document;
- one line per child, frozen at generation;
- the payment ledger allocated to lines;
- pro-rata default allocation to remaining balances, editable per payment;
- vehicle attribution from the line snapshot.

## Context

Under ADR-0042 a `ParentBillingProfile` carried one `monthly_fee` for the whole family, and
`ParentInvoice.generate` split it equally across the active children. A school that charges
Student A $10, Student B $20 and Student C $30 could not express that. The family total came out
right only when the prices happened to be equal, and each student's line was a division rather
than the price the school actually set for that child. That makes student-level balances,
statements and per-bus income arithmetic artefacts instead of facts.

Two further facts shaped the design:

- **A student can be linked to more than one guardian** (`student_parents` is M:N), and each
  guardian can have their own billing profile. With a per-student fee, billing the child under
  every guardian would charge that child's fee twice. The per-family unique index on
  `erp_parent_invoices` cannot see this, because the two invoices belong to different parents.
- **`ux_erp_parent_invoices__org_parent_period` was unconditional.** Cancelling a wrong invoice
  made its period impossible to bill again. Because `exists_for_parent_period` ignores cancelled
  invoices, the monthly run then tried to insert and failed on the index for the whole
  organization. Once fees are per student, "cancel and regenerate at the corrected fee" becomes
  the normal correction path, so this could not be left as it was.

## Decision

### 1. `StudentBillingProfile` — each student's own monthly fee

A new aggregate `StudentBillingProfile` (table `erp_student_billing_profiles`) in `school_erp`:

- one row per `(organization_id, student_id)`, holding `monthly_fee` and `currency`;
- the unique key is enforced by the database;
- a `CHECK (monthly_fee >= 0)` constraint.

The organization is always the student's own organization. It is never supplied by the client.

**Zero is a real answer.** A fee of 0.00 means "rides free" (a scholarship, a staff child) and
produces no line. That is different from a student with no fee at all. The monthly run reports a
student with no fee as `no_fee` and never guesses a price for them.

**Changing a fee affects future invoices only.** Every generated line is a snapshot. Fee history
lives in the audit trail: the `StudentBillingFeeSet` event carries both the previous and the new
figure.

It lives in `school_erp`, not in `transport_ops.Student`. Money configuration belongs to the
financial context, and `.claude/rules/backend.md` #3 forbids `school_erp` from reading student
rows directly. `FeePlan` (the legacy catalogue) was considered and rejected:

- it is a named plan, not a per-student amount;
- it is retired from the UI (ADR-0047 §8);
- reviving it as the pricing source would reconnect the legacy `StudentInvoice` path.

### 2. `ParentBillingProfile` becomes the billing account, without a fee

The profile keeps:

- `status`: whether the family is billed at all;
- `billing_start_period`, `due_day` and `currency`.

It no longer carries a fee. `update_fee` becomes `update_terms`, which can now also change the
start period. The column `erp_parent_billing_profiles.monthly_fee` is made nullable and is
neither read nor written. It is kept rather than dropped, so the family figure each profile held
under ADR-0042 remains visible as history.

`PUT /school-finance/parents/{id}/billing-profile` no longer accepts `monthly_fee`. The body uses
`extra="forbid"`, so a client still sending one receives a 422 rather than having it silently
dropped.

### 3. Generation: one plan, shared by the run and its preview

`ParentFinanceApplicationService._plan_generation` decides, without writing anything, who is
billed and at what amount. Both `POST /parent-invoices/generate` and the new
`GET /parent-invoices/generation-preview` call it, so an admin's confirmation screen cannot
disagree with the run.

- A family is billed when its billing profile is active and has started, and it has no live
  invoice for the period (idempotency).
- Each **active** child is billed at the child's own fee. `ParentInvoice.generate` takes a
  `currency` and a per-child `amount`. The total is the sum of the lines. A duplicate student, a
  zero fee or a negative fee is refused in the domain.
- Children are left out, with a reason:

  | Reason | Meaning | Needs an admin? |
  |---|---|---|
  | `no_fee` | No fee has been set for the child | Yes |
  | `free` | The fee is 0.00 | No |
  | `currency_mismatch` | The fee's currency differs from the account's currency | Yes |
  | `billed_by_another_parent` | Another guardian's invoice already bills the child this period | No |
  | `no_active_children` | The family has no active children | No |
  | `already_invoiced` | The family already has a live invoice for the period | No |

- **A child is billed once per period.** When two guardians both have billing profiles, the payer
  is the guardian whose link is primary, else the lowest parent id. A child already on another
  family's live invoice for the period is skipped (`billed_student_ids_for_period`).
- The scheduled run (still off by default, ADR-0047 §9) logs `parent_invoice_students_not_billed`
  at WARNING level with student ids and reasons. Nobody watches that run, so an unpriced child
  must not go unbilled silently.

### 4. `ux_erp_parent_invoices__org_parent_period` becomes partial

The index becomes `WHERE status <> 'cancelled'`. A cancelled invoice frees its period, and a
corrected invoice can then be generated.

### 5. Payment, allocation and reporting are unchanged in design

Line amounts now carry real per-student prices, and everything downstream reads lines and
allocations as before:

- the default split is still pro-rata to remaining balances. For fees of $10, $20 and $30, a $30
  payment splits 5/10/15. The admin may redirect it, for example 10/20/0;
- student and parent statements, the vehicle report and the P&L all read these lines and
  allocations;
- vehicle attribution is still the line's own `vehicle_id` snapshot.

### 6. Known Issue #16 closed at the HTTP edge

`core/errors/handlers.py` gains two handlers:

- `StaleDataError` (a lost `row_version` race) maps to **409 CONFLICT**;
- `IntegrityError` maps by SQLSTATE: unique violations (23505) to 409, foreign-key (23503) and
  check (23514) violations to 422, and anything else stays 500.

The Unit of Work has already rolled the transaction back when either handler runs, so the
response changes and nothing about the protection does. The canonical case was two payments
recorded on one Parent Invoice at the same moment: the loser used to receive a 500.

### 7. Existing data — no invented fee

Migration `f6c2d9e1b3a8`:

- creates `erp_student_billing_profiles`;
- relaxes `monthly_fee` to nullable;
- swaps the invoice index for the partial one;
- backfills fees.

**Every existing invoice and line is untouched.** A student gets a fee only if they have actually
been billed: the amount of their line on their most recent non-cancelled Parent Invoice (latest
period, then latest generated), in that invoice's currency. That is the figure the family has
been paying for that child, so next month's invoice for an unchanged family equals this month's.

A student who has never been on an invoice gets **no** fee. Dividing the family figure by a head
count would be exactly the equal split this ADR retires. Such a student is left off invoices,
shown as "No fee set" on the Parents page, and listed by name in the generation preview. **An
admin must set their fee.** The migration prints how many fees it created and how many active
children under active billing profiles remain unpriced.

`downgrade()` does the following:

- drops the new table;
- refills any NULL `monthly_fee` from the sum of the linked students' fees, or 0;
- restores NOT NULL;
- restores the unconditional constraint.

It refuses, rather than deleting a financial row, when a period holds both a cancelled and a live
invoice for the same family.

### 8. RBAC

No new permission is added. Setting a fee requires `school_erp.parent_billing_profiles.manage`,
which only `org_admin` holds. Reading fees and the preview requires `.parent_billing_profiles.list`
and `.parent_invoices.list`, which RAAD staff and finance staff hold. A per-student fee is the
same kind of billing configuration as the account it replaces part of, so no second grant set is
introduced.

## Consequences

- **API changes.**
  - New routes:
    - `PUT /school-finance/students/{id}/billing-fee`;
    - `GET /school-finance/parents/{id}/student-fees`;
    - `GET /school-finance/parent-invoices/generation-preview`.
  - `PUT …/billing-profile` no longer takes `monthly_fee`, and its response no longer returns it.
  - `GET /students/{id}/finance` gains `monthly_fee` and `monthly_fee_currency`.
- **Siblings still share one bus.** The family/vehicle rule in `transport_ops` forbids two
  children of one parent riding different vehicles. Per-line vehicle snapshots already support
  different buses per child, but today they only differ across families or across time (a family
  that moves bus).
- **Not done here.**
  - Proration for a child who joins mid-month: a child added after the family's invoice for the
    period was generated is billed from the next period, as before.
  - A route to remove a fee: setting 0.00 stops billing.
