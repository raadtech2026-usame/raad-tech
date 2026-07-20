# ADR-0007: `audit_entries` Write Architecture (Shared-Kernel Audit Writer)

## Status
Accepted. Implemented and verified (Backend Stabilization phase). Resolves High finding #5 of
the pre-production architecture review ("Platform & Audit `audit_entries` write mechanism
contradicts `.claude/rules/backend.md` #3's no-cross-module-writes rule") and the earlier,
separate documentation-only audit's identical finding, both of which this ADR was explicitly
commissioned to settle.

## Context
Two approved documents both speak to how `audit_entries` (Database Design §8.7) gets written:

- `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md` §13.1: *"application logs (operational) are
  distinct from the audit log (§C10, tamper-evident, business-meaningful actions — Phase-2
  §12.8). Audit is a domain concern written transactionally, not a logging side-effect."*
- `docs/business/RAAD_Phase3.2_Database_Design_v1.md` §10: *"`audit_entries` is the immutable,
  append-only record of every important action... auth events, RBAC/scope changes, device
  assignment/reassignment, trip start/end, every video session open/close (D5), subscription/
  payment transitions, and access-revoking events (CR-1). Written **transactionally** by the
  domain."*

Read literally, this means **every one of the ten bounded contexts** must write an
`audit_entries` row in the same transaction as its own business change — a trip start
(`transport_ops`), a video session open (`video`), a payment transition (`billing`), an
RBAC/scope change (`iam`/`organization`), and so on.

But `audit_entries` is owned by `platform_audit` (C10) per
`docs/architecture/adr/0001-business-entity-module-mapping.md`, and
`.claude/rules/backend.md` #3 is unambiguous: *"No cross-module DB reads. A module's
repositories query only that module's own tables."* The same rule, and
`.claude/rules/architecture.md` #1's "strict internal modules," extend by clear implication to
writes — nothing in this codebase permits one module's Unit of Work to insert a row into
another module's table. Nine modules each needing to write, transactionally, into a tenth
module's table is a direct, structural conflict between these two approved documents.

This is not a new category of problem in this codebase. Every domain event, from every module,
already needs an analogous cross-cutting, same-transaction write: the transactional outbox
(`outbox`, Database Design §8.8). Database Design §10 (DB-8) explicitly pairs the two: *"Immutable
`audit_entries` + `outbox` ledger — Traceability + reliable events."* The outbox is not owned by
any bounded context — `OutboxRecord`/`OutboxWriter` live in `core/events/outbox.py`, and every
module's own `SqlAlchemy<Module>UnitOfWork.commit()` calls the same shared `OutboxWriter` instance
before committing the session.

## Decision
Treat `audit_entries` exactly the way `outbox` is already treated: a **shared-kernel table**,
not owned by any single bounded-context module's write path.

- **`AuditEntryRecord`/`AuditWriter`** live in `core/audit/writer.py` — new shared-kernel package,
  structurally identical to `core/events/outbox.py`'s `OutboxRecord`/`OutboxWriter`.
- **`SqlAlchemyUnitOfWork.commit()`** (`core/db/unit_of_work.py`, the one base class every
  module's own `SqlAlchemy<Module>UnitOfWork` already extends) now writes to `AuditWriter` in the
  same call, immediately after `OutboxWriter`, before `session.commit()` — the same session, the
  same transaction, the same atomicity guarantee the outbox already has.
- **`AuditWriter` derives every field from the `DomainEvent` envelope already being recorded** —
  `action` = `event_type`, `entity_type`/`entity_id` = `aggregate_type`/`aggregate_id`,
  `organization_id` = `org_id`, `correlation_id` = `correlation_id`, `actor_user_id` =
  `payload["actor_id"]` (present on every event factory in this codebase already),
  `metadata_json` = the full `payload`. `ip` has no source at the domain-event level and is left
  `NULL` — a flagged, known gap (see Consequences).
- **`platform_audit` (C10) becomes purely the read side**: `GET /admin/audit`
  (API Contracts §4.8) queries `AuditEntryRecord` directly from its own `infra/repositories.py`
  (a shared-kernel model, not a foreign module's) — exactly mirroring how `SqlOutboxPublisher` is
  the outbox's own read/relay side and lives in `core/events/`, not any bounded-context module.
  `platform_audit` never writes an `AuditEntry`.

**Net result: zero changes to any of the nine already-shipped bounded-context modules' own
source files.** Every module's domain events already flow through `record_events()` +
`uow.commit()` — the exact mechanism this ADR extends — so audit coverage becomes retroactive and
automatic the moment this ADR lands, with no module needing to import `platform_audit`, `core.audit`,
or anything new at all.

## Options Considered

### Option A — Shared-kernel `AuditWriter`, threaded through `SqlAlchemyUnitOfWork.commit()`
Described above. **Chosen.**

- **Pro:** Zero changes to any bounded-context module. Reuses an already-proven pattern
  (outbox) for a documented, structurally identical requirement (DB-8 groups them explicitly).
  Literal compliance with LLD §13.1 ("written transactionally... not a logging side-effect") for
  every module, not just new ones.
- **Con:** `AuditWriter` becomes a required constructor argument on the one shared
  `SqlAlchemyUnitOfWork` base class, so its ten call sites in `core/di/bootstrap.py` each need one
  line added (`container.resolve(AuditWriter)`) and every live-DB integration test's own
  `SqlAlchemy<Module>UnitOfWork(...)` constructor call needed the same one-line addition. Purely
  mechanical, no behavioral risk, done as part of this ADR's implementation.

### Option B — Each module writes its own `AuditEntry` via a cross-module application-service call
`transport_ops` (etc.) calls `platform_audit.AuditApplicationService.record(...)` synchronously
from inside its own `commit()` path, the way ADR-0003 proposes for `iam`↔`transport_ops` parent
registration.

- **Con:** ADR-0003's Option A pattern fits a *user-initiated, latency-sensitive* cross-context
  workflow with its own independent Unit of Work — it explicitly accepts a non-atomic,
  two-transaction, compensable window (see ADR-0003's own Failure Handling section). `audit_entries`
  is the opposite case: every module's *own* transaction must include it atomically, with no
  compensation window tolerable for an append-only trust ledger. Nine modules each taking a
  synchronous dependency on `platform_audit`'s public facade, purely to satisfy a cross-cutting
  concern, is also a materially larger blast-radius change than Option A here (ten call sites in
  one already-shared file vs. nine modules' own `application/services.py` each gaining a new
  dependency and call). Rejected.

### Option C — Event-driven: `platform_audit` subscribes to the outbox/broker and projects `AuditEntry` rows asynchronously
- **Con:** No broker is chosen yet (Phase 2 §4.3, still an open item) — this option is blocked on
  work explicitly out of this phase's critical path, and would leave `audit_entries` empty until
  a broker exists. It also does not satisfy LLD §13.1's "written transactionally... not a logging
  side-effect" as literally as Option A does — an async projection is structurally a logging
  side-effect (eventually-consistent, best-effort) in exactly the sense that sentence rules out.
  Rejected for this reason, independent of the broker-availability blocker.

### Option D — `platform_audit` owns `audit_entries`; every other module writes into it via a direct repository/table reference (bypass module seams)
- **Con:** Directly violates `.claude/rules/backend.md` #3 and `.claude/rules/architecture.md` #1.
  Rejected outright — the conflict this ADR exists to resolve.

## Consequences
- **`ip` is not captured.** No domain event factory in this codebase records a request IP — doing
  so would mean threading IP capture from `interfaces/http/middleware.py` through every module's
  own application-service call signature and every event factory's payload, a change to nine
  modules' own files this ADR's "zero changes to shipped modules" property explicitly avoids.
  Left `NULL`, flagged as a known gap for a future phase that also revisits event-factory
  signatures for another reason (so the two changes can be justified together).
- **`action` stores the PascalCase `event_type` verbatim** (e.g. `VideoSessionStarted`), not
  Database Design §8.7's illustrative lowercase-dot-notation example (`video.session.start`) — no
  document specifies a transformation algorithm between the two, and reusing the already-logged,
  already-stable event name keeps `audit_entries.action` trivially joinable against
  `outbox.event_type` for the same event. See `core/audit/writer.py`'s own module docstring for
  the full reasoning.
- **Every recorded domain event becomes an audit row, unconditionally** — no per-event-type
  audit-worthiness filter exists. Domain events in this codebase are only ever raised on genuine
  aggregate state changes, so there is no noisy stream to filter; introducing a filter would be a
  new, undocumented business rule.
- **`SqlAlchemyUnitOfWork.__init__` gained a required third parameter** (`audit_writer:
  AuditWriter`). This is a breaking change to the constructor signature, contained entirely
  within `core/db/unit_of_work.py`'s callers (`core/di/bootstrap.py`'s ten factory bindings, and
  every live-DB integration test's own UoW-construction helper) — no bounded-context module's
  own source is affected, since none of them call this constructor directly (they only extend the
  class and receive `session_factory`/`outbox_writer`/`audit_writer` from `core/di/bootstrap.py`).

## Verification
- New migration `57ccbb4bfda1` creates `audit_entries` (Database Design §8.7 exactly); applied,
  round-tripped (`upgrade → downgrade → upgrade`), `alembic check` reports zero drift.
- `tests/unit/test_core_audit_writer.py` (12 tests): field-derivation mapping, `write_all`
  batching, naive-UTC timestamp handling.
- `tests/integration/test_audit_entries_transactional_write.py`: a real `reporting` module
  commit produces exactly one matching `audit_entries` row, correctly populated, proving the
  end-to-end mechanism works for an unmodified, already-shipped module.
- `tests/integration/test_platform_audit_repository.py`: `platform_audit`'s own repository reads
  a row it never wrote, proving the read/write split.
- Every existing live-DB integration test (68 tests across 9 files, all pre-existing, none
  module-source-modified) continued passing after the `AuditWriter` wiring — direct evidence that
  this change is additive, not disruptive, to already-shipped behavior. A live query after a full
  test run showed real `audit_entries` rows automatically produced for `Plan`, `Subscription`,
  `Route`, `Student`, `Driver`, `Parent`, `Notification`, `Payment`, `VideoSession`,
  `StudentAssignment`, `Trip`, and `Region` domain events — every one of them from a module whose
  own source code this ADR's implementation never touched.
- `tests/architecture/test_module_boundaries.py`'s rule-7 static-proxy check was extended with an
  explicit `raad.core.*`-origin exception (see that file's own updated module docstring) — the
  minimal, targeted change needed so `platform_audit`'s own repository can legitimately bind to
  the shared-kernel `AuditEntryRecord` without the check misreading it as cross-*module* (as
  opposed to core-to-module, already pervasive throughout this codebase) database access.

## References
- `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md` §13.1 (audit is a domain concern, written
  transactionally), §10 (outbox pattern)
- `docs/business/RAAD_Phase3.2_Database_Design_v1.md` §8.7 (`audit_entries`), §8.8 (`outbox`),
  §10 (DB-8: audit_entries + outbox paired), §4.8 (`GET /admin/audit`)
- `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §2.1 (C10: AuditEntry, SystemSetting,
  Integration)
- `.claude/rules/backend.md` #1, #2, #3, #5
- `.claude/rules/architecture.md` #1, #6
- `.claude/rules/security.md` #8
- `docs/architecture/adr/0001-business-entity-module-mapping.md` (`audit_entries` owned by
  `platform_audit`)
- `docs/architecture/adr/0003-parent-registration-orchestration.md` (the cross-context
  orchestration pattern this ADR deliberately does *not* reuse, and why — see Option B)
- `raad/core/audit/writer.py`, `raad/core/db/unit_of_work.py`, `raad/core/di/bootstrap.py`,
  `raad/modules/platform_audit/` (implementation)
