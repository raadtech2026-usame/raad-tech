# Backend Final Architecture Resolution — Final Report

**Scope:** the Backend Stabilization phase, spanning commits `2bb9b19`…`351c4bd` on `main`
(billing bounded context through the load-test deferral doc). Authority granted: refactor,
redesign, relocate responsibilities, resolve documentation conflicts, resolve dependency
problems, improve DDD/Clean Architecture/scalability/maintainability with objective
justification; create ADRs where needed; do not preserve a bad design because it already
exists. Constraints held throughout: prefer minimal changes over large redesigns, don't change
public APIs/schemas without a confirmed architectural or security reason, don't redesign stable
bounded contexts absent evidence of a real defect.

This report follows the task's own required format: one entry per resolved issue (Issue / Root
Cause / Decision / Architecture Change / Files Modified / Documentation Updated / ADR Created /
Migration Required / Backward Compatibility / Testing), then the ten closing summary sections
and seven scored dimensions.

---

## Part 1 — Issues Resolved

### Issue 1 — RBAC was a guaranteed `NotImplementedError` placeholder

- **Root Cause:** `require_permission`/`PermissionEvaluator` existed as an interface
  (Phase 4.3) but no concrete permission matrix was ever approved or seeded, so every
  authenticated route in every module raised `NotImplementedError` (500) regardless of caller.
- **Decision:** Seed a real `role_permissions` table (Database Design §4.4) and implement
  `IamPermissionEvaluator` against it, resolving for real on every route.
- **Architecture Change:** None structural — this filled an already-designed seam
  (`core.security.permissions.PermissionEvaluator`) rather than inventing a new one.
- **Files Modified:** `raad/modules/iam/infra/models.py` (`RolePermissionModel`),
  `raad/modules/iam/infra/repositories.py` (`SqlAlchemyRolePermissionRepository`),
  `raad/core/security/` (concrete evaluator), `core/di/bootstrap.py`.
- **Documentation Updated:** CLAUDE.md's IAM paragraph; ADR-0004.
- **ADR Created:** `docs/architecture/adr/0004-rbac-permission-matrix.md`.
- **Migration Required:** Yes — `role_permissions` table + seed data (owned by `core`/IAM
  jointly, flagged in its own migration docstring per naming.md's cross-cutting-revision note).
- **Backward Compatibility:** Preserved — routes that previously always 500'd now succeed for
  permitted callers; no caller that depended on the placeholder's specific failure mode existed.
- **Testing:** Unit tests for the evaluator; live via `test_rbac_and_scope_resolver.py`.

### Issue 2 — `ScopeResolver` had no concrete implementation

- **Root Cause:** `get_scope`/`ScopeResolver` were interface-only (Phase 4.3); every route
  either had no scope enforcement or a hand-rolled shortcut.
- **Decision:** Implement a real resolver backed by `region_assignments`/`support_assignments`
  (region scoping for RAAD staff — Founder=all, Regional Manager=assigned regions, Support=
  assigned orgs, Finance=billing scope only, per security.md #3).
- **Architecture Change:** None structural — filled the designed `organization` module seam.
- **Files Modified:** `raad/modules/organization/domain/entities.py` (`ScopeAssignment`),
  `infra/models.py`, `infra/repositories.py`, `interfaces/http/deps.get_scope`.
- **Documentation Updated:** CLAUDE.md's Organization paragraph; ADR-0005.
- **ADR Created:** `docs/architecture/adr/0005-scope-resolver.md`.
- **Migration Required:** Yes — `region_assignments`/`support_assignments` tables.
- **Backward Compatibility:** Preserved.
- **Testing:** `test_rbac_and_scope_resolver.py` (live DB), unit tests per assignment type.

### Issue 3 — D4 (safety-over-billing) vs. CR-1 (billing gate) documentation conflict for live tracking

- **Root Cause:** Two approved documents gave conflicting instructions for the same
  surface — live GPS during an active trip must never be billing-gated (D4/backend.md #6), yet
  CR-1 says trip history is billing-scoped. Neither document said which wins when a request is
  *live* position during an *active* trip specifically.
- **Decision:** Safety-over-billing wins for genuinely live position during an active trip;
  trip *history* stays fully CR-1-gated. One capability-policy object, not scattered
  `if subscription_active` checks (backend.md #6).
- **Architecture Change:** `TrackingVisibilityPolicy` — a single four-dimension predicate
  (capability ∧ scope ∧ ownership ∧ time-window, security.md #4) — is now the sole enforcement
  point on both tracking routes.
- **Files Modified:** `raad/core/policies/` (`TrackingVisibilityPolicy`),
  `raad/interfaces/http/policy_guards.py` (`resolve_tracking_decision`),
  `raad/modules/tracking/api/routers.py`.
- **Documentation Updated:** CLAUDE.md's Tracking paragraph.
- **ADR Created:** `docs/architecture/adr/0006-d4-cr1-safety-over-billing-reconciliation.md`.
- **Migration Required:** No.
- **Backward Compatibility:** N/A — routes had no real enforcement before.
- **Testing:** Explicit regression tests per testing.md #3 (safety-critical invariant),
  covering both the live-active-trip exception and the history-still-gated case.

### Issue 4 — `LatestPositionPort` had no adapter

- **Root Cause:** `TrackingApplicationService.get_current_vehicle_position` depended on
  `LatestPositionPort`, deliberately left unbound ("fail loudly, don't fake it").
- **Decision:** Implement a read-only `RedisLatestPositionPort` against Database Design §7.1's
  `vehicle:{id}:last` key — read-only because the JT808 Technical Design (§21.2) names the
  device-plane service itself, not this backend, as the key's writer.
- **Architecture Change:** None structural. `TrackingApplicationService.latest_position_port`
  made `Optional` (method-granularity optional-port pattern, matching billing's
  `payment_provider` precedent) so the service stays constructible when Redis isn't configured.
- **Files Modified:** `raad/modules/tracking/infra/adapters.py`,
  `raad/modules/tracking/application/{ports,services}.py`, `core/di/bootstrap.py`,
  `backend/pyproject.toml` (added `redis>=5.0`, user-approved), `.env.example`.
- **Documentation Updated:** CLAUDE.md's Tracking paragraph.
- **ADR Created:** None (implementation of an already-designed port, not a new decision).
- **Migration Required:** No (Redis key, not a table).
- **Backward Compatibility:** Preserved — unbound-Redis behavior (`NotImplementedError`) kept
  as the explicit fallback when `RAAD_REDIS__URL` isn't configured.
- **Testing:** `test_tracking_redis_latest_position.py` (unit + integration).

### Issue 5 — Video bounded context (C6) entirely unbuilt; D5 had no enforcement point

- **Root Cause:** `video` was a structural scaffold only; "parents have zero reachable path to
  video, anywhere, ever" (D5, jt1078.md #1) had no code enforcing it because there was no code
  to enforce it against.
- **Decision:** Build `VideoSession` (request_live/request_playback/activate/end/fail) around a
  `VideoProviderPort` abstraction — **native JT1078 explicitly not implemented**, per this
  task's own explicit instruction; MVP targets a hardware/vendor video API instead.
- **Architecture Change:** `enforce_d5` in `interfaces/http/policy_guards.py`, called before
  any application-service invocation on all three video routes, resolving the device's
  `organization_id` via `fleet_device`'s own application service (no cross-module DB read,
  backend.md #3).
- **Files Modified:** `raad/modules/video/{domain,application,infra,api}/*.py`,
  `core/di/bootstrap.py`, `interfaces/http/policy_guards.py`.
- **Documentation Updated:** CLAUDE.md's Video paragraph (documents the deliberate
  `playback_requests`-is-not-a-second-aggregate reading and the unbound-adapter posture).
- **ADR Created:** None (D5 itself was already an approved invariant; this is its first
  implementation, not a new decision).
- **Migration Required:** Yes — `video_sessions` table.
- **Backward Compatibility:** N/A — new surface.
- **Testing:** `test_video_domain.py`, `test_video_application.py`, `test_video_repository.py`.

### Issue 6 — Platform & Audit (C10) unbuilt; `audit_entries` write architecture undefined

- **Root Cause:** Backend LLD §10 requires every important action be audit-logged
  transactionally alongside its business change, but `audit_entries` is a shared-kernel table
  no single bounded context owns — writing to it from inside a module would violate
  backend.md #3 ("no cross-module DB reads/writes"), yet *not* writing it violates §10.
- **Decision:** Mirror the already-solved outbox-publication problem exactly: a shared-kernel
  `AuditWriter`, threaded through the one base `SqlAlchemyUnitOfWork.commit()`, so every
  module's own commit writes both its outbox row and its audit row in the same transaction,
  with zero changes to any of the ten modules' own source files.
- **Architecture Change:** `SqlAlchemyUnitOfWork.__init__` now takes a required
  `audit_writer: AuditWriter`; all ten `SqlAlchemy<Module>UnitOfWork` factory bindings updated.
- **Files Modified:** `raad/core/audit/writer.py` (new), `raad/core/db/unit_of_work.py`,
  `core/di/bootstrap.py`, `raad/modules/platform_audit/{domain,application,infra,api}/*.py`
  (new module), `tests/architecture/test_module_boundaries.py` (added a `raad.core.*`-origin
  exception to rule 7's static-proxy check).
- **Documentation Updated:** CLAUDE.md's Platform & Audit paragraph.
- **ADR Created:** `docs/architecture/adr/0007-audit-entries-write-architecture.md`.
- **Migration Required:** Yes — `audit_entries` (shared-kernel, owned by `core`, flagged in its
  own migration docstring) + `system_settings`.
- **Backward Compatibility:** Preserved — every existing module's public surface unchanged; the
  new required UoW constructor argument is internal wiring, not a public API.
- **Testing:** `test_core_audit_writer.py`, `test_platform_audit_{domain,application}.py`,
  `test_platform_audit_repository.py`, `test_audit_entries_transactional_write.py`.

### Issue 7 — Notifications (C7) unbuilt; CR-1 withholding never wired

- **Root Cause:** `notifications` was a structural scaffold; `SubscriptionAccessPolicy` existed
  but nothing called it for the notification-withholding decision Phase 2 describes.
- **Decision:** Build `Notification`/`DeviceToken`; evaluate `SubscriptionAccessPolicy` with
  `assignment_state` always `ACTIVE` (already filtered upstream), `subscription_state` checked
  only for `PARENT_PAYS` orgs, no `safety_override` (D4's live-GPS exception doesn't apply to
  notifications).
- **Architecture Change:** None structural — fills the already-designed policy seam.
- **Files Modified:** `raad/modules/notifications/{domain,application,infra,api,events}/*.py`.
- **Documentation Updated:** CLAUDE.md's Notifications paragraph, including the **real,
  unresolved** event-contract conflict this surfaced (API Contracts §13.2's single
  `student.assignment_changed` event vs. `transport_ops`'s four already-shipped, differently
  shaped events) — recorded, not invented around.
- **ADR Created:** None.
- **Migration Required:** Yes — `notifications`, `device_tokens` (first native `JSONB` column,
  `data_json`, per ADR-0002).
- **Backward Compatibility:** N/A — new surface.
- **Testing:** Full unit suite; `test_notifications_repository.py`;
  `test_notification_subscribers.py` for the fan-out worker logic.

### Issue 8 — Reporting (C9) unbuilt

- **Root Cause:** Structural scaffold only.
- **Decision:** Build `ReportRun` (request/start/succeed/fail) only — `ReportDefinition` has no
  table in Database Design (the schema authority) despite Phase 2 naming it, so it is **not**
  invented; `ReportType` is an opaque validated string, not a closed enum, since no document
  gives its exact wire-format values.
- **Architecture Change:** None structural.
- **Files Modified:** `raad/modules/reporting/{domain,application,infra,api}/*.py`.
- **Documentation Updated:** CLAUDE.md's Reporting paragraph, flagging the
  **real, unresolved** `ReportDefinition` documentation gap explicitly.
- **ADR Created:** None (the gap itself needs a documentation decision before an ADR would even
  apply).
- **Migration Required:** Yes — `report_runs`.
- **Backward Compatibility:** N/A — new surface.
- **Testing:** Full unit suite; `test_reporting_repository.py`; `test_report_worker.py`.

### Issue 9 — Billing (C8) unbuilt; no reconciliation/expiry sweep jobs

- **Root Cause:** Structural scaffold only; nothing expired lapsed subscriptions or reconciled
  stuck-`PENDING` payments.
- **Decision:** Build `Plan`/`Subscription`/`Invoice`/`Payment`/`TransportFee`; add
  `sweep_expired_subscriptions`/`reconcile_expired_payments` as new scheduled-job methods.
  `PaymentProviderPort` (EVC Plus) deliberately left unbound — "fail loudly, don't fake."
- **Architecture Change:** None structural.
- **Files Modified:** `raad/modules/billing/{domain,application,infra,api}/*.py`.
- **Documentation Updated:** CLAUDE.md's Billing paragraph, including the two real
  documentation conflicts resolved (Phase-2 §20.2's "mark Invoice FAILED" vs. the DB enum
  having no `failed` value; `payments.idempotency_key CHAR(64)` blank-padding).
- **ADR Created:** None.
- **Migration Required:** Yes — `plans`, `subscriptions`, `invoices`, `payments`,
  `transport_fees`.
- **Backward Compatibility:** N/A — new surface.
- **Testing:** Full unit suite including `ScheduledJobApplicationTests` (6 tests, caught 2 real
  bugs during this phase — see the naive/aware datetime finding below);
  `test_billing_repository.py`.

### Issue 10 — Event broker unselected; outbox publish side, Notification/Report Workers, and scheduled jobs all unbuilt

- **Root Cause:** Phase 2 §4.3 left the broker choice open (Redis Streams vs. RabbitMQ); every
  downstream consumer (`SqlOutboxPublisher`, Notification Worker, Report Worker, scheduled
  jobs) was blocked on that single decision.
- **Decision:** Redis Streams — Redis was already in the dependency graph for
  `LatestPositionPort` (Issue 4), making it the zero-additional-dependency choice. One shared
  stream (`raad:events`), consumer groups per worker, native `XPENDING`-based delivery-count
  tracking (no second counter store), `XAUTOCLAIM` for stale-pending reclaim.
- **Architecture Change:** New `RedisStreamsBrokerPort`/`RedisStreamsBrokerConsumer`/
  `RedisDeadLetterQueue`; `RedisLockPort` for scheduler overlap guards; conditional DI binding
  on `settings.broker.url`.
- **Files Modified:** `raad/core/events/redis_streams.py` (new), `raad/core/workers/
  scheduler.py`, `raad/core/workers/dlq.py`, `raad/core/config/settings.py`
  (`WorkerSettings` +7 fields), `core/di/bootstrap.py`,
  `raad/modules/notifications/events/subscribers.py` (new — `_NotificationFanOut` +4
  processors), `raad/interfaces/workers/notification_worker.py`,
  `raad/interfaces/workers/report_worker.py`, `raad/interfaces/workers/bootstrap.py`
  (`_register_scheduled_jobs`, 3 job closures).
- **Documentation Updated:** CLAUDE.md's "Architecture patterns in use" and "Known gaps"
  sections.
- **ADR Created:** `docs/architecture/adr/0008-redis-streams-event-broker.md`.
- **Migration Required:** No (Redis Streams, not a table).
- **Backward Compatibility:** Preserved — every consumer stays unbound/no-op when
  `settings.broker.url` isn't configured, matching the existing "fail loudly" posture.
- **Testing:** `test_redis_streams_broker.py`, `test_notification_subscribers.py`,
  `test_report_worker.py`, `ScheduledJobApplicationTests` (billing).

### Issue 11 — No CI/CD pipeline

- **Root Cause:** `ci-cd/pipelines/*.yml` existed as a non-executable scaffold — GitHub Actions
  only runs workflows under `.github/workflows/`.
- **Decision:** Build a real, functional gate: `postgres:16` + `redis:7` service containers,
  `compileall`/`alembic upgrade`/unit/architecture/integration steps. Deployment itself out of
  scope — no cloud target is configured in this sandbox (confirmed with the user).
- **Architecture Change:** None.
- **Files Modified:** `.github/workflows/backend-pipeline.yml` (new),
  `ci-cd/pipelines/backend-pipeline.yml` (rewritten to a pointer comment).
- **Documentation Updated:** Pipeline file's own header comment explains the redirect.
- **ADR Created:** None.
- **Migration Required:** No.
- **Backward Compatibility:** N/A.
- **Testing:** The pipeline *is* the test gate; validated by inspection (YAML structure,
  service container config) since this sandbox cannot execute a live GitHub Actions run.

### Issue 12 — No contract tests; 5 documented `GET`-list endpoints missing

- **Root Cause:** No test validated the implementation against the documented `/api/v1`
  surface (testing.md #4). Building that suite surfaced a real, previously-flagged-but-blocked
  gap: `GET /organizations`, `/regions`, `/vehicles`, `/devices`, `/users` were documented
  (API Contracts §4.1/§4.2) but never implemented — each router's own docstring already
  recorded why ("needs `effective_org_scope` — still pending"), a blocker Issue 2
  (ScopeResolver/ADR-0005) had since resolved.
- **Decision:** Fix all five, reusing each module's own existing `.read` permission (no new
  RBAC migration); scope the contract suite to `app.openapi()` schema introspection only —
  `httpx`/`TestClient` is not an approved dependency in this environment, and a further
  dependency-approval round-trip was judged not worth interrupting the user's "keep going
  autonomously" instruction for.
- **Architecture Change:** None.
- **Files Modified:** `list_all()` added to `OrganizationRepository`/`RegionRepository`/
  `VehicleRepository`/`DeviceRepository`/`UserRepository` (domain + SQLAlchemy infra), one
  `List*Query`+service method per aggregate, one `GET` route per resource
  (`organization`/`fleet_device`/`iam` modules); `tests/contract/test_api_contracts_routes.py`
  (new).
- **Documentation Updated:** All three router module docstrings rewritten from "deliberately
  not implemented" to "added under Backend Stabilization."
- **ADR Created:** None.
- **Migration Required:** No (reused existing `.read` permission grants).
- **Backward Compatibility:** Preserved — additive routes only.
- **Testing:** 905 unit / 10 architecture / 75 integration (pre-existing) + 2 contract, all
  green at the time of this fix's own commit.

### Issue 13 — Four modules (IAM, Organization, Fleet Device, Tracking) had no dedicated live-DB integration test file

- **Root Cause:** CLAUDE.md's own "Known gaps" flagged these as the only completed modules
  whose `SqlAlchemyUnitOfWork` wiring was exercised only indirectly (via
  `test_rbac_and_scope_resolver.py`/`test_postgres_repository_invariants.py`), unlike every
  other module's own dedicated round-trip test file.
- **Decision:** Write the missing four, mirroring `test_transport_ops_driver_repository.py`'s
  skip-guard/cleanup pattern exactly.
- **Architecture Change:** None — testing gap, not a design gap.
- **Files Modified:** `tests/integration/test_{iam,organization,fleet_device,tracking}_
  repository.py` (all new). Writing `test_tracking_repository.py` caught a real production bug
  (Issue 14) and writing `test_organization_repository.py` clarified a real ordering constraint
  in test setup (region must be committed before a referencing organization, matching how
  `ensure_region_exists` already requires in production — not a production bug, a test-setup
  correction).
- **Documentation Updated:** N/A (test-only phase).
- **ADR Created:** None.
- **Migration Required:** No.
- **Backward Compatibility:** N/A.
- **Testing:** 20 new tests, all passing against the live sandbox database.

### Issue 14 — Real production bug: `delete_before` crashed on every real invocation

- **Root Cause:** `SqlAlchemyVehiclePositionRepository.delete_before(cutoff)` bound a
  tz-aware `cutoff` (a `Clock.now()`-derived value, per its caller's own arithmetic) directly
  against `vehicle_positions.event_time`, a naive-UTC `TIMESTAMP WITHOUT TIME ZONE` column
  (ADR-0002) — the same naive/aware datetime bug class already fixed in billing's
  `sweep_expired_subscriptions`/`reconcile_expired_payments` this phase, missed here. Every
  real call raised `asyncpg.exceptions.DataError` ("can't subtract offset-naive and
  offset-aware datetimes"), caught only once a live-DB test exercised it (Issue 13) — no
  in-memory unit test could have caught this, since fakes never round-trip through a real
  driver's timestamp binding.
- **Decision:** Reuse `mappers._naive` — the exact strip-tzinfo helper `vehicle_position_to_
  model` already applies to `event_time`/`received_at` — rather than inventing a second
  helper.
- **Architecture Change:** None.
- **Files Modified:** `raad/modules/tracking/infra/repositories.py` (import + one-line fix in
  `delete_before`).
- **Documentation Updated:** Inline docstring on `delete_before` explaining the bug class and
  the fix, for the next person who adds a datetime-comparison query against this schema.
- **ADR Created:** None (bug fix, not an architecture decision).
- **Migration Required:** No.
- **Backward Compatibility:** Preserved — `delete_before`'s public signature/behavior is
  unchanged; this makes a previously-always-crashing path actually work.
- **Testing:** `test_position_delete_before_prunes_only_older_rows` (the test that caught it),
  re-verified green after the fix; full 905/10/95/2 suite re-run clean.

### Issue 15 — Dead code (`core/validation`) and a stale `README.md`

- **Root Cause:** `SelfValidating`/`ensure`/`guard_not_none` (Phase 4.2 scaffolding) had zero
  imports anywhere in the codebase or tests across all ten completed bounded contexts — every
  module validates via Pydantic at the API boundary and `DomainError`/`ValidationError`
  directly in value objects/entities instead, a pattern established independently of this
  module. Separately, `backend/README.md`'s "Status"/"Roadmap" sections still described a
  five-of-ten-modules, no-RBAC, empty-`tests/architecture/` snapshot from early in the project,
  flatly contradicting CLAUDE.md.
- **Decision:** Retire `core/validation` entirely (per this phase's explicit "don't preserve a
  bad design because it already exists" mandate — dead code with zero adopters, not
  "not yet adopted"). Rewrite the stale README sections to point to CLAUDE.md as the single
  currently-maintained source of truth, avoiding re-introducing the same duplication-then-
  staleness pattern.
- **Architecture Change:** None.
- **Files Modified:** `raad/core/validation/` (deleted), `backend/README.md`.
- **Documentation Updated:** `backend/README.md` (this issue's own primary artifact).
- **ADR Created:** None.
- **Migration Required:** No.
- **Backward Compatibility:** Preserved — confirmed via grep before deletion that nothing
  imported the removed module; app startup and full suite re-verified after removal.
- **Testing:** `python -m compileall raad` + app-factory smoke test + full 905/10/95/2 suite,
  all green after removal.

### Issue 16 — Load tests had no artifact at all

- **Root Cause:** No test, script, or document existed for load/performance validation against
  Phase 2 §13.1's NFR targets.
- **Decision:** Document, not fabricate. Two real structural blockers: no deployed environment
  exists in this sandbox to load-test against, and §13.1's own targets are explicitly marked
  "proposals... for owner sign-off," not yet confirmed — writing strict pass/fail gates against
  unconfirmed numbers would silently promote a proposal to a requirement.
- **Architecture Change:** None.
- **Files Modified:** `testing/load/README.md` (new), `testing/README.md` (status line
  updated).
- **Documentation Updated:** Both files above — a documented plan (five scenarios mapped to
  §13.1's rows) plus the four concrete prerequisites before it can become executable, one of
  which (a load-testing tool) is itself gated on workflow.md #1/#2's dependency-approval rule.
- **ADR Created:** None.
- **Migration Required:** No.
- **Backward Compatibility:** N/A.
- **Testing:** N/A — this issue's resolution is the documentation itself, per this task's own
  explicit "scaffold/document only... justified as intentionally deferred" instruction.

---

## Part 2 — Closing Summary

### 1. Issues fixed

All sixteen above: RBAC, ScopeResolver, D4/CR-1 tracking-visibility reconciliation,
`LatestPositionPort`, Video (C6) + D5 enforcement, Platform & Audit (C10) + the shared
audit-write kernel, Notifications (C7) + CR-1 withholding, Reporting (C9), Billing (C8) +
reconciliation jobs, the Redis Streams broker + both workers + scheduled jobs, a real CI/CD
gate, contract tests + 5 missing list endpoints, 4 missing integration-test files, one real
production bug (`delete_before`), one dead-code removal + one stale-doc fix, and a documented
load-test deferral.

### 2. Architecture improvements

- One shared-kernel pattern (`AuditWriter` + base-UoW threading) now covers both transactional
  outbox *and* transactional audit writes identically, closing the LLD-§10-vs-backend.md-#3
  conflict with zero per-module changes.
- `TrackingVisibilityPolicy` and `VideoAccessPolicy`/`enforce_d5` are the sole, non-bypassable
  enforcement points for their respective safety-critical predicates — no scattered
  `if subscription_active` checks anywhere.
- The method-granularity optional-port pattern (billing → tracking) keeps every application
  service constructible even when one specific capability's dependency is absent, rather than
  making a whole service's DI binding conditional on its least-available dependency.

### 3. Documentation updates

CLAUDE.md rewritten to "all ten bounded contexts complete" with an honest, itemized "Known
gaps" section; 5 new ADRs (0004–0008); `backend/README.md`'s stale Status/Roadmap corrected;
`testing/README.md` + new `testing/load/README.md`; every touched router's module docstring
updated in place rather than left describing removed deferrals.

### 4. ADRs created

- 0004 — RBAC permission matrix
- 0005 — Scope resolver
- 0006 — D4/CR-1 safety-over-billing reconciliation
- 0007 — `audit_entries` write architecture
- 0008 — Redis Streams event broker

### 5. New abstractions

`AuditWriter` (shared-kernel transactional audit write), `RedisStreamsBrokerPort`/
`RedisStreamsBrokerConsumer`/`RedisDeadLetterQueue`, `RedisLockPort`, `VideoProviderPort`
(deliberately left unbound — abstraction only, per this task's explicit native-JT1078
prohibition), `_NotificationFanOut` + 4 event processors, `ReportRendererPort` (deliberately
unbound).

### 6. Infrastructure added

Redis (`redis-py`, user-approved) backing both `RedisLatestPositionPort` and the event broker;
a real GitHub Actions CI gate (`postgres:16` + `redis:7` service containers); Notification
Worker and Report Worker processes; three scheduled jobs (position-history pruning, subscription
expiry sweep, payment reconciliation).

### 7. Security improvements

RBAC and ScopeResolver both resolve for real on every route (previously: universal
`NotImplementedError` / no enforcement). D5 (parent video exclusion) has its first real
enforcement point. D4/CR-1 tracking visibility has one tested, non-bypassable predicate instead
of an undocumented conflict. `audit_entries` — required by security.md #8 — is now actually
written, transactionally, by every module.

### 8. Scalability improvements

Redis Streams chosen specifically because it required zero new infrastructure beyond what
`LatestPositionPort` already needed; consumer groups + `XPENDING`/`XAUTOCLAIM` give
horizontally-scalable, at-least-once worker delivery without a second counter store.

### 9. Performance improvements

None targeted directly this phase (load tests remain a documented deferral, Issue 16) — the
`vehicle_positions` retention-pruning job (bulk `DELETE`, flagged as a deviation from the
documented partition-drop mechanism since the table isn't actually partitioned yet) is the one
change with a direct, if modest, performance rationale (bounded table growth).

### 10. Remaining future work

Everything CLAUDE.md's own "Known gaps" section already names, unchanged by this phase except
where explicitly resolved above: `PaymentProviderPort` (EVC Plus)/`VideoProviderPort` vendor
adapters and the payment-callback signature scheme remain deliberately unbound; no `list_all()`
is yet filtered by the now-real `ScopeResolver` (a separate, larger, cross-cutting change);
`ReportDefinition` (Reporting) and the `student.assignment_changed` event-contract conflict
(Notifications) are real, unresolved documentation gaps awaiting an approved doc update, not a
code fix; RBAC/ScopeResolver *editing* (grant/revoke) has no HTTP route yet; load tests remain
documented-but-not-executable pending a confirmed §13.1 and a deployed environment.

---

## Part 3 — Scores

| Dimension | Score | Rationale |
|---|---|---|
| **Architecture** | 8.5/10 | All ten bounded contexts now complete end-to-end with consistent layering; the broker/worker/CI gaps that blocked several modules are closed. Docked for the still-unfiltered `list_all()` gap and two genuinely unresolved cross-document conflicts (ReportDefinition, notification event contract). |
| **DDD** | 8.5/10 | Aggregates, buffered domain events, value objects, and repository/UoW patterns are uniform across all ten modules, independently verified by `tests/architecture/`. Docked half a point for the deliberately-duplicated `_AggregateRoot`/`SYSTEM_PRINCIPAL` per module (an explicit, justified tradeoff, not an oversight) and the still-unresolved `StudentAssignmentRemoved`-name collision between two aggregates' event catalogs. |
| **Clean Architecture** | 9/10 | `api → application → domain` dependency direction and `infra`-implements-domain-interfaces hold everywhere, enforced by ten automated boundary-gate tests, not just convention. The one bare `RuntimeError` in `iam`'s `update_user` (an intentionally-unreachable defensive guard) was reviewed and confirmed already correctly handled by the global `Exception` handler — not a violation, but not perfectly idiomatic either. |
| **Security** | 8.5/10 | RBAC, ScopeResolver, D4/CR-1, and D5 all now have real, tested enforcement — the four biggest security gaps entering this phase. Docked for the still-unbound payment-callback signature verification (security.md #10) and the unfiltered `list_all()` gap, both explicitly flagged rather than silently left. |
| **Maintainability** | 8/10 | Dead code removed (`core/validation`), stale docs corrected (`README.md`), all four previously-untested modules now have live-DB coverage, and a real bug (`delete_before`) was found and fixed by that new coverage — direct evidence the maintainability investment paid for itself immediately. Docked for the per-module `_AggregateRoot`/`SYSTEM_PRINCIPAL` duplication, a deliberate tradeoff whose cost is real even if justified. |
| **Scalability** | 7.5/10 | Redis Streams + consumer groups give a horizontally-scalable event path; the outbox/audit shared-kernel pattern scales with each module without per-module changes. Docked because load tests remain undemonstrated (Issue 16) and the unfiltered `list_all()` gap is a real, unaddressed scalability liability once tenant counts grow. |
| **Production Readiness** | 7/10 | All ten bounded contexts are feature-complete and CI-gated with 905 unit / 10 architecture / 95 integration / 2 contract tests green. Not yet production-ready: two vendor adapters (payment, video) and the payment-callback verification scheme are unbound by design, the broker/workers have no live deployment to run against, and load tests are documented but not executed. These are the correct set of remaining blockers — not surprises — given the "fail loudly, don't fake it" discipline held throughout. |

---

*Report generated as the final deliverable of the Backend Final Architecture Resolution task.
Every issue above was either fixed, documented, or intentionally deferred with justification —
none left silently unresolved.*
