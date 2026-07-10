# Rule: Testing

1. **Backend test taxonomy** (fixed, per `backend/tests/`): `unit/`, `integration/`, `contract/`,
   `architecture/`. `architecture/` enforces module dependency-direction and import-boundary rules
   (e.g. domain never imports infra/FastAPI, no cross-module DB reads) as an automated gate, not a
   review-time convention.
2. **Cross-service tests live in `testing/`** (`e2e/`, `load/`, `fixtures/`) — reserved for flows
   that genuinely span more than one deployable.
3. **Safety-critical invariants require explicit regression tests**, not incidental coverage:
   safety-over-billing (D4/CR-1), parent video exclusion (D5), tenant isolation, one-active-device-
   per-vehicle, parent-own-children-only.
4. **Contract tests validate real behavior against the published `/api/v1` contract** — a passing
   contract test means the implementation matches the documented API, not just that it returns 200.
5. **Load tests validate the NFR targets** in `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md`
   §13.1 (position throughput, live-video concurrency ceilings, concurrent users, end-to-end
   position latency) — treat these as pass/fail gates, not informational numbers.
6. Don't test scenarios that can't happen; don't skip tests for scenarios that can.
