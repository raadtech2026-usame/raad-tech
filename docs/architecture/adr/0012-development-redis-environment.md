# ADR-0012: Development Redis Environment

## Status
Accepted. Configuration complete and reviewed. **Live verification is incomplete** — this
environment has no working Docker Engine, WSL, or native Windows Redis build (confirmed, not
assumed — see Verification below), so the actual "start the container, run traffic through it"
step named in this ADR's own triggering request could not be executed here. The provided
Docker Compose file, env var wiring, and end-to-end test script are all real deliverables usable
the moment Docker (or any reachable Redis 5+ instance) exists in an environment that has one —
this ADR documents exactly that boundary rather than reporting a live check that didn't happen.

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
  nothing here is blocked on this sandbox's own limitation; only the act of *running* them here is.
- **F7 readiness is therefore partial, honestly**: Mapbox (ADR-0011) is fully resolved with no
  outstanding blocker. The Redis dev environment is fully *specified* but not yet *proven live* in
  this sandbox — the "operational" bar the triggering request set. See the final infrastructure
  readiness report (delivered alongside this ADR) for the explicit go/no-go and the three ways to
  unblock it.
- `backend/.env`'s `RAAD_REDIS__URL`/`RAAD_BROKER__URL` are now set to a URL that is **not
  currently reachable in this sandbox** — starting the backend here today will make DI attempt a
  real connection and fail at first use (a connection error at call time), not silently fall back,
  since `settings.redis.url`/`settings.broker.url` being non-empty is exactly the signal
  `core/di/bootstrap.py` uses to bind the real adapter instead of leaving it unbound. This is the
  correct "fail loudly" behavior, not a bug — it will resolve itself the moment a real Redis is
  reachable at that URL, requiring no code or config change.

## Verification
- **Confirmed absent, this sandbox, this session:** no `docker`/`docker-compose` binary on `PATH`;
  `docker info` fails; no Docker Desktop install directory; no Windows Docker service; `wsl.exe`
  exists but WSL itself reports "not installed"; `winget search` fails on a non-interactive
  Microsoft Store terms prompt; no `redis-server`/`memurai` binary, no `choco`/`scoop`. Every check
  above was actually run in this session, not inferred.
- **Not yet run:** `services/device-gateway/scripts/verify_redis_e2e.py` against a live Redis —
  blocked on the above. Will be run and this ADR updated with a real pass/fail the first time a
  reachable Redis exists in an environment this agent has access to.
- Existing fake-client test suites (ADR-0008/ADR-0010) continue to pass unmodified — this ADR adds
  configuration and a script, not a change to any tested production code path.

## References
- `docs/architecture/adr/0008-redis-streams-event-broker.md`
- `docs/architecture/adr/0010-device-gateway-multi-vendor-architecture.md`
- `.claude/rules/workflow.md` #1, #2
- `docker/docker-compose.yml`, `backend/.env.example`, `services/device-gateway/.env.example`,
  `services/device-gateway/scripts/verify_redis_e2e.py`
