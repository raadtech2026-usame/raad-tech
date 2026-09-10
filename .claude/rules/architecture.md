# Rule: Architecture

Derived from `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md`.

1. **Modular monolith for business logic.** All business logic lives in one deployable
   (`backend/`), organized into strict internal modules aligned to bounded contexts. Do not create
   new independently-deployed business services without an ADR.
2. **Device connectivity is a separate plane.** The device gateway (`services/device-gateway/`,
   renamed from `services/jt808/` per ADR-0010 once it grew a second vendor protocol adapter —
   see `src/vendors/{jt808,lsz,...}/` and `src/adapter.DeviceProtocolAdapter`) and JT1078
   (`services/jt1078/`) are independent deployables. FastAPI never terminates a device socket.
3. **Event-driven backbone.** The device plane communicates with the business plane exclusively
   through asynchronous domain events over the broker — never direct DB writes, never synchronous
   RPC from device services into the business database.
4. **Multi-tenant by design.** Every tenant-owned entity carries `organization_id`; isolation is
   enforced at the repository layer, not just the UI.
5. **API-first.** Every capability is exposed through a versioned contract (`/api/v1`) before any UI
   consumes it.
6. **Twelve bounded contexts, fixed set:** iam, organization, fleet_device, transport_ops,
   tracking, video, notifications, billing, reporting, platform_audit, **school_erp** (the
   eleventh, added 2026-09-04 by ADR-0038), **platform_finance** (the twelfth, added 2026-09-05
   by ADR-0040 §1 — the ADR this rule requires). Adding a thirteenth requires its own ADR.
   **Three financial domains exist and must never be merged.** Each is a separate module with a
   separate permission namespace, because the separation is a security boundary rather than a
   modelling preference (ADR-0038 §2, ADR-0040 §1):

   | Flow | Issuer | Payer | Module |
   |---|---|---|---|
   | RAAD SaaS billing | RAAD | Organization | `billing` (C8) |
   | School ERP finance | Organization | Student/Parent | `school_erp` (C11) |
   | Platform operations | Vendor/Employee | RAAD | `platform_finance` (C12) |

   `school_erp` and `billing` each own an `Invoice`-shaped aggregate deliberately
   (`billing.Invoice` vs `school_erp.StudentInvoice`); do not consolidate them.
   `platform_finance` is platform-scoped — its tables carry **no `organization_id`**, like
   `plans`/`regions`/`device_inventory`, which is what structurally prevents any organization
   from reading RAAD's own costs.
7. **No premature microservices.** Extraction from the monolith follows the documented roadmap
   (Phase 2 §13.3) and is driven by measured load, not speculation.
8. **School ERP is in scope since 2026-09-04 (ADR-0038).** This rule previously read "out of
   scope, permanently, absent an explicit new charter: classroom/attendance, payroll,
   exams/gradebook, LMS." The 2026-09-04 user directive is that explicit new charter. In scope
   now: academic structure (classes/grades), full student registration and records,
   parents/guardians, staff where the school-management use case requires it, and school finance
   (fee plans, student invoices/payments, income, expenses, categories, financial reporting).
   **Still out of scope, absent a further requirement:** LMS/courseware, exams/gradebook marks,
   timetabling, and general non-school enterprise ERP — any request pulling toward those four
   must still be flagged, not built. Payroll exists only as an expense *category* in school
   finance; classroom attendance is not built and needs its own requirement.
   ERP access never bypasses transportation security (D5/CR-1 are unaffected by any ERP grant).
