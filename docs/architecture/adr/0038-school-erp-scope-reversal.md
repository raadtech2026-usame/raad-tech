# ADR-0038: School ERP Scope Reversal and the `school_erp` Bounded Context

## Status

**Accepted** (direct user directive, 2026-09-04: *"IMPORTANT SCOPE CHANGE — SCHOOL ERP IS NOW IN
SCOPE. This instruction OVERRIDES any previous RAAD-TECH instruction that said 'No school ERP'...
REMOVE those restrictions from the current task and repository documentation."*). Confirmed via
`AskUserQuestion` for the module-placement decision this ADR turns on.

## Context

Every prior version of this repository's own governing documents made School ERP a **permanent**
out-of-scope boundary, in three places:

- `CLAUDE.md` → "Explicitly out of scope ... RAAD is **not** a school ERP. Do not add, extend
  toward, or casually suggest features from these domains, even if a request seems adjacent."
- `.claude/rules/architecture.md` #8 → "Out of scope, permanently, absent an explicit new
  charter: classroom/attendance, payroll, exams/gradebook, LMS."
- `.claude/rules/architecture.md` #6 → "Ten bounded contexts, fixed set ... Adding an eleventh
  requires an ADR."

Rule #8's own wording — *"absent an explicit new charter"* — is the hinge. The 2026-09-04
directive **is** that explicit new charter. This ADR records it, so a future reader who finds
ERP code in a repository whose history says "never build ERP" lands on the reversal rather than
concluding the boundary was violated silently. That is the same posture ADR-0025 established for
ADR-0009 and ADR-0036 established for ADR-0035: earlier records are not edited, a later ADR is
where the reader lands.

### Audit finding that shaped this decision

A deep repository audit ran before any implementation (the directive's own requirement 39A).
**The School ERP does not exist in any form** — not as scaffolding, not as dead code, not as
documentation-only. Verified, not assumed:

- Across all of `backend/raad/modules/`: `expense` → **0** files, `income` → **0**, `tuition` →
  **0**, `accounting` → **0**, `academic` → **0**. `grade` → 2 files, both false positives
  (`upgrade`, `graduated`). `class` → 117 files, every one the Python keyword.
- **34 tables** in the canonical database; not one is an ERP table. No `classes`, `expenses`,
  `income`, `fee_plans`, `student_invoices`, `financial_categories`, `payment_methods`.
- Ten `frontend/src/features/` folders, zero ERP. The Org Admin nav has 13 links, none of them a
  School or Finance section.

So this is greenfield construction, not completion of a half-built module. The one genuine
foundation that exists is **`transport_fees`** (`organization_id, student_id, period, amount,
currency, status(due|paid|overdue|waived)`) — a real school→student fee table with **no HTTP
route, no application-service surface and no frontend**, flagged as such in `CLAUDE.md` since it
was built. It is the natural seed for ERP student fees rather than a table to duplicate.

`students` itself carries only four business columns (`organization_id`, `full_name`,
`external_ref`, `status`). A complete ERP student record needs date of birth, gender, admission
number, address, class/grade, enrollment date and academic status — an expansion of the existing
aggregate, deliberately **not** a second student table.

## Decision

### 1. School ERP is in scope

RAAD is now a combined **School Bus Tracking & Transportation Management Platform** *and*
**School ERP / School Management Platform**. `CLAUDE.md`'s Product Scope and
`.claude/rules/architecture.md` #8 are amended in place to say so — the directive explicitly
asked for the repository documentation itself to change, not just this ADR.

**The ERP charter is bounded.** In scope: school profile, academic structure (classes/grades),
student registration and records, parents/guardians, staff where the school-management use case
requires it, and school finance (fees, invoices, payments, income, expenses, categories,
reporting). Out of scope still, absent a further charter: LMS/courseware, exams/gradebook
marks, timetabling, and general (non-school) enterprise ERP. The directive's own closing
constraint governs: *"do not expand beyond this defined ERP scope without a separate
requirement."*

### 2. ERP finance lives in a new `school_erp` bounded context — the eleventh

This is the decision rule #6 requires an ADR for, and it was put to the user directly
(`AskUserQuestion`, 2026-09-04) because two of the directive's own requirements pull against
each other:

- **39N (mandatory):** RAAD SaaS billing and School ERP finance *"are two different financial
  domains ... Do NOT mix them. The database, APIs, permissions, invoices, reports, and
  accounting logic must preserve this distinction."*
- **ERP brief:** *"Do not duplicate the existing billing module if it can be extended safely."*

Folding school finance into `billing` would satisfy the second and violate the first — both
money flows would share one module, one permission namespace and one invoice aggregate. That
risk is not hypothetical: this same audit found `parent` still holding `billing.invoices.list`,
`billing.payments.create` and `billing.subscriptions.list` — stale grants left behind when
ADR-0016 removed parent-pays billing — which today let a parent enumerate **RAAD's SaaS invoices
to their school**. A shared module makes that class of leak permanently easy to reintroduce; a
separate context makes it structurally hard.

**Chosen: a new `school_erp` bounded context.** The two flows are named explicitly and never
interchanged:

| | Issuer | Payer | Module | Aggregate |
|---|---|---|---|---|
| **RAAD SaaS billing** | RAAD | Organization | `billing` (C8, unchanged) | `Invoice`, `Payment`, `Subscription`, `Plan` |
| **School ERP finance** | Organization | Student/Parent | `school_erp` (C11, new) | `StudentInvoice`, `StudentPayment`, `FeePlan`, `Income`, `Expense`, `FinancialCategory` |

`billing` is **not** modified to carry school finance. `transport_fees` — today an orphan inside
`billing` — is the one genuine overlap, and is reconciled in the ERP implementation phase rather
than here (this ADR does not decide its fate; see Consequences).

The context count moves from ten to eleven. `.claude/rules/architecture.md` #6 is amended to
record eleven, with this ADR as the required justification.

### 3. Reuse, never re-invent, the cross-cutting machinery

Every ERP entity is tenant-owned and therefore carries `organization_id`, which makes ADR-0021's
central `SqlAlchemyRepositoryBase._apply_scope` apply automatically to `get_by_id`, `list_page`,
`list_cursor_page` and `list_scoped`. ERP reuses, without exception: the fixed
`api/application/domain/infra/events` module shape (`.claude/rules/backend.md` #1), the
`UnitOfWork` + transactional outbox + `AuditWriter` pipeline (ADR-0007 — financial audit trails
come free), `Money`/`NUMERIC` monetary representation (no floats, ever), `require_permission` +
the seeded `role_permissions` matrix, the standard error envelope, and the existing
pagination/filtering/sorting contract.

No parallel authorization system, no second money representation, no second audit mechanism.

### 4. ERP access never bypasses transportation security

The directive is explicit: *"Do not allow ERP access to bypass transportation security."* An
ERP permission grants no tracking, video, intercom or device reachability. D5 (video), CR-1
(tracking visibility) and ADR-0026's per-parent video grants are unchanged by this ADR and are
evaluated independently of any ERP grant.

## Consequences

- **Eleven bounded contexts.** `.claude/rules/architecture.md` #6's fixed set grows by one, with
  this ADR as its justification. A twelfth still needs its own.
- **Two invoice aggregates exist deliberately.** `billing.Invoice` (RAAD→Organization) and
  `school_erp.StudentInvoice` (Organization→Student). Reviewers must not "consolidate" them; the
  separation is the requirement, not an oversight.
- **`transport_fees` needs a reconciliation decision** in the ERP implementation phase: either
  migrate it into `school_erp` as a fee type, or leave it and have `school_erp` own school fees
  wholly. Deliberately left open here rather than decided without the data model in front of us.
- **`ReportRendererPort` is still unbound.** Printable/PDF student invoices need a rendering
  engine that does not exist in this repository. That is a real dependency for the ERP's
  printable-invoice requirement and is tracked as such, not assumed away.
- **RBAC grows a `school_erp.*` namespace.** Parent ERP finance access, when it is eventually
  exposed, must be per-student-ownership scoped — never a role-wide grant, per the directive's
  own *"Do not repeat the previous mistake where stale Parent permissions exposed
  organization-wide invoices."*
- **This ADR adds no code.** It records scope and placement. Implementation lands in its own
  phases, of which the first (per the user's own sequencing choice, 2026-09-04) is **not** ERP
  at all but the organization subscription lifecycle — see ADR-0039.
