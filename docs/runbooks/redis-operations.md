# Runbook: Redis operations

## When you need this

Three situations:

1. **Routine operation** — nothing to do. The `redis` Docker Compose service (`docker/
   docker-compose.yml`) starts hardened by default: password-protected, persistent, memory-bounded.
   This runbook is for the other two situations.
2. **Something Redis-dependent is degraded or down** — `/auth/login` stopped rate-limiting, live
   position updates stopped, notifications stopped firing, a scheduled job stopped running.
3. **You're about to deploy for real** — verifying auth/persistence/memory limits actually took
   effect before this instance is holding real production data.

## What Redis holds in this platform

One Redis *process*, two logical databases, deliberately kept separate (Priority 1 Item 4,
`PROJECT_STATUS.md`) so an operation scoped to one can never collide with the other:

| DB | Env var | Holds | If lost |
|---|---|---|---|
| 0 | `RAAD_REDIS__URL` | Latest vehicle position cache, geofence hysteresis state, login rate-limit counters (Priority 1 Item 3) | **Reconstructable.** The next real GPS event repopulates the position cache; geofence state re-derives from the next evaluation; rate-limit counters simply reset to zero (an attacker gets one more free window, not a security hole). |
| 1 | `RAAD_BROKER__URL` / `DEVICE_GATEWAY_BROKER_URL` | Redis Streams event broker (ADR-0008): `DevicePositionReported`, `DeviceOnline`/`Offline`, notification-triggering events, the outbox relay's publish target, `LockPort`/`DeadLetterQueue` state | **Not fully reconstructable.** See "The 'Redis is reconstructable hot state' nuance" below — this is the one place that framing (`docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §10) doesn't hold without qualification. |

Both databases live in the *same* Redis server process today (one container, one `maxmemory`
budget, one `--requirepass`) — a deliberate MVP-scale choice, not an oversight; see "Scope
decisions" below.

## The "Redis is reconstructable hot state" nuance

Phase 2 §10's backup/DR framing says "Redis is treated as reconstructable hot state" — true for
DB 0 above, but incomplete for DB 1. Trace the actual write path
(`backend/raad/core/events/outbox.py`'s `SqlOutboxPublisher.publish_pending`): a domain event is
durably written to Postgres's `outbox` table first (protected by Priority 1 Item 1's backup
mechanism), then published to the Redis Stream, and **only then** is the outbox row marked
`published_at` — in the same transaction as the publish call succeeding. This means:

- If Redis loses a Stream entry *before* a consumer (Notification Worker, `/ws/tracking`/`/ws/
  notifications` fan-out) has read and acknowledged it, that entry is gone for good — the outbox
  row is already marked published, so the relay will never re-publish it. A real, if narrow,
  data-loss window: whatever was in-flight (published, not yet consumed) at the moment of loss.
- This is exactly why persistence (AOF, below) matters for this instance in a way it wouldn't for
  a pure cache — and exactly why `--maxmemory-policy noeviction` (never silently drop keys under
  memory pressure) is the correct, if less convenient, choice here over a permissive eviction
  policy that would be perfectly fine for a cache-only Redis.

## Persistence

`docker-compose.yml`'s `redis` service command:

```
--appendonly yes --appendfsync everysec
```

AOF (Append-Only File), fsynced at most once per second — the standard, documented durability/
throughput tradeoff: `always` gives zero loss at a per-write latency cost this workload doesn't
need; `no` relies on the OS's own page-cache flush timing, an unbounded loss window. `everysec`
bounds data loss on a hard crash to at most the last second of writes. RDB snapshotting is *not*
explicitly configured — it stays on the image's own stock schedule (`save 3600 1 300 100 60
10000`), left as a secondary fallback alongside AOF rather than tuned, since no requirement here
justifies deviating from the documented default.

**Verify persistence survived a restart:**

```bash
docker compose -f docker/docker-compose.yml exec redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning SET verify-key hello
docker compose -f docker/docker-compose.yml restart redis
docker compose -f docker/docker-compose.yml exec redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning GET verify-key
# Expect: "hello". Clean up:
docker compose -f docker/docker-compose.yml exec redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning DEL verify-key
```

**Check AOF/RDB status directly:**

```bash
docker compose -f docker/docker-compose.yml exec redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning INFO persistence
```

Look for `aof_enabled:1`, `aof_last_write_status:ok`, and `rdb_last_bgsave_status:ok`. Any
`_status` field reading anything other than `ok` means the last write/save attempt failed —
investigate immediately, don't wait for data loss to surface it.

## Authentication

`REDIS_PASSWORD` (`docker/.env`) is required by the `redis` service's own `--requirepass` and
embedded automatically into `RAAD_REDIS__URL`, `RAAD_BROKER__URL`, and
`DEVICE_GATEWAY_BROKER_URL` (`docker-compose.yml`'s own `${REDIS_PASSWORD:-dev-only-change-me}`
substitutions) — one value, one place to set it, matching `RAAD_AUTH__JWT_SECRET_KEY`'s and
`POSTGRES_PASSWORD`'s existing conventions exactly. The shipped default,
`dev-only-change-me`, is exactly what it says — safe to leave for local dev, **must** be replaced
before any real deployment.

**Generate a real value** the same way as the JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Rotating the password** on a running deployment: update `REDIS_PASSWORD` in `docker/.env`, then
recreate every service that holds a Redis connection (not just `redis` itself — `backend`,
`worker`, `device-gateway` all need to reconnect with the new credential):

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d --force-recreate redis backend worker device-gateway
```

There is no deliberate "reject the default password in prod" startup check (unlike
`RAAD_AUTH__JWT_SECRET_KEY`, which `Settings.validate_on_startup()` does refuse to boot without in
`RAAD_ENVIRONMENT=prod`) — this mirrors `POSTGRES_PASSWORD`, which has no such check either.
Operational discipline (this runbook, `docker/README.md`'s deployment checklist) is the control,
not a code-level gate, for consistency with the existing Postgres precedent rather than inventing
asymmetric rigor between the two.

## Memory

`REDIS_MAXMEMORY` (default `256mb`, `docker/.env`) bounds the container's memory use.
`--maxmemory-policy noeviction` means: once the ceiling is hit, **writes fail with an OOM error**
— Redis does not silently drop keys to make room. This is deliberate, not a missing feature: a
permissive eviction policy (e.g. `allkeys-lru`) would be the right choice for a cache-only Redis,
but this instance also holds not-yet-consumed broker Streams entries (real, undelivered domain
events, DB 1 above) that must never be silently discarded. `maxmemory-policy` is a server-wide
setting — Redis has no way to apply a different policy per logical database — so the safe choice
for this shared-instance topology is "fail loudly" over "silently lose data," the same
safety-over-convenience posture `.claude/rules/backend.md` #6 already establishes elsewhere.

**If you see `OOM command not allowed`** in application logs: check current usage against the
ceiling —

```bash
docker compose -f docker/docker-compose.yml exec redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning INFO memory
```

Compare `used_memory_human` against `REDIS_MAXMEMORY`. Either raise `REDIS_MAXMEMORY` (if the
host has headroom) or investigate what's growing unbounded — an unconsumed Streams backlog
(a stuck/crashed Notification Worker not acknowledging entries) is the most likely real cause,
not a need for more memory per se:

```bash
docker compose -f docker/docker-compose.yml exec redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning XLEN raad:events
```

A number that keeps climbing with no consumer draining it means the worker process needs
attention first — raising `REDIS_MAXMEMORY` alone would only delay the same failure.

## Scope decisions (deliberate, not oversights)

- **Single Redis instance, no Sentinel/Cluster/HA.** Matches this deployment's actual topology (a
  single VPS, `.claude/rules/architecture.md` #7: "no premature microservices... driven by
  measured load, not speculation"). A future scale-out step, not attempted this phase — Phase 2
  §13.3's own roadmap already names Redis HA as a later-scale concern, not an MVP requirement.
- **No mounted `redis.conf` file.** `infrastructure/redis/` intentionally holds no configuration
  (see `infrastructure/README.md`) — every tunable here is a Compose `command:` flag, resolved via
  Compose's own `${VAR}` substitution. A mounted conf file would need its own envsubst-capable
  entrypoint (Redis's stock image has no equivalent to nginx's built-in templating,
  `infrastructure/nginx/`'s own mechanism) for no benefit this deployment's tunable count
  actually needs.
- **Broker vs. cache share one instance/one `maxmemory` budget**, isolated only by logical DB
  number (0 vs. 1). Splitting them onto genuinely separate Redis processes would allow a real
  per-purpose eviction policy (the cache side *could* safely use `allkeys-lru`) — a documented,
  reasonable future improvement if broker/cache memory pressure ever actually conflict in
  practice, not built speculatively now.
- **No client-side connection hardening in `services/device-gateway`'s own Python code this
  phase** — that deployable's Redis clients (`src/events/redis_event_publisher.py`,
  `src/session/redis_device_session_registry.py`, etc.) keep whatever timeout behavior they
  already had; only the Business API's own `core/di/bootstrap.py` gained explicit
  `socket_connect_timeout`/`socket_timeout`/`health_check_interval` (`RedisConnectionSettings`,
  `core/config/settings.py`) this phase. Device-gateway's connection tuning is that deployable's
  own, separate concern (`.claude/rules/architecture.md` #2) — flagged, not silently skipped.

## Testing limitation, disclosed rather than hidden

This mechanism was built and carefully reviewed — YAML structural validation of the merged
Compose config, and the Python-side `RedisConnectionSettings`/DI wiring smoke-tested via direct
container inspection (constructing a real `redis.asyncio.Redis` client and confirming its
connection-pool kwargs, which needs no live server since `Redis.from_url` is lazy) — but this
sandbox has no Docker daemon, no local `redis-server` binary, and no WSL2 distribution installed,
so the actual server behavior (`--requirepass` enforcement, AOF persistence across a real
restart, `--maxmemory`/`noeviction` under real memory pressure) has never been exercised against
a genuinely running Redis process. The same disclosed limitation Priority 1 Item 2 (TLS) already
carries for its own mechanism — see `PROJECT_STATUS.md` Known Issue #13's identical framing, and
its own new entry for this item.

**First real verification, once a VPS/Docker host exists:**

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d --build redis
docker compose -f docker/docker-compose.yml ps redis   # expect "healthy"
docker compose -f docker/docker-compose.yml exec redis redis-cli ping   # expect NOAUTH error (proves auth is enforced)
docker compose -f docker/docker-compose.yml exec redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping   # expect PONG
```

Then run the persistence-restart drill above, and confirm the whole stack (`backend`/`worker`/
`device-gateway`) still connects (`docker compose logs backend | grep -i redis` should show no
connection errors).
