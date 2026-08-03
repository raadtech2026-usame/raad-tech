# Runbook: Health checks and monitoring

## When you need this

1. **Routine operation** — nothing to do. `/health/ready` is what an orchestrator/load balancer
   should point at to decide whether to route traffic to this process; `prometheus` (Docker
   Compose) scrapes `/metrics` automatically on its own interval.
2. **An orchestrator keeps restarting/draining the backend** — check `/health/ready` yourself
   first; it now tells you *which* dependency is the actual problem, not just "not ready".
3. **You want to know if the platform is under load, or a dependency degraded** — `/metrics`.

## The three `/health*` endpoints (and how they differ)

| Endpoint | Checks | Use it for |
|---|---|---|
| `GET /health` | Nothing — the process can respond at all. | A trivial "is anything listening" smoke test. |
| `GET /health/live` | Nothing — deliberately. | Kubernetes-style liveness: an orchestrator restarts the process if this ever fails. Must never depend on external services, or a database blip would cause a pointless process restart instead of a graceful "not ready" state. |
| `GET /health/ready` | Real Postgres + Redis (cache) + Redis (broker) reachability (Priority 1 Item 5). | Kubernetes-style readiness: an orchestrator stops routing traffic here (without restarting the process) while a dependency is down. |

`/health/ready` example (a genuinely degraded response — real output from this sandbox, where
Redis is configured but unreachable):

```json
{"status": "not_ready", "checks": {"database": "ok", "redis": "down", "broker": "down"}}
```

HTTP 503 whenever `status` is `not_ready`, HTTP 200 when `ready` — an orchestrator should treat
the status *code*, not just the body, as the signal (the body is for a human debugging *why*).

**Readiness policy** (`core/health/service.py`, `interfaces/http/health.py`):

- **Database is mandatory.** Unconfigured or unreachable, both mean "not ready" — almost nothing
  in this platform works without one.
- **Redis (cache) and the event broker are only gating if configured at all.** A deployment that
  genuinely hasn't configured Redis yet isn't "broken", just running without that feature (the
  same "fail loudly per-feature, don't crash the whole app" policy this codebase already applies
  to `LatestPositionPort`/`BrokerPort` themselves) — but a *configured*, unreachable Redis *is*
  reported not-ready, since something is actually broken in that case.

Each check has its own 3-second timeout (`core/health/service.py`'s `_CHECK_TIMEOUT_SECONDS`) —
`/health/ready` itself is bounded to a few seconds worst case, never hangs indefinitely waiting
on a half-dead connection.

## `/metrics`

Prometheus text-exposition format, no authentication (matches every other endpoint on this
router — restrict reachability at the network/reverse-proxy layer for a real deployment, not an
application-level credential a scraper needs provisioning for). Three metric families, all
hand-rolled (`core/observability/metrics.py` — no `prometheus-client` dependency; see that
module's own docstring for why a small purpose-built exposition renderer was chosen over a
general-purpose library for a need this narrow):

- **`raad_http_requests_total{method,route,status}`** — a counter, incremented once per
  completed request by `RequestLoggingMiddleware` (the same middleware that already emits the
  structured request-completed log line — no separate metrics middleware). Labeled by the
  matched **route template** (e.g. `/api/v1/vehicles/{vehicle_id}`), never the raw path — using
  the raw path would give every distinct resource ID its own metric series, an unbounded-
  cardinality bug.
- **`raad_dependency_up{dependency}`** — a gauge, `1`/`0`, reusing the exact same
  `HealthCheckService` checks `/health/ready` runs. A dependency that was never configured at
  all is *omitted* from the output, not fabricated as `0` — an absent series and a down series
  mean different things to whoever's alerting on this.
- **`raad_process_start_time_seconds`** — a gauge, the Unix timestamp this process started. Diff
  against wall-clock time for uptime, or watch for an unexpected jump to detect a restart.

**Example scrape** (real output, this sandbox — confirms the mechanism end-to-end):

```
raad_http_requests_total{method="GET",route="/health",status="200"} 2
raad_dependency_up{dependency="database"} 1
raad_dependency_up{dependency="redis"} 0
raad_process_start_time_seconds 1785739298
```

## Prometheus (Docker Compose)

`docker/docker-compose.yml`'s `prometheus` service (stock `prom/prometheus` image, no custom
Dockerfile) scrapes `backend:8000/metrics` every 15 seconds
(`infrastructure/monitoring/prometheus/prometheus.yml`). Not published to a host port by
default — reachable only inside the Docker network until you deliberately expose it (add a
`ports:` mapping, or front it with `nginx` + basic auth) — the same "don't publish more than the
deployment actually needs" posture already applied to `postgres`/`redis`/`backend` themselves in
`docker-compose.prod.yml`.

**Query it directly, container-to-container**, while developing:

```bash
docker compose -f docker/docker-compose.yml exec prometheus wget -qO- http://backend:8000/metrics
```

**Open the Prometheus UI** (temporarily, for local debugging only — remove the port again before
deploying, don't leave this published in prod): add a `ports: ["9090:9090"]` mapping to the
`prometheus` service in `docker/docker-compose.yml` (or a local-only override file), then

```bash
docker compose -f docker/docker-compose.yml up -d prometheus
```

and open `http://localhost:9090` — Status → Targets should show `raad-backend` as `UP`.

## What's deliberately not built this phase

- **Grafana dashboards.** `infrastructure/monitoring/grafana/dashboards/` stays an empty
  placeholder — building meaningful dashboard JSON needs a live Prometheus target with real
  traffic patterns to design useful panels against, which this sandbox (no Docker) cannot
  provide. The `/metrics` output above is real and scrapeable the moment a Grafana instance is
  pointed at this Prometheus.
- **Sentry / error tracking.** Needs a real Sentry account and DSN — an external dependency this
  session cannot obtain, the same category of gap the payment provider integration has. Wiring
  the SDK against a placeholder/fake DSN would ship dead, unverifiable code, so it wasn't
  attempted. When a real DSN exists: bind it via a new `SentrySettings.dsn` (`core/config/
  settings.py`) and initialize the SDK once in `main.py`'s `lifespan`, mirroring every other
  conditionally-bound port's "absent unless configured" shape.
- **OpenTelemetry / distributed tracing.** Not pursued — this is a modular monolith with no
  service-to-service call graph to trace yet (the device-gateway/business-API boundary is
  event-only, per `.claude/rules/architecture.md` #3), so a tracing system would have nothing
  meaningful to show beyond what structured request logging already provides.
- **Log shipping/aggregation** — tracked separately (`PROJECT_STATUS.md`'s own Logging row,
  Priority 2), not part of this item's scope.

## Testing limitation, disclosed rather than hidden

`HealthCheckService`'s database checks are live-verified against this sandbox's real, reachable
PostgreSQL (`tests/integration/test_health_check_service.py` — including a genuine "unreachable
host" case, not mocked) and the whole `/health*`/`/metrics` surface was exercised end-to-end
against a real running `uvicorn` server with real HTTP requests. The `prometheus` Docker Compose
service itself has **not** been live-tested — no Docker daemon in this sandbox, the same
disclosed limitation every other Compose-only mechanism this Priority 1 program shipped
(TLS, Redis hardening) already carries. `infrastructure/monitoring/prometheus/prometheus.yml`'s
scrape config was reviewed for correctness (valid YAML, correct target/port) but never confirmed
against an actual running Prometheus process.
