# Testing (Cross-Service)

Tests that span more than one deployable. Per-service unit/integration/contract tests live inside
each deployable (e.g. `backend/tests/`, `services/jt808/tests/`) — this directory is for tests that
exercise the system as a whole.

## Structure

- `e2e/` — end-to-end flows across frontend/mobile + backend + device plane (e.g. driver starts a
  trip → parent receives live tracking + notification).
- `load/` — load/performance testing against the NFR targets in
  `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §13.1 (position throughput, live-video
  concurrency ceilings, concurrent users).
- `fixtures/` — shared test data and fixtures reused across e2e/load suites.

## Status

Structural scaffold only. No test suites are implemented yet.
