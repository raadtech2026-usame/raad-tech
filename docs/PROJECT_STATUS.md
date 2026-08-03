# RAAD — Project Status

**This document is the single source of truth for implementation progress.** It does not replace
`CLAUDE.md` (the architectural/historical record — *why* each decision was made) — this file
tracks *where things stand right now* and *what to do next*. See `.claude/rules/documentation.md`
for how the two relate: `CLAUDE.md` and `docs/business/` remain the sources of truth for
architecture; this file is the source of truth for progress and sequencing.

**Read this file before starting any implementation work.** See Section 14.

---

## 1. Executive Summary

| | |
|---|---|
| **Overall completion** | ~60% (weighted: ✅=100%, 🟡=50%, ❌/⏸=0%, across the 39 subsystems in Section 3 — a rough gauge, not a precise metric; Item 3 flips the Authentication row from 🟡 to ✅, but a single row's movement across 39 doesn't meaningfully shift this rounded figure) |
| **Production readiness** | **Not production-ready.** Core product (backend + web dashboard for Founder/Regional Manager/Support/Finance/Org Admin) is solid; six Priority-1 blockers remain open (Backups, TLS/HTTPS, and Auth rate limiting + account lockout closed) — see Section 5. |
| **Current phase** | Backend: all ten bounded contexts implemented; ADR-0018 (Device Inventory & Allocation) just landed. ADR-0019 (Session Cap) and ADR-0020 (Platform Analytics) are next in the backend milestone sequence but **paused** pending Priority-1 production-readiness work (see Section 5's callout). Frontend: F0–F7 complete, F8–F13 not started. Mobile: scaffold only, 0% built. Priority 1 work is active: Items 1–3 (Backups, TLS/HTTPS, Auth rate limiting + account lockout) complete, Item 4 (Redis production hardening) recommended next. — see Section 2 for the full per-track breakdown. |
| **Current git commit** | `f70863a` — `feat(infra): implement Priority 1 Item 2 - TLS/HTTPS` (branch `main`; this auth rate-limiting/account-lockout work is uncommitted as this line is written — see Section 14 rule 2 on why this field always lags by one commit) |
| **Last updated** | 2026-08-03 |

---

## 2. Current Phase

At-a-glance status per track. **Update this section after every completed implementation** —
it should never lag behind Section 3's detail.

| Track | Current phase |
|---|---|
| **Backend** | ADR-0018 (Device Inventory & Allocation) complete. All ten bounded contexts implemented end-to-end. Next queued backend work is ADR-0019 (Session Cap) / ADR-0020 (Platform Analytics), but both are **paused** — see the Section 5 callout on why Priority-1 production-readiness work goes first. |
| **Frontend** | Phases F0–F7 complete (design system, org/region/user/fleet/device/people management, live tracking). F8 (Notifications), F9 (Billing), F10 (Video), and reporting/analytics feature folders are empty — not started. |
| **Mobile** | Pre-implementation. `mobile/` is a structural scaffold only — no Flutter SDK dependency declared in `pubspec.yaml`, `lib/main.dart` is a 0-byte file, no native Android/iOS project files exist. `flutter create` has never been run. |
| **Infrastructure** | Docker Compose (dev + prod overlays) verified working end-to-end, including a real nginx reverse proxy. **Priority 1 Item 1 (Backups) complete.** **Priority 1 Item 2 (TLS/HTTPS) complete** — nginx `prod-tls.conf` + a `certbot` service (Let's Encrypt via webroot challenge, auto-renewal), mechanism built and carefully reviewed but not live-tested against a real domain (none provisioned yet — Known Issue #13). **Priority 1 Item 3 (Auth rate limiting + account lockout) complete** — account lockout fully live-verified (real Postgres round trip + real HTTP requests against a running server); IP-based rate limiting's counting logic unit-tested only (no reachable Redis in this sandbox — Known Issue #14), but its Redis-unreachable fail-open behavior *is* live-verified over real HTTP. Production monitoring and Redis persistence hardening remain open — two of the remaining Priority-1 blockers (Section 5). |

---

## 3. Architecture Status

Legend: ✅ Complete &nbsp;·&nbsp; 🟡 Partial &nbsp;·&nbsp; ❌ Missing &nbsp;·&nbsp; ⏸ Deferred (deliberate, not a gap)

### Identity & access

#### Authentication — ✅ Complete
- **Implemented:** From-scratch HS256 JWT service (`backend/raad/core/security/tokens.py`), refuses to boot in prod with an unset/default secret; refresh-token rotation on every `/auth/refresh`, hashed at rest; PBKDF2-HMAC-SHA256 password hashing (260k iterations); enforced password-strength policy. **Priority 1 Item 3:** account lockout (`User.record_failed_login`/`is_locked` — 5 failed attempts locks for 15 minutes, both configurable), fully live-verified against real Postgres and a real running server; IP-based login rate limiting (`RateLimitMiddleware` + `LoginRateLimiter`, Redis `INCR`+`EXPIRE` fixed window) with a live-verified fail-open path when Redis is unreachable — see Known Issue #14 for the one disclosed residual gap (counting logic itself untested against a real Redis server, no reachable instance in this sandbox).
- **Missing:** Nothing blocking. Known Issue #14 (rate limiter's real-Redis round trip) is low-severity, non-blocking.
- **Production blocker?** No longer.
- **Dependencies:** None (foundational).

#### Authorization / RBAC — 🟡 Partial
- **Implemented:** Seeded `role_permissions` matrix enforced on every route (ADR-0004); tenant/region scope resolved once at the edge, enforced at the repository layer (ADR-0005); ADR-0021 closed a real cross-org IDOR, independently re-verified (68 tests + a live two-org script).
- **Missing:** Zero HTTP route to grant/revoke a permission or region/support assignment — DB-only today.
- **Production blocker?** Yes (operationally — RAAD can't safely onboard its own staff).
- **Dependencies:** Authentication.

#### Organizations (onboarding + CRUD) — ✅ Complete
- **Implemented:** ADR-0017's one guided RAAD-only flow — creates the Organization, assigns a Plan, issues the first Org Admin a one-time password with a forced change-on-first-login gate.
- **Missing:** Nothing.
- **Production blocker?** No.
- **Dependencies:** Authentication, Authorization.

#### Founder Onboarding & Recovery — ✅ Complete
- **Implemented:** One-shot CLI bootstrap (refuses to run if `users` has any row); documented recovery CLI + runbook.
- **Missing:** The 3-step bootstrap isn't atomic (documented, not hidden).
- **Production blocker?** No.
- **Dependencies:** Authentication.

### Fleet & people

#### Fleet (Vehicles + Devices, umbrella) — ✅ Complete
- **Implemented:** Full `Vehicle`/`Device` lifecycle, camera child entities, tenant-scoped CRUD.
- **Missing:** Nothing.
- **Production blocker?** No.
- **Dependencies:** Organizations.

#### Drivers — ✅ Complete
- **Implemented:** Register/update/activate/disable; trip-ownership enforcement (a Driver can only start/end their own trips).
- **Missing:** Nothing.
- **Production blocker?** No.
- **Dependencies:** Organizations.

#### Routes — ✅ Complete
- **Implemented:** Create/update/activate/disable, add-stop wired end-to-end.
- **Missing:** Nothing blocking.
- **Production blocker?** No.
- **Dependencies:** Organizations.

#### Stops — 🟡 Partial
- **Implemented:** `Route.add_stop` fully wired (domain + HTTP + frontend).
- **Missing:** `Route.remove_stop`/`move_stop` are implemented and unit-tested but have no approved HTTP route yet.
- **Production blocker?** No.
- **Dependencies:** Routes.

#### Students — ✅ Complete
- **Implemented:** Full enroll/update/activate/disable/graduate/transfer lifecycle; `StudentAssignment` (the CR-1 access gate).
- **Missing:** Nothing.
- **Production blocker?** No.
- **Dependencies:** Organizations, Routes.

#### Parents — ✅ Complete (backend only)
- **Implemented:** Register/update/activate/disable, student-parent linking, CR-1-gated visibility, reachable from the Organization dashboard.
- **Missing:** Nothing on the backend — but a Parent has no client of their own to use any of it (see Mobile App).
- **Production blocker?** Indirectly, via Mobile App.
- **Dependencies:** Students.

### Device supply chain

#### Devices (onboarding/lifecycle) — ✅ Complete
- **Implemented:** LSZ registration/heartbeat/position handlers; Redis-backed device-registry projection; proven end-to-end via `services/device-gateway/scripts/verify_redis_e2e.py`.
- **Missing:** Identity is serial-number-only (hardware has no credential, accepted per ADR-0015); no network-layer compensating control configured (IP allow-list/mTLS).
- **Production blocker?** No.
- **Dependencies:** None (RAAD-owned hardware pipeline).

#### Device Inventory — ✅ Complete
- **Implemented:** ADR-0018 — platform-scoped `device_inventory` pool, full state machine, `POST /device-inventory`.
- **Missing:** No `GET /device-inventory` list route (flagged in-code; a narrow usability gap).
- **Production blocker?** No.
- **Dependencies:** None.

#### Device Allocation — ✅ Complete
- **Implemented:** ADR-0018 — `POST /device-inventory/{id}/allocate` transitions the item and creates the `devices` row in one transaction; narrow read-only Org Admin visibility.
- **Missing:** Nothing.
- **Production blocker?** No.
- **Dependencies:** Device Inventory, Organizations.

#### JT808 — ⏸ Deferred (dormant by design)
- **Implemented:** Fully built, parsed, tested (`services/device-gateway/src/vendors/jt808/`), still instantiated live in the gateway.
- **Missing:** No procured hardware speaks it — kept ready for a future genuinely-compliant vendor.
- **Production blocker?** No.
- **Dependencies:** None.

#### JT1078 — ❌ Missing
- **Implemented:** Nothing. `services/jt1078/` is empty folders; README states the runtime isn't decided.
- **Missing:** Everything — session management, ingest, repackaging to WebRTC/HLS, a runtime decision, and LSZ-specific signaling (LSZ isn't JT/T 1078-compliant either).
- **Production blocker?** Only if live video is required for launch.
- **Dependencies:** A runtime/vendor decision.

### Live operations

#### GPS (ingestion) — ✅ Complete
- **Implemented:** Proven end-to-end: LSZ position frame → `DevicePositionReported` → Redis Streams → backend processor → `vehicle_positions` row; real writer for the `vehicle:{id}:last` Redis key.
- **Missing:** Alarm-flag taxonomy mapping, boarding/alighting modeling (tracked separately — see Known Issues).
- **Production blocker?** No.
- **Dependencies:** Devices, Redis.

#### Live Tracking — 🟡 Partial
- **Implemented:** `/ws/tracking` (JWT-authenticated, re-authorizes on every push); real F7 frontend page; geofence-crossing detection now wired into live ingestion.
- **Missing:** One active vehicle subscription per WebSocket connection (no fleet-wide live map); hard-dependent on Redis, which has no production hardening.
- **Production blocker?** Partially — works today, not yet trustworthy at scale.
- **Dependencies:** GPS ingestion, Redis (hardening).

#### Video — ❌ Missing
- **Implemented:** The D5 authorization policy (parents get zero reachable path to video) is real and enforced even though nothing exists behind it.
- **Missing:** Everything downstream of JT1078; frontend player (F10) not started.
- **Production blocker?** Only if required for launch.
- **Dependencies:** JT1078.

### Engagement & revenue

#### Notifications — 🟡 Partial
- **Implemented:** `Notification`+`DeviceToken` aggregates, `/ws/notifications`, a real Notification Worker gating sends through CR-1 across 4 event types.
- **Missing:** Zero frontend UI (`features/notifications/` empty — F8 not started); no mobile client to receive a push.
- **Production blocker?** Yes, for the customer-facing promise.
- **Dependencies:** Live Tracking (for trip events), Mobile App (for delivery to Parents).

#### Billing — 🟡 Partial
- **Implemented:** Full `Plan`/`Subscription`/`Invoice`/`Payment`/`TransportFee` lifecycle; 5 documented routes.
- **Missing:** `PaymentProviderPort` completely unbound — no charge has ever completed; zero frontend UI (F9 not started).
- **Production blocker?** Yes — no way to collect money today.
- **Dependencies:** A payment provider adapter (EVC Plus).

#### Subscriptions — 🟡 Partial
- **Implemented:** Full open/renew/expire/suspend/cancel lifecycle; two scheduled jobs keep state honest automatically.
- **Missing:** Nothing beyond Billing's payment-completion gap.
- **Production blocker?** Tied to Billing.
- **Dependencies:** Billing.

### Surfaces

#### Platform Dashboard — 🟡 Partial
- **Implemented:** 9 of 14 nav sections real (organizations, regions, users, vehicles, devices, drivers, routes, trips, live tracking).
- **Missing:** Notifications, reports, billing, audit, settings — all honest placeholders.
- **Production blocker?** Partially.
- **Dependencies:** Notifications, Billing, Reporting, Analytics (each backlogged feature owns one placeholder).

#### Organization Dashboard — 🟡 Partial
- **Implemented:** 7 of 12 sections real (vehicles, students, parents, drivers, routes, trips, live tracking).
- **Missing:** Video, notifications, reports, billing, users, settings.
- **Production blocker?** Yes, partially — a real customer hits a "being built" wall on day one.
- **Dependencies:** Same as Platform Dashboard, plus Video.

#### Mobile App — ❌ Missing
- **Implemented:** Nothing. `pubspec.yaml` declares no Flutter SDK; `lib/main.dart` is a literal 0-byte file; `android/`/`ios/` hold only `.gitkeep`. `flutter create` has never been run.
- **Missing:** Everything — auth, active-trip-only live GPS map, trip/payment history, push handling, offline states, native scaffolding.
- **Production blocker?** Yes, unconditionally — this is the *only* channel Parents/Drivers have.
- **Dependencies:** None technically (can start immediately); Notifications and Video are only meaningful to Parents once this exists.

### Insight

#### Analytics — ❌ Missing
- **Implemented:** Nothing beyond what already existed pre-ADR-0020 (`AuditEntry`, `SystemSetting`).
- **Missing:** The entire ADR-0020 scope — an `is_online` read-model, a stats read-model, a platform-stats route, and the frontend KPI grid.
- **Production blocker?** No.
- **Dependencies:** ADR-0020 implementation.

#### Reporting — ❌ Missing (functionally)
- **Implemented:** `ReportRun` request/track lifecycle and a Report Worker that polls queued runs.
- **Missing:** `ReportRendererPort` has zero binding (not even referenced in DI bootstrap) — every run ends `failed` by design; frontend `features/reports/` is empty.
- **Production blocker?** No for a pilot; yes before this can be marketed as working.
- **Dependencies:** A PDF/Excel rendering engine choice.

### Platform operations

#### Docker — 🟡 Partial
- **Implemented:** Real dev + production compose overlays, 3 real Dockerfiles (backend, frontend, device-gateway), working nginx reverse proxy — verified live per ADR-0013. Priority 1 Item 2: TLS termination mechanism (nginx `prod-tls.conf` + `certbot` service, Let's Encrypt via webroot challenge, auto-renewal) built and carefully reviewed.
- **Missing:** No container for `services/jt1078/`. TLS mechanism not live-tested against a real domain — no domain/VPS provisioned yet; see Known Issue #13.
- **Production blocker?** No longer for TLS itself (mechanism exists, documented two-phase bootstrap in `docs/runbooks/tls-setup.md`) — the residual risk is that it hasn't been proven against a real domain yet.
- **Dependencies:** A domain name + DNS pointed at a real VPS, to actually run the bootstrap.

#### Database (PostgreSQL) — ✅ Complete
- **Implemented:** SQLAlchemy 2.x async + Alembic, one linear migration chain, verified zero-drift, ADR-0021 tenant-isolation fix.
- **Missing:** Nothing in the schema layer itself (backups/encryption tracked separately).
- **Production blocker?** No, on its own merits.
- **Dependencies:** None.

#### Redis — 🟡 Partial
- **Implemented:** Event broker, live-position cache, geofence hysteresis state, both WS fan-out workers — all real, tested code.
- **Missing:** Zero production hardening — `infrastructure/redis/redis.conf.template` is a placeholder comment; no persistence (AOF/RDB) config, no HA plan.
- **Production blocker?** Yes.
- **Dependencies:** None.

#### Background Workers — ✅ Complete
- **Implemented:** Notification Worker, Report Worker, 3 scheduled jobs (`prune_vehicle_positions`, `sweep_expired_subscriptions`, `reconcile_expired_payments`), 2 WS fan-out workers.
- **Missing:** Nothing in the plumbing; Report Worker's output blocked on Reporting.
- **Production blocker?** No, on its own merits.
- **Dependencies:** Redis.

#### Monitoring — ❌ Missing
- **Implemented:** `/health`, `/health/live`, `/health/ready` endpoints exist.
- **Missing:** `/health/ready` doesn't check DB/Redis reachability (docstring admits this); no Prometheus/Grafana/Sentry/OpenTelemetry anywhere; `infrastructure/monitoring/` empty.
- **Production blocker?** Yes.
- **Dependencies:** None.

#### Logging — 🟡 Partial
- **Implemented:** Real structured JSON logging, backend + device-gateway, with PII redaction and correlation-id context.
- **Missing:** Stdout only, no shipping/aggregation anywhere; frontend has zero logging/error-tracking.
- **Production blocker?** Partially (acceptable for a single-VPS pilot via `docker logs`).
- **Dependencies:** A log-aggregation destination choice.

#### Deployment — 🟡 Partial
- **Implemented:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` genuinely works, live-verified (ADR-0013). Automated backups (Priority 1 Item 1) and a TLS/HTTPS mechanism (Priority 1 Item 2, `docs/runbooks/tls-setup.md`) both now ship as part of this stack.
- **Missing:** No monitoring, no secrets-manager integration, no deploy step in CI, no rollback runbook; `scripts/db/migrate.sh`/`seed.sh`/`scripts/dev/bootstrap.sh` are still literal 0-byte files. TLS itself is unverified against a real domain (Known Issue #13).
- **Production blocker?** Yes — the umbrella item.
- **Dependencies:** Monitoring, Security.

#### Backups — ✅ Complete (local mechanism; off-site not yet configured to a real destination)
- **Implemented:** Priority 1 Item 1. A `backup` Docker Compose service (`docker/backup.Dockerfile`,
  `FROM postgres:16-alpine` + `rclone`) runs continuously, dumping via `scripts/db/backup.sh`
  (`pg_dump --format=custom`) on a schedule (`BACKUP_INTERVAL_HOURS`), pruning local dumps past
  `BACKUP_RETENTION_DAYS`. `scripts/db/restore.sh` is a tested, explicit-`--confirm`-required
  restore path. Live-verified end-to-end against a real PostgreSQL server (seed → backup →
  restore into a throwaway database → data round-trip confirmed), automated in
  `testing/backups/test_backup_restore.sh`, wired into CI (`.github/workflows/backend-pipeline.yml`).
  Runbook: `docs/runbooks/backup-and-restore.md`.
- **Missing:** No off-site destination is actually provisioned yet — `BACKUP_RCLONE_REMOTE` is
  an unset, documented, pluggable hook (rclone supports 40+ backends via one config); until a
  real target is configured, the service logs a loud warning on every run rather than silently
  claiming off-site protection it isn't providing.
- **Production blocker?** No longer, for the local half. The off-site gap is still a real risk
  (a lost VPS with no off-site copy is still total data loss) — tracked as Known Issue #12, not
  re-opening this item.
- **Dependencies:** None. (An off-site destination, once chosen, is configuration only — no code
  change needed.)

#### Security (composite) — 🟡 Partial
- **Implemented:** Real tenant isolation (ADR-0021), real password hashing/policy, JWT with no hardcoded secrets, safe-by-default CORS, nothing secret committed to git. Data-loss risk lowered by Priority 1 Item 1 (Backups). Transport encryption mechanism shipped by Priority 1 Item 2 (TLS/HTTPS) — see Docker above for its unverified-against-a-real-domain caveat. Auth-abuse protection shipped by Priority 1 Item 3 (rate limiting + account lockout) — see Authentication above.
- **Missing:** In-repo encryption-at-rest, RBAC admin route, `/docs` exposed with no environment gating.
- **Production blocker?** Yes (RBAC admin route in particular — Section 5 Item 6).
- **Dependencies:** Authentication, Authorization.

### Completeness

#### API Completeness — ✅ Complete
- **Implemented:** All 10 bounded contexts expose working, RBAC-enforced, paginated REST APIs; a real contract test suite validates the OpenAPI surface; 1,180 unit tests + 10 architecture-gate tests passing.
- **Missing:** A handful of small, individually-tracked gaps (RBAC routes, stop reorder, camera registration, device-inventory listing, payment-callback verification).
- **Production blocker?** No, as a category.
- **Dependencies:** None.

#### Frontend Completeness — 🟡 Partial
- **Implemented:** F0–F7 built and tested — 54 real test files, working production build, correct in-memory-only token handling, real Docker/nginx deployment path.
- **Missing:** F8 (notifications), F9 (billing), F10 (video), reporting, analytics — all empty feature folders.
- **Production blocker?** Partially.
- **Dependencies:** Notifications, Billing, Video, Reporting, Analytics (backend halves).

#### CI/CD — 🟡 Partial
- **Implemented:** `.github/workflows/backend-pipeline.yml` — real, runs unit/architecture/integration tests against live Postgres+Redis service containers on every backend PR.
- **Missing:** No lint/security-scan gate, no deploy step, no frontend/mobile/device-gateway CI at all (`ci-cd/pipelines/*.yml` are empty placeholders except the backend one, which just points at the real workflow).
- **Production blocker?** No, but blocks safe automated deploys.
- **Dependencies:** None.

#### Documentation Completeness — 🟡 Partial
- **Implemented:** Exceptionally thorough at the architecture/business/ADR level — every phase recorded in `CLAUDE.md`, 21 ADRs covering every major decision.
- **Missing:** Only 2 of the planned operational runbooks exist (founder bootstrap, password recovery); no incident-response/rollback/on-call runbooks; no VPS/TLS/DNS deployment guide; two stale docstrings found (see Known Issues).
- **Production blocker?** Partially (folded into Deployment).
- **Dependencies:** None.

---

## 4. ADR Progress

| ADR | Title | Status |
|---|---|---|
| 0001 | Business Entity ↔ Module Mapping | ✅ Complete |
| 0002 | PostgreSQL Migration | ✅ Complete |
| 0003 | Parent Registration Orchestration | ✅ Complete (extended to cover Driver + Org onboarding) |
| 0004 | RBAC Permission Matrix | ✅ Complete |
| 0005 | Scope Resolver | ✅ Complete |
| 0006 | D4/CR-1 Safety-over-Billing Reconciliation | ✅ Complete (amended for ADR-0016) |
| 0007 | Audit Entries Write Architecture | ✅ Complete |
| 0008 | Redis Streams Event Broker | ✅ Complete |
| 0009 | MDVR Vendor Protocol (Device Plane) | ✅ Complete |
| 0010 | Device Gateway Multi-Vendor Architecture | ✅ Complete |
| 0011 | Mapbox Map Provider | ✅ Complete |
| 0012 | Development Redis Environment | ✅ Complete |
| 0013 | Platform Dockerization | ✅ Complete |
| 0014 | Geofence Evaluation Config Gaps | ✅ Complete |
| 0015 | Device-Plane Authentication Trust Model | ✅ Complete |
| 0016 | Organization-Only Billing Model | ✅ Complete |
| 0017 | Organization Onboarding Orchestration | ✅ Complete |
| 0018 | Device Inventory & Allocation | ✅ Complete |
| 0019 | Account-Sharing Session Cap | ❌ Not Started |
| 0020 | Platform Analytics Read Model | ❌ Not Started |
| 0021 | Tenant Scope Enforcement at Repository Layer | ✅ Complete |

---

## 5. Production Readiness Roadmap

> **On ADR-0019 / ADR-0020:** both are well-specified and next in the backend milestone
> sequence, but neither is a production blocker. Priority 1 below (backups, TLS, rate limiting,
> mobile app, payments, monitoring) is where a real launch actually gets stopped — recommend
> clearing Priority 1 first; ADR-0019/0020 slot into Priority 2.

### Priority 1 — Critical blockers before production
1. ~~**Backups**~~ — ✅ **Complete** (2026-08-03). Local `pg_dump`/`pg_restore` mechanism, live-verified round trip, CI-covered, pluggable off-site hook (unconfigured — see Known Issue #12). `docs/runbooks/backup-and-restore.md`.
2. ~~**TLS/HTTPS**~~ — ✅ **Complete** (2026-08-03). nginx `prod-tls.conf` + `certbot` service (Let's Encrypt via webroot challenge, auto-renewal via PID-namespace reload signal), two-phase bootstrap runbook. Mechanism built and carefully reviewed, **not live-tested against a real domain** (none provisioned — see Known Issue #13). `docs/runbooks/tls-setup.md`.
3. ~~**Auth rate limiting + account lockout**~~ — ✅ **Complete** (2026-08-03). Account lockout (`User.record_failed_login`/`is_locked`, migration `d4fbe03f2b94`) fully live-verified — real Postgres round trip + real HTTP smoke test against a running server. IP-based rate limiting (`LoginRateLimiter`, `RateLimitMiddleware`) unit-tested against a fake Redis; its fail-open-when-Redis-unreachable path live-verified (a real bug caught and fixed during that verification — see Known Issue #14). `AccountLockedError`/`RateLimitedError` added to the documented error taxonomy.
4. **Redis production hardening** — no persistence config; also closes Known Issue #14 (rate limiter's real-Redis round trip untested). *(1–2 days)* ← **recommended next**
5. **Real health checks + minimum monitoring** — `/health/ready` doesn't check its dependencies. *(3–5 days)*
6. **RBAC grant/revoke route** — RAAD can't onboard its own staff without hand-editing the DB. *(3–4 days)*
7. **Deployment & rollback runbook, VPS setup guide** — the TLS half of this is now covered by `docs/runbooks/tls-setup.md` (item 2); still missing: a general VPS provisioning guide and a rollback runbook. *(1–2 days remaining)*
8. **Payment provider adapter** — no real payment has ever completed. *(1–2 weeks)*
9. **Mobile app MVP** — Parents/Drivers have no way to use the system, in any form. *(4–8 weeks)*

### Priority 2 — Recommended before first customer
- Notifications web UI (F8) *(3–5 days)*
- Billing web UI (F9) *(3–5 days)*
- Live video / JT1078 — only if video is part of the launch pitch *(3–6 weeks)*
- Platform analytics (ADR-0020) *(1–2 weeks)*
- Session cap (ADR-0019) *(3–5 days)*
- Reporting renderer (PDF/Excel) *(~1 week)*
- Load testing — plan exists, zero scripts *(3–5 days)*
- Log shipping / aggregation *(1–2 days)*
- Secrets-manager integration, replacing hand-edited `.env` *(2–3 days)*
- CI hardening — lint/security scan + frontend/mobile/device-gateway CI *(2–3 days)*
- `/docs` gating for production *(&lt; 1 day)*
- SOS/overspeed alarm mapping + notification triggers *(3–5 days)*

### Priority 3 — Can wait until after launch
- Dark mode (mechanism exists, no palette)
- Boarding/alighting/ignition events (no design spec yet)
- Teltonika/Queclink/Ruptela vendor adapters (only relevant if a new vendor is procured)
- Route stop reorder/remove, camera registration, device-inventory list routes
- Remaining exception-workflow runbooks (device offline, GPS signal lost, etc.)
- Infrastructure-as-code (Terraform/Ansible/K8s) — only relevant beyond single-VPS scale
- Two stale docstrings (see Known Issues)

*(Full reasoning and evidence for this roadmap: see the 2026-08-02 production-readiness audit
referenced in Section 9.)*

---

## 6. Upcoming Roadmap

This is a different axis from Section 5: Section 5 orders work by *what blocks a safe launch*.
This section orders the same overall body of work by *conceptual build sequence*, beginning to
production — useful for seeing where "we" are in the big picture. The two will not always agree
on what's "next" (e.g. Session Cap is Phase 6 here but Priority 2 there) — that's expected; use
Section 5 for sequencing decisions and this section for orientation. **Update this roadmap
whenever a phase finishes.**

| Phase | Name | Status | Note |
|---|---|---|---|
| 1 | Architecture | ✅ Complete | Ten bounded contexts, Clean Architecture/DDD patterns, foundational ADRs (0001–0002, 0007–0008). |
| 2 | Authentication | ✅ Complete | Core JWT/RBAC complete; rate limiting + account lockout shipped (Priority 1 Item 3). |
| 3 | Organizations | ✅ Complete | Onboarding (ADR-0017), billing cutover (ADR-0016), tenant isolation (ADR-0021). |
| 4 | Tracking | 🟡 In Progress | GPS ingestion + live tracking backend complete; blocked on Redis production hardening for launch. |
| 5 | Device Inventory | ✅ Complete | ADR-0018. |
| 6 | ADR-0019 Session Cap | ⬜ Planned | Not started. |
| 7 | ADR-0020 Platform Analytics | ⬜ Planned | Not started. |
| 8 | Flutter Mobile App | ⬜ Planned | 0% built — structural scaffold only. |
| 9 | Video Platform | ⬜ Planned | JT1078, 0% built — runtime not yet decided. |
| 10 | Production Deployment | ⬜ Planned | Blocked on Section 5 Priority 1 (Redis hardening, monitoring, RBAC admin route, deployment docs, payments, mobile app). |

---

## 7. Future Features

Ideas that are **intentionally not part of the active roadmap** (Sections 5 and 6). Kept
separate specifically so they are never mistaken for required work or silently pulled into a
sprint.

- AI Camera
- Driver Voice Calls
- Parent ETA Prediction
- Fuel Monitoring
- School Payments
- Driver Behavior Scoring

None of these have an ADR, a design document, or an approved scope. Before any of them is ever
promoted out of this list, it must (a) get its own ADR per `.claude/rules/workflow.md` #8, and
(b) be checked against `CLAUDE.md`'s Product Scope guardrails — several of these sit close to the
project's explicit "not a school ERP" boundary and would need that conflict flagged and resolved
first, not assumed away.

---

## 8. Current Sprint

**Currently Working On:**
Nothing in-progress — Priority 1 Item 3 (Auth rate limiting + account lockout) just closed out
completely (architecture review → implementation → unit tests → live Postgres integration test
→ live HTTP verification against a real running server → regression suite → docs → this update),
per the user's explicit "one item at a time, fully finished" process.

**Completed This Sprint:**
- **Priority 1 Item 3 — Auth rate limiting + account lockout.** Account lockout: `User.
  record_failed_login`/`is_locked` (`modules/iam/domain/entities.py`) — 5 consecutive failed
  attempts locks the account for 15 minutes (both configurable via `LockoutSettings`); a prior
  window's lapse resets the counter rather than accumulating across unrelated episodes; a
  successful login or any legitimate password-establishing action (`change_password_hash`/
  `set_temporary_password_hash`, the existing operator "reset password" path) clears lockout
  state, giving operators an unlock path with zero new API surface or RBAC permission. New
  `AccountLockedError` (401, `ACCOUNT_LOCKED`) and migration `d4fbe03f2b94` (`users.
  failed_login_attempts`/`locked_until`). Rate limiting: `LoginRateLimiter` (`core/security/
  login_rate_limiter.py`, Redis `INCR`+`EXPIRE` fixed window) + new `RateLimitMiddleware`,
  scoped to `POST /api/v1/auth/login` only, wired into `main.py` between
  `CorrelationIdMiddleware` and `SecurityContextMiddleware`; new `RateLimitedError` (429,
  `RATE_LIMITED`). **Two real bugs were caught during live verification, not just asserted
  away:** (1) a tz-aware/naive datetime bug — `model_to_user` (`modules/iam/infra/mappers.py`)
  never applied the existing `_aware_utc` conversion on read, so `User.is_locked` crashed with
  `TypeError` the instant a real, previously-persisted locked account was checked (the exact
  same class of bug `RefreshToken.is_expired` had already taught this codebase to guard
  against) — caught by the new live-Postgres lockout round trip, fixed by applying `_aware_utc`
  uniformly across `created_at`/`updated_at`/`last_login_at`/`locked_until`. (2) The rate-limit
  middleware only handled "Redis not configured" (`limiter is None`) — a *configured but
  unreachable* Redis (this sandbox's actual condition: `RAAD_REDIS__URL` is set, but nothing is
  listening on `localhost:6379`) would have raised an uncaught `RedisError` on every login
  attempt, taking `/auth/login` down entirely; fixed by catching `RedisError` and failing open
  (log once, allow the request), then live-confirmed via a real running server + real HTTP
  requests logging the warning exactly once across 6 requests while login kept working
  throughout. Account lockout's full round trip (5 wrong passwords → `ACCOUNT_LOCKED` even with
  the correct password on attempt 6) was also verified the same way, against a real disposable
  user in the live database. 15 new domain unit tests, 8 new application unit tests (plus 1
  pre-existing test's commit-count assertion corrected for the new, intentional persist-on-
  failure behavior), 6 new rate-limiter unit tests, 4 new live-Postgres integration tests — 1203
  unit + 10 architecture tests pass with zero regressions; the only integration-suite failures
  are the pre-existing, already-disclosed "no reachable Redis in this sandbox" gap in unrelated
  tracking/broker-fanout tests. Zero changes to any other bounded context, RBAC, or tenant
  isolation.
- **Priority 1 Item 2 — TLS/HTTPS.** nginx `prod-tls.conf` (new) + `prod.conf` gains an ACME
  challenge location; a new `certbot` Docker Compose service (official image, no custom
  Dockerfile) obtains/renews Let's Encrypt certificates via the webroot HTTP-01 challenge and
  reloads nginx by sharing its PID namespace (`kill -HUP 1`) rather than mounting the Docker
  socket. `${DOMAIN_NAME}` substitution uses nginx's own official templating mechanism. Two real
  bugs were caught by careful review (this sandbox cannot run `nginx -t`/`docker compose up`):
  an accidentally-added `ports: !reset []` on nginx that would have un-published port 80 in
  prod, and a TLS-config catch-all that would have redirected the container's own `/health`
  healthcheck to HTTPS and broken it. A real self-signed certificate (via the locally-available
  `openssl`) confirmed the cert file paths match certbot's actual output convention. New runbook
  `docs/runbooks/tls-setup.md` — two-phase bootstrap, Let's-Encrypt-staging-first
  recommendation, verifying auto-renewal, troubleshooting. Zero changes to any bounded context,
  RBAC/tenant-isolation code, or migration.
- **Priority 1 Item 1 — Backups.** New `backup` Docker Compose service
  (`docker/backup.Dockerfile`), `scripts/db/{backup,restore,backup-loop}.sh`, local retention,
  pluggable off-site `rclone` hook (unconfigured — Known Issue #12). Live-verified end-to-end
  against a real PostgreSQL server using disposable throwaway databases (seed → backup → restore
  → data-integrity check → cleanup); a real bug was found and fixed during that verification
  (connection-string passwords were being logged in plaintext — now redacted in both scripts).
  Automated round-trip test `testing/backups/test_backup_restore.sh`, wired into
  `.github/workflows/backend-pipeline.yml`. New runbook `docs/runbooks/backup-and-restore.md`.
  Zero changes to any bounded context, RBAC/tenant-isolation code, or migration.
- ADR-0018 (Device Inventory & Allocation) — full vertical slice: domain, application, infra,
  API, 2 migrations, RBAC grants, 23 new unit tests, 5 new integration tests. Committed as
  `d13a5a8`.
- Full 38-subsystem production-readiness audit (read-only, no code changes) covering docs,
  infra/Docker/deployment, device-plane depth, frontend/mobile, and backend security.
- This document (`docs/PROJECT_STATUS.md`), created and then expanded into the permanent
  Project Control Center (Sections 2, 6, 7, 12, 13).

**Next Task:**
**Recommended: Priority 1 Item 4 — Redis production hardening.** Directly closes Known Issue
#14 (the rate limiter's untested-against-real-Redis gap) as a side effect, on top of its own
persistence/HA scope. Per Section 14's rules, the next implementation session should not resume
ADR-0019/ADR-0020 or skip ahead in the Priority 1 list until the user confirms or redirects.

---

## 9. Recent Completed Work

Reverse-chronological (most recent first):

- **Priority 1 Item 3 — Auth rate limiting + account lockout** completed — account lockout
  (`User.record_failed_login`/`is_locked`, migration `d4fbe03f2b94`) fully live-verified against
  real Postgres and a real running server; IP-based rate limiting (`LoginRateLimiter`,
  `RateLimitMiddleware`) unit-tested against a fake Redis, with its Redis-unreachable fail-open
  path live-verified. Two real bugs caught and fixed during live verification: a tz-aware/naive
  datetime bug in `model_to_user` (identical class of bug to the earlier `RefreshToken.
  is_expired` regression) and a missing `RedisError` handler that would have taken `/auth/login`
  down entirely whenever Redis was configured but unreachable — this sandbox's actual condition.
- **Priority 1 Item 2 — TLS/HTTPS** completed — nginx `prod-tls.conf` + `certbot` service (Let's
  Encrypt via webroot challenge, PID-namespace auto-reload on renewal), two-phase bootstrap
  runbook; mechanism built and carefully reviewed but not live-tested against a real domain (none
  provisioned).
- **Priority 1 Item 1 — Backups** completed — local `pg_dump`/`pg_restore` mechanism, live
  round-trip verified, CI-covered, runbook written; off-site copy shipped as a documented,
  pluggable hook, not yet wired to a real destination.
- **ADR-0018 — Device Inventory & Allocation** completed (backend, migrations, RBAC, tests).
- **Production-readiness audit** completed (38 subsystems, read-only).
- **Tenant Isolation Security Audit & Fix (ADR-0021)** completed — closed a live cross-org IDOR
  at the repository layer, module by module (`fleet_device`, `organization`, `transport_ops`,
  `billing`, `iam`), plus a `/ws/tracking` RBAC-capability gap; 68 new tests + a live two-org
  verification script.
- **WebSocket phase** completed — `/ws/tracking` + `/ws/notifications`, Redis Streams fan-out
  workers, live re-authorization on every position push.
- **Pagination/Filtering/Sorting phase** completed — offset + cursor pagination across every
  list endpoint in the API.
- **Final Backend Completion phase** completed — closed 7 confirmed RBAC/error-code/ownership/
  audit-column gaps, added CORS support.
- **Organization Billing cutover (ADR-0016)** completed — parent-billing path removed outright,
  Organization-only billing model.
- **Organization Onboarding orchestration (ADR-0017)** completed — one guided RAAD-only flow.
- **Founder Recovery** completed — CLI-based password recovery for a locked-out Founder.
- **IAM provisioning port** completed — cross-context orchestration for Org Admin / Driver
  account creation.
- **Device Domain Overhaul** completed — RAAD-owns-hardware RBAC correction, hardware-intake
  identity fields (`imei`/`iccid`/`serial_number`).
- **MDVR vendor protocol integration (ADR-0009/0010)** completed — the LSZ vendor stack,
  device-gateway multi-vendor reorganization, real Redis event bus + device registry.
- **Backend Stabilization phase** completed — RBAC permission matrix, `ScopeResolver`, Redis
  Streams broker, all ten bounded contexts' domain→infra→API stacks.

*(For the full reasoning behind each phase, see `CLAUDE.md`.)*

---

## 10. Known Issues

### 1. ~~No rate limiting or account lockout on authentication~~ — RESOLVED 2026-08-03
- **Resolution:** Priority 1 Item 3. Account lockout (`User.record_failed_login`/`is_locked`,
  `modules/iam/domain/entities.py`; migration `d4fbe03f2b94` adds `failed_login_attempts`/
  `locked_until` to `users`) is fully live-verified — a real Postgres round trip
  (`tests/integration/test_iam_repository.py`'s `AccountLockoutRepositoryTests`) and a real
  running-server HTTP smoke test (5 wrong passwords → `ACCOUNT_LOCKED` 401 even with the
  correct password on the 6th attempt). IP-based rate limiting
  (`core/security/login_rate_limiter.py`, `RateLimitMiddleware`) is unit-tested against a fake
  Redis only — see Known Issue #14 for the narrower, disclosed residual gap this left (the
  counting/threshold logic itself was never exercised against a real Redis server, only its
  fail-open-when-Redis-is-unreachable path, which *was* live-verified).
- **Severity:** ~~High~~
- **Blocking production?** No longer.

### 2. ~~Zero backup mechanism~~ — RESOLVED 2026-08-03
- **Resolution:** Priority 1 Item 1. `docker-compose.yml`'s `backup` service, `scripts/db/
  {backup,restore}.sh`, live-verified round trip, CI coverage, `docs/runbooks/
  backup-and-restore.md`. See Known Issue #12 for the one remaining, lower-severity piece
  (off-site destination not yet configured).
- **Severity:** ~~Critical~~
- **Blocking production?** No longer.

### 3. `/health/ready` doesn't check real dependencies
- **Severity:** High
- **Recommended fix:** Add actual Postgres/Redis connectivity checks before reporting ready.
- **Blocking production?** Yes.

### 4. `PaymentProviderPort`, `VideoProviderPort`, `ReportRendererPort` all unbound
- **Severity:** High (Payment), Medium (Video, Reporting)
- **Recommended fix:** Bind a real EVC Plus adapter (Payment); decide a JT1078 runtime (Video);
  pick a PDF/Excel engine (Reporting).
- **Blocking production?** Payment: yes. Video/Reporting: only if marketed as working at launch.

### 5. Stale docstring — `tracking/infra/adapters.py`
- **Severity:** Low (documentation hygiene, not a functional bug)
- **Description:** Still states no writer exists for the `vehicle:{id}:last` Redis key. The LSZ
  vendor's `RedisLatestPositionWriter` now supplies exactly that.
- **Recommended fix:** Update the docstring to reflect the device-gateway's writer.
- **Blocking production?** No.

### 6. Stale docstring — `fleet_device/api/routers.py`
- **Severity:** Low
- **Description:** Still states "neither the JT808 service nor that consumer exists yet, so
  `last_seen_at` is always NULL" — `DeviceConnectivityProcessor` now consumes
  `DeviceOnline`/`DeviceOffline` and populates it for real.
- **Recommended fix:** Update the docstring.
- **Blocking production?** No.

### 7. `DeviceAlarmRaised` event defined but never constructed
- **Severity:** Medium
- **Description:** The event type and publisher branch exist in
  `services/device-gateway/src/events/redis_event_publisher.py`, but no handler (LSZ or dormant
  JT808) ever builds one — dead code path.
- **Recommended fix:** Either wire a real alarm handler or remove the unused event type until one
  exists.
- **Blocking production?** No.

### 8. `alarm_flags` has no per-bit taxonomy mapping
- **Severity:** Medium
- **Description:** LSZ's `alarm_flags` is parsed as an opaque, range-clamped integer and passed
  through with no ACL/taxonomy mapping. `0` means "unmapped/unknown," not "verified no alarms" —
  a real ambiguity if this is ever surfaced to an end user.
- **Recommended fix:** Design and implement the alarm-bit → taxonomy mapping (SOS, overspeed,
  etc.) before marketing any alarm-based safety feature.
- **Blocking production?** No, unless alarms are marketed as working.

### 9. ADR-0020's Context section conflates two different consumers
- **Severity:** Low
- **Description:** ADR-0020 frames the `DeviceOnline`/`DeviceOffline` consumer as something it
  still needs to build — but the `last_seen_at`-populating consumer is already real (see Known
  Issue 6). ADR-0020 actually needs a *second*, distinct consumer that additionally sets a new
  `devices.is_online` boolean for the KPI grid.
- **Recommended fix:** Amend ADR-0020's Context section to name the two consumers separately
  before implementation starts.
- **Blocking production?** No.

### 10. `infrastructure/mysql/` templates are orphaned
- **Severity:** Low
- **Description:** Leftover placeholder config from before ADR-0002 moved the project to
  PostgreSQL. Still present, unused, potentially confusing to a new contributor.
- **Recommended fix:** Delete `infrastructure/mysql/`.
- **Blocking production?** No.

### 11. `ci-cd/pipelines/*.yml` and `scripts/*.sh` are non-functional placeholders
- **Severity:** Low
- **Description:** `ci-cd/pipelines/frontend-pipeline.yml`, `mobile-pipeline.yml`,
  `jt808-pipeline.yml`, `jt1078-pipeline.yml`, `infrastructure-pipeline.yml` are empty.
  `scripts/db/migrate.sh`, `scripts/db/seed.sh`, `scripts/dev/bootstrap.sh` are literal 0-byte
  files. Neither is wired to anything — GitHub Actions only reads `.github/workflows/`.
- **Recommended fix:** Either implement them or remove the misleading scaffolding.
- **Blocking production?** No.

### 12. Backup off-site destination not yet configured
- **Severity:** Medium
- **Description:** Priority 1 Item 1 shipped a fully working, live-verified local backup
  mechanism plus a pluggable off-site hook (`BACKUP_RCLONE_REMOTE`, via `rclone`) — but no real
  off-site destination (S3-compatible bucket, second server, etc.) is actually provisioned yet.
  Every backup today lives only on the same disk as the database it protects. The service logs a
  loud warning on every run rather than silently claiming protection it isn't providing.
- **Recommended fix:** Provision a real destination and set `BACKUP_RCLONE_REMOTE` in
  `docker/.env` — see `docs/runbooks/backup-and-restore.md`'s "Configuring off-site storage"
  section. No code change needed, configuration only.
- **Blocking production?** Not this item on its own, but a real risk until closed — a lost VPS
  with only local backups is still total data loss.

### 13. TLS mechanism not live-tested against a real domain
- **Severity:** Medium
- **Description:** Priority 1 Item 2 shipped a complete, carefully-reviewed TLS termination
  mechanism (nginx `prod-tls.conf`, a `certbot` service for Let's Encrypt via the webroot HTTP-01
  challenge, PID-namespace-based auto-reload on renewal) — but it has never been run against a
  real domain, because no domain or VPS is provisioned yet. This sandbox also has no local
  `nginx`/`certbot` binary and no Docker daemon, so not even `nginx -t`/`docker compose config`
  could be run; verification was YAML structural validation, a hand-simulated Compose merge, and
  careful manual config review (which did catch two real bugs — see Section 9's entry for this
  item) rather than an actual boot/request cycle.
- **Recommended fix:** Follow `docs/runbooks/tls-setup.md` once a domain/VPS exist — Step 2's
  Let's-Encrypt-**staging** run is deliberately where the first genuinely live test happens,
  safely, before any production certificate request.
- **Blocking production?** Not on its own (the design is the standard, documented pattern for
  this exact topology, and `prod.conf`'s plain-HTTP fallback stays the safe default until an
  operator explicitly opts in) — but treat "TLS live-verified" as not yet true until the runbook
  has actually been run once for real.

### 14. Login rate limiter's counting logic never exercised against a real Redis server
- **Severity:** Low
- **Description:** Priority 1 Item 3 shipped `LoginRateLimiter` (`core/security/
  login_rate_limiter.py`, a Redis `INCR`+`EXPIRE` fixed-window counter) and wired it into
  `RateLimitMiddleware`. Its counting/threshold logic is unit-tested only, against a fake
  in-memory Redis double (`tests/unit/test_login_rate_limiter.py`) — this sandbox's configured
  `RAAD_REDIS__URL` (`redis://localhost:6379/0`) is confirmed genuinely unreachable (`Error 22
  connecting to localhost:6379`), so the real `INCR`/`EXPIRE` round trip against an actual Redis
  server has never run. What **has** been live-verified, over a real running server and real HTTP
  requests: the middleware's fail-open behavior when `LoginRateLimiter` is bound but Redis is
  unreachable (`RedisError` caught, logged exactly once, `/auth/login` keeps working) — this was
  in fact caught and fixed *during* this item's own live verification (the original design only
  handled "unbound," not "bound but connection fails," which would otherwise have taken
  `/auth/login` down entirely the moment Redis was configured-but-down, exactly this sandbox's own
  condition).
- **Recommended fix:** Once Priority 1 Item 4 (Redis production hardening) makes a real reachable
  Redis instance available, re-run `tests/unit/test_login_rate_limiter.py`'s scenarios against it
  (or add a dedicated live integration test) to confirm the real `INCR`/`EXPIRE` behavior matches
  the fake's.
- **Blocking production?** No — the fail-open design means an unreachable/misconfigured Redis
  degrades to "rate limiting temporarily off," never to "login broken," and account lockout
  (Known Issue #1, resolved) is the higher-value, fully-live-verified control of the two.

---

## 11. Deployment Checklist

Live checklist for a real VPS deployment — update as each item closes.

- [x] **TLS** — mechanism complete (Priority 1 Item 2): nginx `prod-tls.conf` + `certbot`
      service, auto-renewal. Check this box again once `docs/runbooks/tls-setup.md`'s bootstrap
      has actually been run for real (Known Issue 13) — stays on plain HTTP (`prod.conf`) until
      an operator opts in via `NGINX_PROD_CONF`.
- [ ] **Domain** — no domain name assigned/configured yet; required before Item 2's mechanism can
      actually be exercised.
- [x] **Docker** — dev + prod compose overlays real and live-verified (ADR-0013); missing only a
      `services/jt1078/` container (tracked separately, see Video/JT1078).
- [x] **Backups** — local `pg_dump`/`pg_restore` mechanism live-verified, CI-covered (Priority 1
      Item 1). Off-site copy is a configured-or-loud-warning hook, not yet pointed at a real
      destination (see Known Issue 12) — check this box again once `BACKUP_RCLONE_REMOTE` is set.
- [ ] **Redis** — real in code, zero production hardening (no persistence config, no HA).
- [x] **PostgreSQL** — schema/migrations solid, verified zero-drift.
- [ ] **Monitoring** — only basic `/health*` endpoints; no real dependency checks, no
      Prometheus/Grafana/Sentry.
- [ ] **Logging** — real structured JSON, but stdout-only; no shipping/aggregation configured.
- [ ] **Health Checks** — endpoints exist; `/health/ready` doesn't verify DB/Redis reachability.
- [ ] **Environment Variables** — `.env.example` templates exist for every service; real
      deployment still means hand-editing a `.env` on the host, no secrets manager.
- [ ] **CI/CD** — backend test-only pipeline exists; no deploy step, no lint/security gate, no
      frontend/mobile/device-gateway CI.
- [x] **Reverse Proxy** — nginx configs (dev/prod/frontend) real and working.
- [ ] **Object Storage** — not present anywhere in the repo (no S3-equivalent evaluated for
      report files, etc.).
- [ ] **Secrets** — plain env vars only; no Vault/sealed-secrets/cloud secrets manager.
- [ ] **Firewall** — not configured or documented anywhere in-repo.

---

## 12. Business Rules (Protected)

These are the project's non-negotiable business rules — drawn from the existing architecture
record (`CLAUDE.md`, the ADRs cited below, `.claude/rules/`), restated here for quick reference,
**not newly invented.** Any feature request that would violate one of these must be flagged
explicitly, per `.claude/rules/workflow.md` #7, not silently implemented around.

- RAAD owns all hardware. *(Device Domain Overhaul; ADR-0018)*
- Organizations own all operational data — vehicles, drivers, routes, students, parents, staff
  users. *(Three-tier business model)*
- Organizations create Students.
- Organizations create Parents.
- Parents never exist at Platform level — Parent is Organization-scoped and mobile-only.
  *(`.claude/rules/flutter.md` #1)*
- RAAD bills Organizations only — no direct parent billing. *(ADR-0016)*
- Organizations collect money from Parents independently, outside RAAD's billing system.
  *(ADR-0016's scope boundary)*
- Device Inventory belongs only to RAAD — platform-scoped, carries no `organization_id`.
  *(ADR-0018)*
- Devices become visible to an Organization only after allocation, and only read-only.
  *(ADR-0018 §3)*
- Organization users must never access another Organization's data. *(Tenant isolation, ADR-0021)*
- Multi-tenancy is mandatory — every tenant-owned entity carries `organization_id`, enforced at
  the repository layer, not just the UI. *(`.claude/rules/architecture.md` #4; ADR-0021)*

---

## 13. Architecture Freeze

Decisions listed here must **never be changed without explicit approval** before implementation.
This is a subset of Section 12 focused specifically on structural/technical decisions (Section 12
covers business rules; this section covers the architecture that enforces them).

- Multi-tenant architecture
- Tenant isolation, enforced at the repository layer *(ADR-0021)*
- Organization-only billing model *(ADR-0016)*
- Device Inventory design (platform-scoped, no `organization_id`) *(ADR-0018)*
- Device Allocation workflow *(ADR-0018)*
- Redis Streams event architecture *(ADR-0008)*
- Scope Resolver *(ADR-0005)*
- RBAC model *(ADR-0004)*
- Event-driven architecture between the device plane and business plane *(ADR-0009, ADR-0010)*
- GPS ingestion pipeline (device-gateway → Redis → backend)

**Any change to these decisions requires explicit approval before implementation.**

---

## 14. Development Rules

Before implementing **any** feature:

1. Read `PROJECT_STATUS.md`.
2. Verify it matches the current repository — this file describes reality, but code is the final
   authority; if they disagree, trust the code and fix this file.
3. Read `CLAUDE.md`.
4. Determine the highest-priority unfinished work.
5. Confirm it does not conflict with frozen architecture (Section 13) or a protected business
   rule (Section 12).
6. Continue only the next approved roadmap item (Section 5 or Section 6).
7. Update `PROJECT_STATUS.md` after every completed implementation.
8. Keep `PROJECT_STATUS.md` synchronized with `CLAUDE.md` — `CLAUDE.md` remains the authority on
   *why*; this file is the authority on *current state and what's next*.

These rules absorb and extend the project's existing discipline: never repeat completed work,
and never remove valid architecture (Section 13) without the explicit approval it requires.

This document must always reflect the real repository, not planned work. Treat it as mandatory
reading before every implementation session.
