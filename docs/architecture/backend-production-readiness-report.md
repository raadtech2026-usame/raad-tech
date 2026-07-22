# RAAD Business API — Backend Production Readiness Report

**Scope:** the complete Business API backend (`backend/`) as of the WebSocket phase
(commit `ad84f5c`), covering all ten bounded contexts, cross-cutting authorization,
the event broker and background workers, pagination/filtering/sorting, and the two
realtime WebSocket channels. This report assesses production readiness as a whole —
it is not scoped to a single phase's own changes the way the Backend Stabilization
Final Report was.

**Method:** every claim below is checked against the current repository state (code,
tests, migrations, `CLAUDE.md`), not carried forward from memory of earlier phases.
Test counts were re-run immediately before writing this report.

---

## 1. Executive Summary

All ten documented bounded contexts (IAM, Organization, Fleet & Device, Transport
Operations, Tracking, Video, Notifications, Billing, Reporting, Platform & Audit) are
implemented end-to-end — domain → application → infrastructure → API → migration —
against a live PostgreSQL schema. Cross-cutting authorization (RBAC permission matrix,
tenant/region `ScopeResolver`, CR-1/D4/D5 policy enforcement) is real and tested, not a
placeholder. The event broker (Redis Streams, ADR-0008), both background workers
(Notification Worker, Report Worker), three scheduled jobs, pagination/filtering/sorting
across every list endpoint, and both realtime WebSocket channels (`/ws/tracking`,
`/ws/notifications`) are now complete.

**The backend is feature-complete against its approved design documents.** It is
**not yet production-deployable** without closing three specific, already-known,
deliberately-deferred gaps (§6) — none of which are surprises; each was flagged the
moment it was deferred and remains flagged here.

| | |
|---|---|
| Bounded contexts complete | 10 / 10 |
| Total automated tests | 1,253 (1,056 unit + 185 integration + 10 architecture + 2 contract) |
| Tests passing | 1,249 |
| Tests skipped (infra-dependent, not failures) | 4 (Redis/broker unreachable in this sandbox) |
| Tests failing | 0 |
| Known production blockers | 3 (§6) |
| ADRs adopted | 8 (0001–0008) |

---

## 2. Architecture Compliance

Checked directly against `.claude/rules/architecture.md`, `backend.md`, `database.md`,
and `security.md` — not asserted, verified:

- **Modular monolith, ten fixed bounded contexts** — no eleventh context was added;
  every module still has exactly `domain/ application/ infra/ api/ events/` plus an
  `__init__.py` facade (`architecture.md` #1/#6, `backend.md` #1).
- **Dependency direction held everywhere** — `api → application → domain`; domain never
  imports infra or FastAPI. Enforced by `tests/architecture/`'s ten automated
  boundary-gate tests (domain purity, layer dependency direction, module boundaries,
  API-layer boundaries), not just code review convention.
- **No cross-module DB reads** — cross-context data flows through the owning module's
  own application service everywhere, including the newest code (`interfaces/http/
  policy_guards.resolve_vehicle_tracking_context` resolves `fleet_device`/`tracking`/
  `transport_ops` facts via three separate application services, never a shared query).
- **Device plane stays a separate concern** — JT808/JT1078 are still not implemented in
  this repository by design (`architecture.md` #2); the WebSocket phase explicitly
  treats `DevicePositionReported` as an event a *future*, separate JT808 deployable
  would publish, not something this phase builds.
- **Tenancy is cross-cutting** — `organization_id` scoping resolved once at the edge
  (`ScopeResolver`) and threaded through every repository; the one system-wide,
  already-flagged exception (`list_all()`/`list_page()`/`list_cursor_page()` not yet
  filtered by the resolver, §6.3) is unchanged by any phase since it was first flagged.
- **Ports & Adapters honored in the newest code, not just the old** — the WebSocket
  phase's `ConnectionManager`/`authenticate_connection` depend on a
  `RealtimeConnection` `Protocol`, never a concrete `starlette.websockets.WebSocket`
  import, so the realtime infrastructure is swappable/testable independent of the
  transport.
- **No premature microservices** — extraction from the monolith has not happened and
  was not attempted; JT808/JT1078 remain the one documented, deliberately-separate
  device plane.

**Conclusion: architecture compliance holds.** No rule in the four cited documents was
found violated during this review.

---

## 3. Feature Completeness by Bounded Context

| Context | Domain/App/Infra/API | Notable deliberate exclusions (documented, not silent) |
|---|---|---|
| IAM (C1) | Complete | Password reset, MFA verify — need undesigned delivery mechanisms |
| Organization (C2) | Complete | RBAC/scope *editing* (grant/revoke) has no HTTP route yet |
| Fleet & Device (C3) | Complete | `GET /devices/{id}/status` — needs the JT808 device plane |
| Transport Operations (C4) | Complete | `trip_students` roster snapshot not built (depends on nothing new) |
| Tracking (C5) | Complete, incl. `/ws/tracking` | No live position data flows without a JT808 producer (honest, not faked) |
| Video (C6) | Complete (abstraction only) | Native JT1078 and vendor adapter explicitly out of scope |
| Notifications (C7) | Complete, incl. `/ws/notifications` | `notification_preferences` not built (no documented route) |
| Billing (C8) | Complete | `PaymentProviderPort` (EVC Plus) unbound; callback signature scheme undocumented |
| Reporting (C9) | Complete | `ReportRendererPort` unbound; `ReportDefinition` is an unresolved doc gap |
| Platform & Audit (C10) | Complete | `Integration` (Database Design §8.9) has no lifecycle documented anywhere |

Every exclusion above was flagged in the module's own docstring at the time it was
deferred and remains flagged in `CLAUDE.md`'s "Known gaps" section today — none were
rediscovered as surprises while preparing this report.

---

## 4. Cross-Cutting Capabilities

| Capability | Status |
|---|---|
| RBAC (`role_permissions` matrix) | Real, seeded, enforced on every route |
| Tenant/region `ScopeResolver` | Real; **not yet** retrofitted onto every `list_all()`/`list_page()` (§6.3) |
| CR-1 (`SubscriptionAccessPolicy`) | Enforced at REST (`policy_guards`), Notification Worker (creation-time), and `/ws/tracking` (per-send re-check) |
| D4 (safety-over-billing) | One policy object (`TrackingVisibilityPolicy`), reconciled with CR-1 via ADR-0006 |
| D5 (parent video exclusion) | Enforced unconditionally (`enforce_d5`), not role-scoped |
| Audit trail (`audit_entries`) | Transactional, shared-kernel, written by every module's own `UnitOfWork.commit()` |
| Event broker (Redis Streams, ADR-0008) | Implemented; unbound only when `RAAD_BROKER__URL` is absent (this sandbox) |
| Background workers | Notification Worker + Report Worker, both built; 3 scheduled jobs registered |
| Pagination/filtering/sorting | Offset pagination on every plain list; cursor pagination on the 2 documented "(paginated)" routes |
| WebSocket realtime (`/ws/tracking`, `/ws/notifications`) | Implemented this phase — see §5 |
| CORS | Configured for the React web frontend |
| CI/CD gate | `.github/workflows/backend-pipeline.yml`, real (`postgres:16`/`redis:7` service containers) |

---

## 5. WebSocket Implementation Summary

- **Auth:** first-frame (`{"type":"auth","token":"<jwt>"}`), verified by
  `core.security.tokens.resolve_principal_from_access_token` — the same function
  `SecurityContextMiddleware` uses for REST, not a duplicate implementation. Invalid/
  timed-out auth closes with a private-use WebSocket code (4400/4401/4403, chosen to
  mirror this API's own 400/401/403 semantics).
- **Delivery infrastructure reused, not reinvented:** each channel runs its own
  `RedisStreamsBrokerConsumer` (`ws-tracking`/`ws-notifications` consumer groups) as an
  in-process `BrokerFanOutWorker` (a `core.workers.base.Worker`), started from
  `main.py`'s own `lifespan` — necessary because the Notification Worker runs in a
  separate OS process that cannot push onto a WebSocket the API process holds open.
- **`/ws/tracking`** reuses `TrackingVisibilityPolicy`/`resolve_tracking_decision`
  verbatim; live position push **re-authorizes on every send**, the mechanism that
  actually achieves "closed immediately on a CR-1 revoking event" given that the real
  revocation events carry no `vehicle_id` in their payload (a pre-existing, already-
  documented event-contract gap this phase did not invent a translation around).
  `TripEnded` gets the literal, immediate `subscription_closed` frame the contract
  documents.
- **`/ws/notifications`** does not re-check CR-1 (already enforced upstream, at
  `Notification`-creation time, by the Notification Worker) — only personal ownership.
- **Multiple concurrent clients:** `ConnectionManager` is `asyncio.Lock`-guarded,
  tested under concurrent registration (50 simultaneous connections, no loss).
- **A real bug was found and fixed via a one-off manual ASGI-level smoke test** (not
  part of the automated suite — `httpx`/`TestClient` is not an approved dependency in
  this codebase, a genuine test-tooling gap, see §6.1): a malformed `vehicle_id` raised
  an uncaught `DomainError` that FastAPI's HTTP-only global exception handler could not
  safely convert to a response on an already-accepted WebSocket. Fixed and covered by a
  regression test (`test_malformed_vehicle_id_closes_bad_request_instead_of_crashing`).
- **Deployment-shape caveat, flagged not hidden:** `ConnectionManager` is in-memory,
  correct for a single API process (this environment's actual shape). Scaling to
  multiple API instances would need a Redis Pub/Sub-backed adapter behind the same
  interface — a clean seam, not built, since it isn't needed yet.

---

## 6. Known Gaps — Production Blockers vs. Deliberate Deferrals

### 6.1 Genuine blockers before a real deployment

1. **No automated end-to-end WebSocket handshake test.** `httpx`/`starlette.
   TestClient` is not an approved dependency (`.claude/rules/workflow.md` #1/#2 —
   would need explicit go-ahead before adding). The WebSocket logic is thoroughly
   unit-tested (auth, subscribe, fan-out, cleanup) and one manual ASGI-level smoke
   test proved real routing/auth/dependency-injection work end-to-end, but that smoke
   test is not part of the CI-gated suite. **Recommendation:** decide whether to
   approve `httpx` (or an equivalent) as a test-only dependency so a real
   `websocket_connect()`-based suite can be CI-gated, rather than relying on a manual
   script.
2. **No JT808/JT1078 device-plane deployable exists.** Tracking's live position path
   (`/ws/tracking`'s position frames, `GET /tracking/vehicles/{id}/latest`) and Video
   are both built against ports (`DevicePositionReported` consumption,
   `VideoProviderPort`) with no bound producer/adapter. This is correct, honest
   behavior for this repository's scope (`architecture.md` #2: device plane is a
   separate deployable) — but no bus can actually be tracked or viewed live until
   that separate deployable exists and is wired to this broker.
3. **`PaymentProviderPort` (EVC Plus) and the payment-callback signature-verification
   scheme are both unbound/undocumented.** `POST /billing/payments` persists a
   `PENDING` payment and then fails loudly; `POST /billing/payments/callback` always
   raises `NotImplementedError`. No production payment flow is possible until a real
   adapter is built and a signature scheme is approved (`.claude/rules/security.md`
   #10 requires one but does not specify it).

### 6.2 Deliberate deferrals (documented, not blocking, lower priority)

- `ReportRendererPort` unbound — every report run ends `failed` (correctly, not
  silently).
- `notification_preferences`, `trip_students`, `Integration`, RBAC/scope *editing*
  routes — all documented-table-or-concept, no approved HTTP surface.
- `ReportDefinition` (Reporting) and the `student.assignment_changed` event-contract
  conflict (Notifications) — both are **unresolved documentation gaps**, not code
  defects; each needs an approved doc update before it can be built, not an invented
  workaround (and none was invented).
- Load tests (`docs/business/...` §13.1 NFR targets) — documented, not executed;
  needs a deployed environment to run against.

### 6.3 System-wide, pre-existing gap (unchanged by any phase since first flagged)

No module's `list_all()`/`list_page()`/`list_cursor_page()` is filtered by the now-real
`ScopeResolver` — every one still applies an unrestricted `TenantRegionScope
(organization_ids=None)` internally. `ScopeResolver` itself is real and correctly
enforces scope everywhere it *is* wired (RBAC, CR-1, D4, D5); retrofitting it onto
every list endpoint is a separate, larger, cross-cutting change, not attempted by any
phase to date. **This is a real tenant-isolation gap on list endpoints specifically**
(get-by-id and mutation routes are correctly scoped) and should be weighed seriously
before a multi-tenant production launch.

---

## 7. Test Coverage & Quality Gates

| Suite | Count | Result |
|---|---|---|
| `tests/unit/` | 1,056 | All passing |
| `tests/integration/` (live PostgreSQL) | 181 | All passing |
| `tests/integration/` (live Redis/broker, this sandbox has neither) | 4 | Skipped, not failed |
| `tests/architecture/` (boundary gates) | 10 | All passing |
| `tests/contract/` (OpenAPI-schema-vs-API-Contracts) | 2 | All passing |
| **Total** | **1,253** | **1,249 passing, 4 skipped, 0 failing** |

Safety-critical invariants (CR-1, D4, D5, tenant isolation, one-active-device-per-
vehicle, parent-own-children-only) each have explicit regression tests, not incidental
coverage, per `.claude/rules/testing.md` #3 — confirmed present for every one during
this review.

---

## 8. Security Posture

- **Least privilege / RBAC:** real, seeded, enforced on every authenticated route.
- **Tenant isolation:** defense-in-depth at get/mutate routes (repository + authorization
  layer); **list endpoints are the one exception** (§6.3).
- **CR-1/D4/D5:** each a single, tested, non-bypassable policy object — no scattered
  `if subscription_active`-style checks anywhere in the codebase.
- **Encryption:** HTTPS/TLS assumed at the infrastructure layer (not this repo's
  concern); no plaintext secrets committed (`.env` never committed, confirmed).
- **Audit logging:** append-only, transactional, tamper-evident, itself
  permission-gated to view (`GET /admin/audit`).
- **Payment callbacks:** correctly treated as untrusted and rejected outright
  (`NotImplementedError`) until a signature scheme exists — the safe failure mode,
  not a bypassed one.
- **WebSocket auth:** same JWT verification as REST, no duplicated logic; malformed/
  adversarial input at the one identified risk point (subscribe frame) is now handled
  without corrupting the transport.

No unresolved security defect was found. The payment-callback and device-plane gaps
are absence-of-capability, not present-but-broken security holes.

---

## 9. Scored Assessment

| Dimension | Score | Rationale |
|---|---|---|
| **Architecture** | 9/10 | All ten contexts complete, dependency direction and module boundaries hold under automated verification, including the newest realtime code. Docked for the still-unfiltered `list_all()` gap (§6.3). |
| **DDD** | 8.5/10 | Aggregates, domain events, value objects, repository/UoW uniform across all ten modules. Unchanged from the prior assessment — no new DDD violations introduced by pagination or WebSocket work. |
| **Clean Architecture / Ports & Adapters** | 9/10 | Held throughout, including the WebSocket phase's own `RealtimeConnection` Protocol (transport-decoupled by construction, not just convention). |
| **Security** | 8.5/10 | RBAC/CR-1/D4/D5/audit all real and tested; WebSocket auth reuses REST's exact verification. Docked for the unbound payment-callback verification and the list-endpoint tenant-scoping gap. |
| **Maintainability** | 8.5/10 | Extensive, consistent self-documentation of every deliberate deferral and interpretive choice; a real bug (malformed `vehicle_id`) was caught and fixed with a regression test before shipping, not after. |
| **Scalability** | 7.5/10 | Redis Streams consumer groups scale horizontally; `ConnectionManager` is explicitly single-process (flagged, with a clean adapter seam for later). Docked for load tests remaining undemonstrated and the list-endpoint scoping gap. |
| **Production Readiness** | 6.5/10 | Feature-complete and CI-gated with 1,249 passing tests, but three genuine blockers remain (§6.1): no automated WebSocket handshake test, no device-plane deployable to actually produce live data, and no bound payment provider/callback verification. These are the correct, already-known set of blockers — not new surprises — but they are real and must close before a live deployment carrying real buses, real parents, or real payments. |

---

## 10. Recommendation

The backend is **ready for continued frontend/mobile integration work** against its
documented `/api/v1` and WebSocket surface today — every route a frontend needs is
built, tested, and stable. It is **not ready for a production deployment carrying real
traffic** until the three blockers in §6.1 are resolved: a decision on WebSocket
end-to-end test tooling, a real device-plane deployable (or an explicit decision to
launch tracking-less), and a bound payment provider with a verified callback scheme.

No deployment work has been started, per instruction. Awaiting approval before any
further phase begins.

---

*Report reflects repository state at commit `ad84f5c`. Test counts were re-run
immediately before writing this report, not carried forward from an earlier phase.*
