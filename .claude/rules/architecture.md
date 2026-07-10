# Rule: Architecture

Derived from `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md`.

1. **Modular monolith for business logic.** All business logic lives in one deployable
   (`backend/`), organized into strict internal modules aligned to bounded contexts. Do not create
   new independently-deployed business services without an ADR.
2. **Device connectivity is a separate plane.** JT808 (`services/jt808/`) and JT1078
   (`services/jt1078/`) are independent deployables. FastAPI never terminates a device socket.
3. **Event-driven backbone.** The device plane communicates with the business plane exclusively
   through asynchronous domain events over the broker — never direct DB writes, never synchronous
   RPC from device services into the business database.
4. **Multi-tenant by design.** Every tenant-owned entity carries `organization_id`; isolation is
   enforced at the repository layer, not just the UI.
5. **API-first.** Every capability is exposed through a versioned contract (`/api/v1`) before any UI
   consumes it.
6. **Ten bounded contexts, fixed set:** iam, organization, fleet_device, transport_ops, tracking,
   video, notifications, billing, reporting, platform_audit. Adding an eleventh requires an ADR.
7. **No premature microservices.** Extraction from the monolith follows the documented roadmap
   (Phase 2 §13.3) and is driven by measured load, not speculation.
8. **Out of scope, permanently, absent an explicit new charter:** classroom/attendance, payroll,
   exams/gradebook, LMS. Any request pulling toward these must be flagged, not built.
