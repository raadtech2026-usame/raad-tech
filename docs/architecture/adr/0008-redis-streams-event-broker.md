# ADR-0008: Redis Streams as the MVP Event Broker

## Status
Accepted. Implemented and verified (Backend Stabilization phase). Resolves Medium finding #6
("Notification/Report Workers are empty files") and #7 ("Scheduler has zero registered jobs")
of the pre-production architecture review, together with the still-open half of Critical/High
finding tracked in `core/events/ports.py`'s own module docstring: *"a broker (Redis Streams/
RabbitMQ at MVP, Kafka as the scale path, Phase 2 §4.3) is still an open item, not decided in
this phase."*

## Context
Phase 2 §4.3 names the decision space explicitly, without picking a winner: *"MVP: a lightweight
broker with durable streams — Redis Streams or RabbitMQ — sufficient for the event volume and
simplest to operate. Scale path: migrate the high-throughput position/telemetry topics to Kafka
when ingestion outgrows the MVP broker... The event contracts are broker-agnostic so this is a
transport swap, not a redesign."* Every downstream consumer of this decision (`core.events.ports.
BrokerPort`/`BrokerConsumer`, `core.workers.scheduler.LockPort`, `core.workers.dlq.
DeadLetterQueue`) was already built interface-first specifically so this choice could be made
later without disturbing them — this ADR is that later decision.

ADR the "Redis integration" the user separately approved for `tracking.infra.adapters.
RedisLatestPositionPort` (this same phase) already puts a real Redis instance in the
dependency graph. RabbitMQ would be a second new external service with its own client library,
its own connection/health-check surface, and its own operational footprint — for a decision
Phase 2 §4.3 itself frames as interchangeable at MVP scale ("sufficient for the event volume").

## Decision
**Redis Streams**, via the same `redis-py`/`redis.asyncio` client already added for
`RedisLatestPositionPort` — no second broker client dependency.

- `core/events/redis_streams.py` (new, shared-kernel, mirrors `core/events/outbox.py`'s
  placement): `RedisStreamsBrokerPort` (producer, `XADD`) and `RedisStreamsBrokerConsumer`
  (consumer, `XREADGROUP` against a durable consumer group, `XACK` on success).
- One shared stream (`raad:events`) for every published `DomainEvent`, not a stream per
  `event_type` — no approved document specifies per-event-type topic partitioning at MVP scale,
  and `core.events.processor.EventProcessorRegistry` already exists specifically to fan a single
  inbound stream out to per-`event_type` handlers client-side. Splitting into per-type streams
  is a straightforward later change (a "transport swap," per Phase 2 §4.3's own framing) if
  measured load ever justifies it (`.claude/rules/architecture.md` #7).
- One consumer group per logical worker (`notification-worker`, ready for a future
  `report-worker` if report generation ever needs its own event-driven trigger) — Redis Streams'
  native competing-consumers semantics give at-least-once delivery (LLD §10.3's own requirement)
  for free; `core.workers.idempotency.IdempotencyStore` (already built, deduping by `event_id`)
  is the existing, already-approved mechanism that makes redelivery safe.
- `core.workers.scheduler.LockPort` gets a concrete `RedisLockPort` (`SET key value NX EX ttl`
  for `acquire`; `DEL` for `release`) — the exact primitive §11.3 names ("a run-lock in Redis").
- `core.workers.dlq.DeadLetterQueue` gets a concrete `RedisDeadLetterQueue` — a second Redis
  Stream (`raad:events:dlq`) holding the failed event plus `error`/`attempts`, per §11.3
  ("bounded attempts, then dead-letter queue + alert").
- **`core.events.outbox.SqlOutboxPublisher` needed no changes at all** — it already depends only
  on the abstract `BrokerPort`; binding `RedisStreamsBrokerPort` in `core/di/bootstrap.py` is
  the one line that makes the outbox relay (`interfaces/workers/outbox_relay.py`, already
  built, previously always a no-op) start actually publishing.

All four bindings (`BrokerPort`, `BrokerConsumer`, `LockPort`, `DeadLetterQueue`) are conditional
on `settings.broker.url` being configured — left unbound without one, the same "fail loudly,
don't fake it" policy every other pending-infra port in this codebase already follows.
`broker.url` is deliberately a **separate** setting from `redis.url` (both already existed as
distinct `BaseModel`s in `core/config/settings.py` before this ADR) even though an MVP
deployment will typically point both at the same Redis instance — keeping them independently
configurable preserves the option to run the broker on its own Redis instance later without a
settings-shape change.

## Options Considered

### Option A — Redis Streams (chosen)
See Decision above.

- **Pro:** No second broker dependency; reuses the exact client already approved this phase.
  Native consumer groups give at-least-once + competing-consumers for free. Simple operationally
  (no separate broker process to run in this sandbox or in a small-scale deployment).
- **Con:** Redis Streams' durability model (AOF/RDB persistence) is weaker than RabbitMQ's
  disk-backed queues by default — acceptable at MVP scale per Phase 2 §4.3's own "sufficient for
  the event volume" framing, and explicitly named as the scale-path trigger for migrating to
  Kafka, not a reason to prefer RabbitMQ over Streams specifically.

### Option B — RabbitMQ
- **Con:** A second new external service + client library (`pika`/`aio-pika`), rejected under
  `.claude/rules/workflow.md` #1/#2's "only approved dependencies, explain before installing"
  discipline when Option A already satisfies the same documented requirement with zero
  additional infrastructure, given Redis is already being added this same phase.

### Option C — Defer the broker decision further, leave every dependent port unbound
- **Con:** This is the codebase's status quo before this ADR — directly contradicts the user's
  own explicit authorization for this phase ("Broker implementation... Notification Worker,
  Report Worker, Scheduler, Scheduled jobs") and the instruction to resolve every confirmed issue
  rather than re-defer it without new justification. Rejected — nothing changed about the
  *reasons* to keep deferring; Redis is now in the dependency graph specifically because of it.

## Consequences
- **Kafka migration remains a pure transport swap**, per Phase 2 §4.3's own framing —
  `BrokerPort`/`BrokerConsumer` are the only interfaces any consumer code depends on; a future
  `KafkaBrokerPort`/`KafkaBrokerConsumer` pair would need zero changes to `SqlOutboxPublisher`,
  the Notification Worker, or any bounded-context module.
- **No per-event-type stream/topic exists** — a consumer that only cares about one `event_type`
  still reads the shared stream and discards what it doesn't handle (`EventProcessorRegistry`'s
  own `get(event_type)` returning `None` is already a normal, cheap no-op path). Acceptable at
  MVP volume; revisit only if measured load shows this discarding is a real bottleneck.
- **`raad:events`/`raad:events:dlq` are new, undocumented-by-Database-Design Redis key
  patterns** — consistent with `vehicle:{id}:last`'s own precedent (Redis key shapes live in
  architecture/technical-design documents, not the relational schema); no Database Design change
  is needed since Redis Streams state is explicitly "reconstructable hot state" (JT808 Technical
  Design §14's own framing, reused here for the same reasoning), never a system of record.

## Verification
- `tests/unit/test_redis_streams_broker.py`: publish/consume round trip against a fake Redis
  stream client, `RedisLockPort` acquire/release/contention, `RedisDeadLetterQueue` send.
- `tests/integration/test_redis_streams_broker.py`: skip-guarded on `RAAD_BROKER__URL`
  (no broker reachable in this sandbox, same posture as the Redis-backed `LatestPositionPort`
  integration test).
- `interfaces/workers/notification_worker.py`/`report_worker.py` (previously empty files) now
  have real, tested implementations consuming this broker — see their own module docstrings.

## References
- `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §4.3, §13 (Kafka scale path)
- `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md` §10 (outbox + broker), §11.2/§11.3
  (worker/scheduler/DLQ contract rows)
- `.claude/rules/workflow.md` #1, #2
- `.claude/rules/architecture.md` #7
- `raad/core/events/redis_streams.py`, `raad/core/workers/scheduler.py` (`RedisLockPort`),
  `raad/core/workers/dlq.py` (`RedisDeadLetterQueue`), `raad/core/di/bootstrap.py`
  (implementation)
