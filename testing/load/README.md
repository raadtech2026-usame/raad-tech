# Load Tests — Status: Documented Plan Only, Intentionally Deferred

`.claude/rules/testing.md` #5 requires load tests to validate the NFR targets in
`docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §13.1 as pass/fail gates, not
informational numbers, and the Backend Final Architecture Resolution task explicitly requires
load tests be "scaffold/document only" here rather than silently skipped. This file is that
scaffold: it names the scenarios, the NFR targets each one gates, and the two concrete blockers
preventing an executable suite from existing yet.

## Why no executable suite exists yet

1. **No deployable environment to load-test against.** Load testing exercises latency and
   throughput *under real infrastructure conditions* (network, connection pooling, DB I/O,
   horizontal scaling behavior) — meaningless against a single local dev process on a laptop
   sandbox with no provisioned PostgreSQL/Redis/broker cluster, no deployed `backend/` instance,
   and no JT808 device-plane traffic generator (`services/jt808/` is not built this phase).
   Running one here would produce numbers that don't reflect anything real, which is worse than
   not running one at all.
2. **§13.1's own targets are explicitly provisional.** The Enterprise Architecture document's own
   words: *"Numbers are proposals to make the NFRs testable; please confirm or adjust"* — these
   are marked **for owner sign-off**, not yet a confirmed contract. Writing strict pass/fail
   assertions against unconfirmed numbers would silently promote a proposal to a requirement,
   which is exactly the kind of undocumented invention `.claude/rules/workflow.md` #8 and
   `.claude/rules/documentation.md` #1 both prohibit. Confirming (or revising) §13.1 is itself a
   prerequisite, not something this file can resolve on its own.

Both are structural blockers, not effort/time gaps — the second point in particular means even a
fully deployed staging environment wouldn't make these gates *meaningful* until §13.1 is
confirmed.

## What the suite will assert once unblocked

One scenario per §13.1 row, each a **pass/fail gate against the confirmed target**, not merely
an informational measurement (testing.md #5):

| Scenario | Target (§13.1, pending confirmation) | What it exercises |
|---|---|---|
| Position ingestion throughput | Sized to (vehicles × cadence) with headroom, cadence 10–15s active / 30–60s idle | `tracking`'s position-write path (`TrackingApplicationService.record_vehicle_position` → `vehicle_positions` insert), simulating N vehicles at the documented cadence |
| Live-position end-to-end latency | ≤ 3–5s device → client | Full path: simulated device position report → (once the event broker's device-plane producer exists, `services/jt808/`) → `RedisLatestPositionPort` write → `GET /tracking/vehicles/{id}/latest` or `/ws/tracking` read |
| Concurrent live video streams | Hard ceiling per org + global (e.g. 50 global to start) | `video`'s `VideoAccessPolicy`/D5 gate plus the (not-yet-bound) `VideoProviderPort` adapter's own concurrency ceiling (`.claude/rules/jt1078.md` #4) |
| Concurrent API users | "Thousands," stateless horizontal scaling | Standard HTTP load against `/api/v1` — the one scenario least blocked by device-plane dependencies, and the most plausible first candidate once *any* deployed environment exists |
| Platform availability | 99.5% → 99.9% | Not a single-run load test — an ongoing production SLO measurement, out of this suite's scope entirely |

## Prerequisites before this can move from "documented" to "executable"

1. §13.1's targets confirmed or revised by the doc owner (blocks writing real assertions, not
   just running them).
2. A deployed target environment (even a throwaway staging one) with provisioned
   PostgreSQL/Redis/broker sized per §13.2's scaling levers.
3. **A load-testing tool is not yet an approved dependency anywhere in this repository**
   (`requirements*.txt`/`pyproject.toml` has none). Per `.claude/rules/workflow.md` #1/#2, picking
   one (e.g. k6, Locust) requires stating what/why/replaces/license and getting explicit
   go-ahead in its own turn before installing anything — deliberately not done speculatively
   here.
4. For the video/live-position scenarios specifically: a JT808 device-plane traffic simulator,
   since `services/jt808/` itself is a separate, not-yet-built deployable
   (`.claude/rules/architecture.md` #2) this backend repository cannot simulate on its own.

This file should be updated (not silently left stale) the moment any of the four prerequisites
above changes.
