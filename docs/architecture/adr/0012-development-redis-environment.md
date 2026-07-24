# ADR-0012: Development Redis Environment

## Status
Accepted. **Live verification complete, 2026-07-24 (follow-up pass).** Docker Desktop, WSL2, and
`redis:7-alpine` (`raad-redis-dev`) are now genuinely reachable in this environment — re-confirmed
directly this session (`docker ps`, a real healthy container), superseding this ADR's original
"confirmed absent" Verification section below, which is kept for the historical record rather than
silently deleted. `services/device-gateway/scripts/verify_redis_e2e.py` was run and passed. Beyond
that script's own scope, this pass went further and proved the *consumer* half live too — a real
Postgres `vehicle_positions` row, not just a decoded in-memory event — and found and fixed a real
bug along the way (see Verification below for both). One genuine caveat survives this pass, not
resolved by it: the initial claim that reached this ADR's author ("Business API Processing: PASS",
"End-to-End Verification: PASS", among others) was asserted, not accompanied by evidence, and did
not hold up under independent check at the time it was made — the actual state at that moment was
that every real position event was silently failing forever on a domain-layer validation error
(see Verification). That gap is what this follow-up pass closed; it is recorded here so the
distinction between "asserted" and "independently verified" stays part of this ADR's own history,
matching this codebase's own "fail loudly, don't fake it, and don't let a status claim outrun the
evidence for it" discipline.

## Context
ADR-0008 (Redis Streams event broker) and ADR-0010 (device-gateway Redis integration) both wired
real, tested Redis-dependent code — `RedisStreamsBrokerPort`/`RedisStreamsBrokerConsumer`,
`RedisLatestPositionPort`, `RedisEventPublisher`, `DeviceRegistryProjection`/
`RedisDeviceRegistryConsumer` — but every test of it runs against a fake/in-memory Redis double,
by explicit necessity: no reachable Redis server existed anywhere in this sandbox at the time
either ADR landed. `docker/docker-compose.yml`'s `redis:` entry was a one-line placeholder
comment. Before Phase F7 (Live Monitoring & Maps) begins, the user asked for this to become a
real, runnable local dev environment: a filled-in Compose service, real env var wiring on both
deployables, and a genuine LSZ device → Redis → Business API end-to-end proof — not just more
fake-client unit tests.

## Decision

### 1. `docker/docker-compose.yml` — a real `redis` service
```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "${REDIS_PORT:-6379}:6379"
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - raad_redis_dev_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
```
One instance backs **both** logical uses this codebase already treats as independently
configurable-but-usually-coincident (ADR-0008's own precedent): the Business API's
`RAAD_REDIS__URL` (tracking's read-only latest-position cache) and `RAAD_BROKER__URL` (the
`raad:events` Streams broker), plus the Device Gateway's own `DEVICE_GATEWAY_BROKER_URL`. No
second `broker:` service is defined — there was never a plan for the event broker to be anything
other than this same Redis (ADR-0008 §"Options Considered" already rejected a separate broker
technology). AOF persistence (`--appendonly yes`) is a dev convenience so Stream contents survive
a container restart — not a durability guarantee, and not something prod configuration should
inherit unexamined. `business-api`/`worker`/`device-gateway`/`jt1078-server`/`postgres` stay
commented placeholders: none has a `Dockerfile` yet, so none can be containerized regardless of
Redis being ready — that is separate, larger work this ADR does not attempt.

### 2. Env var wiring, both deployables pointed at the same instance
- `backend/.env.example` — `RAAD_REDIS__URL`/`RAAD_BROKER__URL` uncommented with a real default
  (`redis://localhost:6379/0`) instead of the prior "not yet connected in this phase" comment,
  which was accurate when written and is now stale.
- `backend/.env` (gitignored, real local file) — same two variables actually set, so the next
  `uvicorn` start in this environment binds `RedisLatestPositionPort`, the Streams broker,
  `RedisLockPort`, and `RedisDeadLetterQueue` for real rather than leaving them unbound.
- `services/device-gateway/.env.example` (new — this deployable had no env template at all
  before) — documents `DEVICE_GATEWAY_BROKER_URL`, with an explicit note that
  `src/broker_config.py` reads it via bare `os.environ`, not a dotenv loader; there is no
  `.env`-file-parsing code in this deployable, so the variable must actually be exported into the
  process environment (or supplied via a future `docker-compose` `environment:`/`env_file:` block
  once a `Dockerfile` exists) — documenting a `.env.example` here is a convention/reference, not a
  claim that this deployable auto-loads it.

### 3. End-to-end verification script (new)
`services/device-gateway/scripts/verify_redis_e2e.py` — a real, runnable proof of LSZ frame →
`RedisEventPublisher` → `raad:events` Stream → the Business API's own real
`_fields_to_event`/`DevicePositionReportedProcessor`, wired against **whatever Redis URL is passed
to it** (defaults to `redis://localhost:6379/0`, matching the Compose service above). Unlike
ADR-0010 §6's one-off manual check (run once, not committed), this script is committed and
reusable specifically so this exact "is the live wiring actually correct" question can be
re-asked cheaply in any environment that has a reachable Redis — including this ADR's own,
currently-blocked one, the moment that blocker is lifted.

## Options Considered

### Fake/in-memory Redis as a substitute for "live" verification (rejected)
Every Redis-dependent component here already has thorough fake-client unit test coverage
(ADR-0008/ADR-0010's own Verification sections) — adding another one under a different name would
not answer the actual question this task asked: does a *real* `redis-server` process, reachable
over a real socket, actually carry a `DevicePositionReported` from one process to another. Calling
a fake-client test "live verification" would misrepresent what was checked — this codebase's own
"fail loudly, don't fake it" discipline (already applied to every unbound port in `core/di/
bootstrap.py`) applies equally to how a completed task is *reported*, not only to how code
degrades when a dependency is missing.

### Installing Docker Desktop / enabling WSL2 in this sandbox (not attempted without confirmation)
Both are real, working options for the *user's own machine* — but doing either from inside an
agent session means installing invasive system software (admin rights, likely a reboot) with no
prior approval, exactly the class of hard-to-reverse, machine-affecting action this codebase's own
operating instructions require stopping and asking about first. Not attempted; flagged as the
first option below instead.

### Downloading an unofficial third-party Windows Redis binary (rejected)
Community Windows ports of Redis exist and would not need Docker/WSL at all. Rejected for this
phase specifically: fetching and executing an arbitrary third-party binary is a real trust-boundary
decision (workflow.md #1/#2 requires new dependencies to be explained and approved *before*
installation, and a raw `.exe` from outside any package registry this project already trusts is a
materially different risk than a `pip`/`npm` package) — not something to decide unilaterally
mid-task. If the user prefers this path over Docker, it is a live option, just not one to reach for
without asking first.

## Consequences
- The Compose file, both `.env.example` templates, and the verification script are all genuinely
  usable right now, in any environment with Docker (or a directly reachable Redis 5+ instance) —
  and, as of the 2026-07-24 follow-up pass, actually running in this one.
- **F7 readiness, updated 2026-07-24: both of F7's independent gates are now cleared.** Mapbox
  (ADR-0011) was already fully resolved. This ADR's own Redis dev environment is now live-proven,
  not just specified — real LSZ frame → Redis → Business API → persisted `vehicle_positions` row,
  end to end, with one real bug found and fixed along the way (see Verification). F7 (Live
  Monitoring & Maps) can proceed against this real pipeline rather than only synthetic/manual
  events — with the two residual, narrower gaps named in Verification (standing-worker backlog
  catch-up not directly observed; `vehicle:{id}:last` cache write still unbuilt) carried forward
  honestly rather than implied closed.
- `backend/.env`'s `RAAD_REDIS__URL`/`RAAD_BROKER__URL` point at a URL that is now genuinely
  reachable in this environment — DI binds the real Redis-backed adapters (`RedisLatestPositionPort`,
  the Streams broker, `RedisLockPort`, `RedisDeadLetterQueue`) rather than leaving them unbound.

## Verification

### Original pass (superseded, kept for history)
- **Confirmed absent, this sandbox, this session:** no `docker`/`docker-compose` binary on `PATH`;
  `docker info` fails; no Docker Desktop install directory; no Windows Docker service; `wsl.exe`
  exists but WSL itself reports "not installed"; `winget search` fails on a non-interactive
  Microsoft Store terms prompt; no `redis-server`/`memurai` binary, no `choco`/`scoop`. Every check
  above was actually run in that session, not inferred.
- **Not yet run:** `services/device-gateway/scripts/verify_redis_e2e.py` against a live Redis —
  blocked on the above.

### Follow-up pass, 2026-07-24 — live, independently re-verified
- **Docker/WSL2/Redis:** `docker ps` shows `raad-redis-dev` (`redis:7-alpine`) up and healthy on
  `6379`, matching this ADR's own Compose service exactly.
- **Producer side:** `verify_redis_e2e.py` run twice — first run reproduced a real, then-latent bug
  (below); second run, after the fix, printed `PASS`.
- **A real bug was found, not just a missing-infrastructure gap.** The first `raad:events` entry
  this pass inspected (`DevicePositionReported`, `heading_deg: 1521000`, `alarm_flags:
  3940653985813379`) was never consumed successfully — `redis_streams.py`'s own failure path
  swallows the exception message, so a dedicated diagnostic script (calling
  `DevicePositionReportedProcessor.process()` directly against the real container) was used to
  surface it: `raad.core.errors.exceptions.DomainError: HeadingDegrees must be in [0, 360):
  1521000`. Root cause: `services/device-gateway/src/vendors/lsz/handlers/position_handler.py`
  only substituted its documented `0` default when a field parsed to `None`, never when it parsed
  to a concrete but out-of-range value — and this vendor's own worked examples (per
  `protocol.location_status`'s own pre-existing docstring) are out of range in **both** of its
  documented cases, so this was not an edge case, it was the norm. Fixed with an explicit range
  clamp (`_clamp_heading`/`_clamp_alarm_flags`); `alarm_flags`'s clamp is explicitly flagged as
  "unmapped/unknown," not a verified no-alarms reading, since that field is safety-relevant and no
  real per-bit ACL mapping exists yet (Hardware Analysis §5) — user-confirmed as the interim
  default. Regression-tested (`tests/test_mdvr_position_handler.py`, using this exact vendor
  worked example); full device-gateway suite re-run clean, 323/323.
- **Consumer side, proven against a real Postgres, not a fake:** after the fix, a fresh
  `verify_redis_e2e.py` run's published event was picked up by a direct invocation of the real
  `DevicePositionReportedProcessor` (built via the real `core.di.bootstrap.build_container`, no
  fake `TrackingUnitOfWork`) and confirmed committed: `SELECT * FROM vehicle_positions WHERE
  vehicle_id = 'vehicle-e2e-verify'` returned exactly one row, `heading_deg=0, alarm_flags=0`,
  lat/lng matching the sent frame.
- **`backend/raad/modules/tracking/events/subscribers.py`'s own module docstring was stale** —
  claimed the producer-side Redis dependency was "proposed, not yet approved" and the whole path
  "not yet wired," both incorrect by the time of this pass (`services/device-gateway/pyproject.
toml` already marked `redis>=5.0` **APPROVED**). Corrected in place, along with a leftover
  pre-rename `services/jt808/src/vendors/lsz_mdvr/` path reference (should read
  `services/device-gateway/src/vendors/lsz/`).
- **Two things this pass explicitly did *not* prove, flagged rather than implied:** (1) the
  *standing* worker process (`python -m raad.interfaces.workers.bootstrap`) reaching a live
  position event on its own — it shares its consumer group with a large pre-existing `outbox`
  backlog (700+ historical domain events from prior, unrelated integration-test runs, draining for
  the first time now that a broker is reachable) that it must work through first; the persistence
  proof above used a direct processor invocation, not an observed catch-up. (2) `vehicle:{id}:
last`'s direct Redis cache write (B2's own scope, backing `GET /tracking/vehicles/{id}/latest`'s
  instant read) — grepped for in `services/device-gateway/src`, confirmed **absent**; still
  genuinely unbuilt.
- Existing fake-client test suites (ADR-0008/ADR-0010) continue to pass unmodified — this pass
  fixed one production code path (`position_handler.py`) and one stale docstring, nothing else.

## References
- `docs/architecture/adr/0008-redis-streams-event-broker.md`
- `docs/architecture/adr/0010-device-gateway-multi-vendor-architecture.md`
- `.claude/rules/workflow.md` #1, #2
- `docker/docker-compose.yml`, `backend/.env.example`, `services/device-gateway/.env.example`,
  `services/device-gateway/scripts/verify_redis_e2e.py`
