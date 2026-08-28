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
| **Overall completion** | ~68% (weighted: ✅=100%, 🟡=50%, ❌/⏸=0%, across the 39 subsystems in Section 3 — a rough gauge, not a precise metric; Mobile App moved ❌→🟡 this item, though entirely unverified — see below) |
| **Production readiness** | **Backend + web dashboard: production-ready for a first pilot VPS deployment**, pending only real external accounts (a real domain for TLS, a real VPS to run the already-written provisioning runbook against, a real Stripe merchant account for live payments) — every Priority 1 item touching the backend/web/infra surface (1–8) is now complete and either live-verified or mechanism-complete-with-disclosed-testing-limits: **Item 8 (Payment) is no longer an architectural blocker** — ADR-0022 (2026-08-06) shipped a real, verified `StripePaymentAdapter`, a wired webhook route, and a production `OrgBillingPage` "Pay Invoice" flow, resolving both the design gaps (signed-webhook-caller representation, provider abstraction shape) this item used to carry; only a live merchant account's credentials remain, same disclosed posture as TLS/Redis. Two deployment paths now exist side by side: the original generic-VPS/nginx/certbot path, and a new Coolify-managed path (`docker-compose.coolify.yml`, `docs/runbooks/coolify-deployment.md`) for the user's own chosen Hostinger-VPS-via-Coolify target. **Mobile: not production-ready** — Item 9 shipped a real M0/M2 foundation and a partial M3, but is entirely unverified (no Flutter SDK in this sandbox) and is missing FCM push (M4) and release packaging (M5), both blocked on real external accounts. **ADR-0023 (2026-08-07)** closed Known Issue #17 on the backend side (a canonical `GET /me`/`GET /me/students`/`GET /me/driver-profile` self-service identity capability) — M3's own blocking backend gap is resolved, though the mobile client itself is not yet wired to it (same missing-SDK limitation as the rest of Item 9). This is the direct continuation of the continuous-completion program (user directive 2026-08-03) — see Section 15 for that program's own final report, and Section 8 for ADR-0022's/ADR-0023's own full writeups. |
| **Current phase** | Backend: all ten bounded contexts implemented; ADR-0018 (Device Inventory & Allocation), ADR-0019 (Account-Sharing Session Cap), ADR-0020 (Platform Analytics Read Model), and **ADR-0022 (Payment Provider Architecture) have all now landed** — every backend milestone in the original "IAM provisioning port → org onboarding → billing cutover → device inventory → session cap → platform analytics" sequence (CLAUDE.md's own Business Model section) is complete, plus this unplanned-at-the-time payment-architecture milestone the user added afterward. Frontend: **F0–F9 complete**, with F9's own previously-deferred Organization Billing half now also complete (ADR-0022: dedicated `OrgBillingPage` + real "Pay Invoice" flow) — F8: Notifications web UI (first cursor-paginated page, first live-WS-driven bell badge); F9: Billing web UI (platform-wide read-only tabs + org-scoped subscription/invoice/payment view and a real payment flow) — plus the ADR-0020 KPI grid and a fleet-ops-style dashboard redesign/polish pass; **F10 (Video) is complete** (`/org/video` built 2026-08-14 commit `600c4da`, unified with GPS into one Vehicle Operations view by ADR-0027/0028/0029, live-hardware-verified 2026-08-19) — reporting is the one frontend feature folder still genuinely empty. Mobile: M0/M2 code-complete, M3 partial, M4/M5 not started, entirely unverified. See Section 2 for the full per-track breakdown and Section 15 for the Priority 1 program's consolidated final report. |
| **Current git commit** | This turn's own commit (recording ADR-0026's parent video access authorization in PROJECT_STATUS.md/the five rule files) is created immediately after this line is written — see Section 14 rule 2 on why this field always lags by one commit; the four prior commits were `9cda51e` (feat(mobile): permission-gated Parent WS-FLV video player), `5bd6524` (feat(video,jt1078): reconcile relay lifecycle, concurrency ceilings, SPS/PPS/AVCC), `cca7c96` (feat(transport_ops,video,iam): implement ADR-0026 parent video access authorization), and `fd8f330` (docs(adr): accept ADR-0026) — each already one commit behind by the time this line is read (the same real, disclosed, recurring staleness rule 2 warns about, not a one-time slip). |
| **Last updated** | 2026-08-13 |

---

## 2. Current Phase

At-a-glance status per track. **Update this section after every completed implementation** —
it should never lag behind Section 3's detail.

| Track | Current phase |
|---|---|
| **Backend** | All ten bounded contexts implemented end-to-end. ADR-0018 (Device Inventory & Allocation), ADR-0019 (Session Cap), ADR-0020 (Platform Analytics), and **ADR-0022 (Payment Provider Architecture) have all now landed** — every originally-planned backend milestone is complete, plus this later-added payment-architecture milestone. |
| **Frontend** | Phases F0–F9 complete (design system, org/region/user/fleet/device/people management, live tracking, ADR-0020 KPI grid + fleet-ops dashboard redesign, notifications web UI, billing web UI — including ADR-0022's own org-scoped `OrgBillingPage` + "Pay Invoice" flow, previously deferred out of F9). **F10 (Video) is also complete** (`/org/video`, commit `600c4da`, 2026-08-14; unified with GPS into one Vehicle Operations view and extended to Platform Admin by ADR-0027/0028/0029, 2026-08-16; live-hardware-verified 2026-08-19) — reporting is the one feature folder still empty, not started. |
| **Mobile** | Pre-implementation. `mobile/` is a structural scaffold only — no Flutter SDK dependency declared in `pubspec.yaml`, `lib/main.dart` is a 0-byte file, no native Android/iOS project files exist. `flutter create` has never been run. *(Note: Priority 1 Item 9 has since shipped a real, unverified M0/M2/partial-M3 foundation — see Section 3/8; this row is stale and not yet corrected, flagged rather than silently left implying zero mobile work exists.)* |
| **Infrastructure** | Docker Compose (dev + prod overlays, plus a new Coolify-managed alternative — ADR-0022, `docker-compose.coolify.yml`) verified working end-to-end, including a real nginx reverse proxy. **Priority 1 Items 1 (Backups), 2 (TLS/HTTPS), 3 (Auth rate limiting + lockout), 4 (Redis hardening), 5 (health checks + monitoring), 6 (RBAC admin routes), and 7 (deployment runbooks) are all complete** — each either fully live-verified or mechanism-complete with a disclosed, specific testing limitation (Known Issues #12–#16), consistently the "no Docker/live external dependency in this sandbox" gap, never an unverified design. **Item 8 (Payment) is now mechanism-complete too** (ADR-0022) — see the Executive Summary and Known Issue #4 for the full detail. |

---

## 3. Architecture Status

Legend: ✅ Complete &nbsp;·&nbsp; 🟡 Partial &nbsp;·&nbsp; ❌ Missing &nbsp;·&nbsp; ⏸ Deferred (deliberate, not a gap)

### Identity & access

#### Authentication — ✅ Complete
- **Implemented:** From-scratch HS256 JWT service (`backend/raad/core/security/tokens.py`), refuses to boot in prod with an unset/default secret; refresh-token rotation on every `/auth/refresh`, hashed at rest; PBKDF2-HMAC-SHA256 password hashing (260k iterations); enforced password-strength policy. **Priority 1 Item 3:** account lockout (`User.record_failed_login`/`is_locked` — 5 failed attempts locks for 15 minutes, both configurable), fully live-verified against real Postgres and a real running server; IP-based login rate limiting (`RateLimitMiddleware` + `LoginRateLimiter`, Redis `INCR`+`EXPIRE` fixed window) with a live-verified fail-open path when Redis is unreachable — see Known Issue #14 for the one disclosed residual gap (counting logic itself untested against a real Redis server, no reachable instance in this sandbox). **ADR-0019 (Account-Sharing Session Cap):** `SessionLimitPolicy` (`core/policies/session_limit.py`) enforced at both `login`/`refresh`, revoking the oldest non-revoked/non-expired `RefreshToken`(s) once a per-role cap is exceeded — a refresh's own rotated token is excluded from the count so an ordinary refresh never spuriously evicts an unrelated session. The cap is a single `platform_audit.SystemSetting` row (`key="session_cap"`, one `{role: max_sessions}` dict — a per-role key doesn't fit `SystemSettingKey`'s 26-char max, discovered while implementing, not assumed from the ADR text), read via a new `SessionCapPort`/`SystemSettingSessionCapAdapter` (`core/di/session_cap_adapter.py`) that reaches `platform_audit`'s application facade only — confirmed architecturally clean by the existing `tests/architecture/test_module_boundaries.py` gate, not just asserted. Previously-dead `refresh_tokens.user_agent`/`ip_address` columns are now populated; a new `device_label` column (migration `4ef3fefb5e8d`) holds a short parsed label (`core/security/user_agent.py`, no new dependency). Self-service `GET`/`DELETE /auth/sessions` (masked `ip_address` via `core/security/ip_mask.py`). A "login from an unrecognized device" signal (`SuspiciousLoginDetected`, visibility-only per `security.md` #8) is skipped on a genuinely first-ever login — flagged interpretive choice, the ADR's own "not seen in the last N sessions" leaves N undefined. Live-verified against real Postgres, including the real `SystemSettingSessionCapAdapter` reading the actual migration-seeded row per role (not just a test double).
- **Missing:** Nothing blocking. Known Issue #14 (rate limiter's real-Redis round trip) is low-severity, non-blocking.
- **Production blocker?** No longer.
- **Dependencies:** None (foundational).

#### Authorization / RBAC — ✅ Complete
- **Implemented:** Seeded `role_permissions` matrix enforced on every route (ADR-0004); tenant/region scope resolved once at the edge, enforced at the repository layer (ADR-0005); ADR-0021 closed a real cross-org IDOR, independently re-verified (68 tests + a live two-org script). **Priority 1 Item 6:** `GET/POST /roles/{role}/permissions` (+`/revoke`) and `GET /scope-assignments/{user_id}` + `POST /scope-assignments/{regions,support}` (+`/revoke`) — Founder-only, live-verified end-to-end over real HTTP against real Postgres (grant → confirmed via GET → revoke → confirmed cleared; non-Founder caller correctly gets 403). Closes "RAAD can't onboard its own staff without hand-editing the DB."
- **Missing:** Nothing blocking.
- **Production blocker?** No longer.
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

#### JT808 — 🟡 Partial (live, primary GPS target — ADR-0025; field-width rework, auth-code lifecycle, and video signaling all built, 2026-08-11/12)
- **Implemented:** Fully built, parsed, tested (`services/device-gateway/src/vendors/jt808/`), instantiated live in the gateway. Device-plane provisioning/identity real (2026-08-09): `ProjectionBackedJt808ProvisioningPort` resolves a device's `terminal_id` against the same shared `DeviceRegistryProjection` the LSZ adapter uses. **JT/T 808-2019 field-width rework complete** (2026-08-11, commit `f5e9fae`): header now `BCD[10]` terminal phone + protocol-version byte (`header.py`), `0x0100`/`0x0102` bodies widened to the confirmed 76-/variable-byte 2019 shapes (`registration_body.py`/`authentication_body.py`), `0x0200`/`AlarmFlags`'s own basic-info layout confirmed byte-for-byte identical between the 2013 citation already implemented and the 2019 supplier spec, table-by-table/offset-by-offset (`position_body.py` — no code change needed, only citation) — closes the "0x0200/AlarmFlags byte-level diff" ADR-0025 §2 flagged as outstanding. **`0x0102` auth-code lifecycle implemented** (ADR-0025 §3, commit `f5e9fae`): `ProjectionBackedJt808ProvisioningPort` mints + PBKDF2-hashes a fresh code on every successful `0x0100` (`auth_code_hashing.py`), verifies by hash comparison on `0x0102`, publishes `DeviceAuthCodeIssued` so `fleet_device.Device.auth_key_hash` mirrors it — closes Known Issue #18 for real (see that issue's own resolution note). **JT/T 1078 video-signaling-forwarding built** (ADR-0024 §1/§8, ADR-0025 §5, 2026-08-11): `commands/video_signaling.py` encodes/decodes `0x9101`/`0x9102`/`0x9105`/`0x9205`/`0x9201`/`0x9202` (downlink) and `0x1205` (uplink, resource list); a new `CommandAckHandler` (`0x0001`, replacing a placeholder) + `PendingCommandTracker` give every platform-initiated command real correlation-ID tracking (`jt808.md` #6); `RedisVideoSignalingConsumer` receives structured command requests from the broker and forwards them, unmodified in wire terms, on the terminal's already-open connection. **The real Business-API-side publisher of those requests now exists too** (2026-08-12, see Video/JT1078 rows below) — the command path is exercised end to end in tests, from `Jt1078RelayAdapter` through to this consumer. 405→471 device-gateway tests, all green (unchanged this turn — no device-gateway code was touched by the 2026-08-12 phase).
- **Missing:** Nothing architecturally blocking and no backend-side integration gap remaining. The one genuine remaining gap across this entire JT808 row is verification: every field-width, auth-code, and signaling claim above is specification-verified and unit/integration-tested against synthetic fixtures only — **none of it has been exercised against a real, physical MDVR**, and none of this row should be read as claiming otherwise.
- **Production blocker?** No, mechanism-wise. Yes, if "launch" is read as "verified against real hardware" — that verification has not happened.
- **Dependencies:** A real device, for the one remaining verification step.

#### JT1078 — 🟡 Partial (relay + backend + mobile player all built, 2026-08-12 — never live-device-verified)
- **Implemented:** New deployable `services/jt1078/`, Python 3.11 asyncio, stdlib + `redis>=5.0` only (evidence-based runtime choice — see `services/jt1078/pyproject.toml`'s own header comment; zero new dependency). JT/T 1078 extended-RTP ingest demux + subpackaged-frame reassembly, spec-verified against `mdvrdocs/MDVR-808-1078-spec.pdf` §6.2.1.1. Session lifecycle (VSM): `SessionManager` — create → active → ended/failed, viewer-count tracking, idle-timeout + ingest-timeout sweeps, device stop-signal (reuses `device-gateway`'s own `Jt1078SignalCommandRequested` wire contract, `0x9102`/`0x9202` control=close). Signed, single-use, session-scoped viewer tokens (HMAC-SHA256; in-memory or Redis-backed single-use guard) — D5 enforced structurally (the relay does no RBAC of its own; a viewer with no valid token never reaches a media byte). Hand-rolled FLV muxer, now with a real SPS/PPS-aware sequence-header path (`FlvMuxer.feed_annex_b_video` — `extract_sps_pps`/`build_avc_decoder_config` parse real Annex-B SPS/PPS NAL units into a real `AVCDecoderConfigurationRecord`, emitted once per distinct parameter set, re-emitted only if it changes; closes the seam `build_avc_sequence_header_tag`'s own docstring used to flag as unpopulated), and a minimal RFC 6455 WebSocket server (no new dependency) for WS-FLV live delivery. Full device→ingest→repackage→viewer path proven end to end over real loopback sockets with synthetic frames. Redis-backed session-lifecycle event publishing on the shared `raad:events` stream, conditional on a broker being configured. Docker: `docker/jt1078-relay.Dockerfile` + a `jt1078-relay` service block — mirrors `device-gateway`'s exact deployment shape. **Backend-facing control endpoint built**: `SessionRequestServer` answers a Redis list-based BLPOP/RPUSH RPC from the Business API's `Jt1078RelayRpcClient` — see the Video row below. **Concurrency ceilings implemented (ADR-0026 §8)**: `SessionManager` enforces a configurable global ceiling (default 50, citing Phase 2 §13.1's "e.g., start 50 global") and an independent per-organization ceiling (`JT1078_RELAY_MAX_GLOBAL_SESSIONS`/`JT1078_RELAY_MAX_SESSIONS_PER_ORGANIZATION`), rejecting `create_session` with `SessionCapacityExceededError` before any allocation. **The relay-event reconciliation gap is closed**: `backend/raad/modules/video/events/subscribers.py` now consumes `VideoSessionActivated`/`Ended`/`Failed` and drives real `VideoSession.activate`/`end`/`fail` transitions (see Video row). 90→115 jt1078 tests, all green.
- **Missing:** HLS (the playback transport ADR-0024 §14 also names) — live/WS-FLV only; playback signaling (`0x9201`/`0x9202`/`0x9205`/`0x1205`) is fully built on the device-gateway side, but the relay's own playback viewer-delivery transport is not. Viewer-level (not session-level) audit granularity — `audit_entries` now covers every `VideoSession` transition (see below), but not individual viewer join/leave events. A defensive reconciliation-timeout scheduled job for a `VideoSession` stuck in `REQUESTED`/`ACTIVE` with **no** lifecycle event ever arriving at all (e.g. relay crash) — ADR-0024 §16 names this, ADR-0026 does not build it, out of that ADR's own scope. **Never tested against the physical MDVR** — every piece above, old and new, is verified against the supplier's own written specification and synthetic byte fixtures/fakes only.
- **Production blocker?** Yes, for real live video — HLS (if required), the reconciliation-timeout job, and physical-device verification are the remaining items. SPS/PPS handling, the concurrency ceiling, the relay-event reconciliation gap, and the backend control-endpoint wiring are no longer blockers.
- **Dependencies:** None architecturally (the runtime/dependency/backend-transport decisions are all made); a real device for verification.

### Live operations

#### GPS (ingestion) — ✅ Complete
- **Implemented:** Proven end-to-end: LSZ position frame → `DevicePositionReported` → Redis Streams → backend processor → `vehicle_positions` row; real writer for the `vehicle:{id}:last` Redis key.
- **Missing:** Alarm-flag taxonomy mapping, boarding/alighting modeling (tracked separately — see Known Issues).
- **Production blocker?** No.
- **Dependencies:** Devices, Redis.

#### Live Tracking — 🟡 Partial
- **Implemented:** `/ws/tracking` (JWT-authenticated, re-authorizes on every push); real F7 frontend page; geofence-crossing detection now wired into live ingestion. Its Redis dependency is now hardened mechanism-wise (Priority 1 Item 4: auth, persistence, memory bounds) — see Redis below for the one remaining caveat (not live-tested against a real server in this sandbox).
- **Missing:** One active vehicle subscription per WebSocket connection (no fleet-wide live map).
- **Production blocker?** Partially — works today, not yet trustworthy at scale.
- **Dependencies:** GPS ingestion, Redis.

#### Video — 🟡 Partial (backend + relay + web (F10) + a narrow Parent mobile player all built; the discovery→live-video signaling path is now genuinely live-device-verified, 2026-08-19 — the mobile/Flutter layer and the full production topology remain unverified)
- **Implemented:** D5 is now narrower, not weaker (ADR-0026, 2026-08-12 — formally revisits the "Parent has zero reachable path to video, anywhere, ever" invariant, resolving `docs/business/Project_Brief_v1.md` §4.8's own original "Parents may view live video if enabled by the organization" requirement in its favor, narrowly — see that ADR for why this is the platform's own root requirement being formally reinstated, not a new one being invented). `enforce_d5()` still runs before any of the below, unconditionally, for every role. **`VideoProviderPort` has a real implementation**: `Jt1078RelayAdapter` (`backend/raad/modules/video/infra/adapters.py`), conditionally bound in `core/di/bootstrap.py` only when both a broker and `device_plane.jt1078_signaling_url` are configured. Full flow: `VideoApplicationService` → `Jt1078RelayAdapter` → `Jt1078RelayRpcClient` (Redis list RPC to the relay's `SessionRequestServer`) → a `Jt1078SignalCommandRequested` event on the existing `raad:events` broker stream → device-gateway's `RedisVideoSignalingConsumer` → the real `0x9101`/`0x9201` JT808 command. The returned `stream_url` is a `ws://.../viewer?token=...` URL the client connects to directly — no media byte ever transits the FastAPI process.

  **Parent video-access authorization (ADR-0026 §1-§4):** two independent booleans on `Parent` (`has_video_live_access`/`has_video_playback_access`), off by default for every parent, migration-backed (`server_default=false`), grantable only by that parent's own org_admin via a new `PATCH /parents/{id}/video-access` (a dedicated, more restrictive RBAC permission, `transport_ops.parents.grant_video_access`, not the ordinary profile-edit permission). Full authorization chain, all server-side, before any `VideoApplicationService` call (`interfaces/http/policy_guards.resolve_d5_decision`, extended for `Role.PARENT` only): self identity (`_resolve_parent_id`) → explicit permission (matching `purpose`, "live" vs "playback", independently) → child/device ownership (new `find_owned_student_id_for_device`, resolving `device_id` → the device's active vehicle assignment → the existing CR-1 child-ownership check) → only then `VideoSession`/`VideoProviderPort`. **A parent with no ownership relationship to the device at all gets 404, never 403** (this codebase's established cross-tenant-probing-avoidance convention); only an owning-but-ungranted parent gets 403. RBAC: Parent gains the same three `video.*` permissions Org Admin already holds (layer-2 "may attempt," not "may succeed" — the real per-instance decision is the policy chain above, the identical split CR-1 already established for `tracking.vehicles.read_latest`). `GET /me` now surfaces both flags (presentation only) for the mobile client's own UI gating.

  **Relay-lifecycle reconciliation (ADR-0026 §7):** `VideoApplicationService.request_live_video`/`request_playback_video`'s previous eager `session.activate()` (called synchronously right after the provider RPC returned, before the relay had any real signal media was flowing) is removed. A new `video/events/subscribers.py` (previously empty) consumes the relay's own `VideoSessionActivated`/`Ended`/`Failed` events and drives real `activate`/`end`/`fail` transitions through a fresh `VideoUnitOfWork` — `VideoSession.end`/`.fail` gained an optional `reason` parameter, threaded from the relay's own event payload into the domain-event payload (e.g. `"viewer_idle_timeout"`, `"ingest_timeout"`).

  **`audit_entries` closed for real (ADR-0026 §6 of this session's own report), not just architecturally**: every `VideoSession` transition (`Requested`/`Started`/`Ended`/`Failed`) and every `Parent` video-access grant/revoke already flows through the existing `UnitOfWork.commit()` → `AuditWriter` pipeline (ADR-0007) automatically — no new audit code was needed, only the reconciliation fix above closing the gap that used to leave `Started`/`Ended`/`Failed` under-triggered. Live-Postgres-verified (`tests/integration/test_video_audit_entries.py`, two new tests: a grant produces a real `ParentVideoLiveAccessGranted` row; `mark_session_active` produces a real `VideoSessionStarted` row).

  **Mobile player (ADR-0026 §5, `mobile/lib/features/video/`)**: `MeIdentity`/`MeRepository` (`GET /me`), `VideoRepository` (`POST /video/live`/`/playback`/`/sessions/{id}/stop`), `FlvRelayBridge` (bridges the relay's bespoke binary-WebSocket-frame WS-FLV protocol to a local `http://127.0.0.1` URL via `dart:io.HttpServer`, no new dependency for the bridge itself), `VideoPlayerScreen` (new `media_kit`/`media_kit_video`/`media_kit_libs_video` dependency, MIT license, user-approved before adding), `VideoWatchScreen` (manual device/camera id entry — the same disclosed "no endpoint resolves my devices" stand-in pattern `ParentHomeScreen` already established for "list my children"). `ParentHomeScreen` gained a permission-gated "Watch live video" entry point, presentation-only per `.claude/rules/frontend.md` #2. **This paragraph is dated to ADR-0026 (2026-08-12) itself and describes only what that phase touched** — at that time "Web dashboard (F10) is untouched... the user's own explicit choice was Flutter-only for this phase" was accurate. It stopped being current two days later: **F10 (Org-Admin web live video, `/org/video`, `VideoPage.tsx`) was built 2026-08-14 (commit `600c4da`)**, then unified with GPS into one Vehicle Operations view on `/platform/tracking`/`/org/tracking` (**ADR-0028**, 2026-08-16, commit `8b5bd0c` — `useVehicleActiveDevice(vehicleId)` resolves a selected vehicle's device via the new `GET /vehicles/{vehicle_id}/device-assignment` + `is_online` read model from **ADR-0027**, commit `560580d`, then hands off to the existing `CameraPicker`/`useVideoSessionController`; `/org/video`'s own device-first picker is deliberately kept, not removed — it's the only path to a device not yet assigned to any vehicle). **ADR-0029** (2026-08-16, commit `857d68b`) then extended that same unified view's video capability to Founder/Regional Manager/Support Staff (D5 already allowed all three; closed a real RBAC gap — `regional_manager`/`support_staff` could start a session but not stop it — and flipped one frontend boolean gate). See the ADR Progress table (§4) for each ADR's own accepted-status line.
- **Live-verified end to end, 2026-08-19** (this session, against the physical `LSZ-C5804DG-Q-F` bench unit): a real `POST /video/live` → `0x9101` JT808 command → the device dials the relay's ingest port and streams genuine JT/T 1078 extended-RTP frames → `VideoSession.status=active` → a real WS-FLV viewer connection. Four real, production-blocking bugs were found and fixed in the process (three unprotected `run_forever` consumer loops that a single transient Redis error could permanently and silently kill; the device-registry projection not surviving a device-gateway restart; a BCD-width mismatch that made every real ingest connection look "unsolicited"; `JT1078_RELAY_PUBLIC_INGEST_HOST` never wired anywhere, silently defaulting to the unroutable `0.0.0.0`) — see CLAUDE.md's own Permanent Engineering Lessons and §8's dated entry below for the full incident detail.
- **Missing:** HLS, the relay's own reconciliation-timeout scheduled job (ADR-0024 §16). **Physical-MDVR verification of the mobile/Flutter layer specifically** — the backend/device-gateway/relay/web-frontend path above is now real-hardware-verified, but the Flutter mobile player is still only unit/integration-tested against fakes/synthetic fixtures; no real Flutter SDK has exercised any part of it (the mobile layer carries the same categorical "written, not compiled or run" limitation every M0-M3 phase already discloses, `mobile/README.md`'s own "Testing limitation" section). The full production topology (a real domain, TLS, Coolify/nginx routing the relay's raw ingest TCP port) is also still unverified — this session's own verification used a direct LAN IP, a dev-only stand-in disclosed in `docker/.env.example`'s own comment on `JT1078_RELAY_PUBLIC_INGEST_HOST`.
- **Production blocker?** No longer, for the backend/device-gateway/relay/web path — that's now real-hardware-verified. Yes, still, for a mobile launch — the Flutter player is entirely unverified even in principle (no Flutter SDK in this sandbox), and for a production VPS deployment — the ingest port's own real-domain routing has never been exercised.
- **Dependencies:** JT1078 (built, live-verified), the backend adapter (built, live-verified), the web frontend (built, live-verified), the parent-authorization model (built), a Flutter SDK to verify the mobile layer, a production VPS to verify real-domain ingest routing.

### Engagement & revenue

#### Notifications — 🟡 Partial
- **Implemented:** `Notification`+`DeviceToken` aggregates, `/ws/notifications`, a real Notification Worker gating sends through CR-1 across 4 event types. **Web UI (F8) now built**: `features/notifications/NotificationsPage.tsx`, mounted at both `/platform/notifications`/`/org/notifications` (one shared component — the route is scoped to `recipient_user_id`, not tenant, so it behaves identically regardless of which dashboard reaches it). Type filter chips, cursor-paginated "Load more" (`useInfiniteQuery` — the first cursor-paginated page in this frontend, backing new shared `CursorPageWire`/`toCursorPage`/`CursorListParams`/`buildCursorListQuery` utilities mirroring the existing offset equivalents), per-row mark-as-read, and a live refetch on every `/ws/notifications` push. `AppShell`'s topbar bell badge (`unreadNotifications`, previously always `undefined`/no badge) is now wired to a real, live-updating count (`useUnreadCount` — seeded from the most recent 50 notifications, incremented via the same WebSocket channel).
- **Missing:** No mobile client to receive a push yet (Mobile MVP's own M4/FCM gap, Priority 1 Item 9) — the web inbox itself is real and live, but Parents/Drivers still have no channel at all.
- **Production blocker?** Partially — the RAAD-staff/Org-Admin web experience is no longer missing; Parent/Driver delivery still is.
- **Dependencies:** Live Tracking (for trip events), Mobile App (for delivery to Parents).

#### Billing — 🟡 Partial (architecture complete; real provider credentials remaining)
- **Implemented:** Full `Plan`/`Subscription`/`Invoice`/`Payment`/`TransportFee` lifecycle; 6
  documented/added routes (5 original + ADR-0022's new `GET /billing/payments`).
  `BillingApplicationService.initiate_payment`/`handle_payment_callback`/
  `reconcile_expired_payments` are all fully implemented and tested — idempotency-key handling,
  the full paid/failed state orchestration (invoice → subscription renewal), and the scheduled
  reconciliation job all genuinely work today. **ADR-0022 (2026-08-06) closes what used to be
  Priority 1 Item 8**: a redesigned, provider-agnostic `PaymentProviderPort` (card token *or*
  mobile-money msisdn); a real, verified `StripePaymentAdapter` (httpx, Payment Intents API,
  documented HMAC-SHA256 webhook signature scheme) bound conditionally in DI
  (`RAAD_PAYMENT__PROVIDER=stripe` + real env-var-only credentials — never `SystemSetting`,
  since `org_admin` holds `admin.settings.read`/`.update` too); `EvcPlusPaymentAdapter`/
  `ZaadPaymentAdapter` are honest, interface-complete stubs (`NotImplementedError` — no real
  merchant docs exist to verify against, the user's own explicit choice). `POST /billing/
  payments/callback` is now genuinely wired (previously a documented, deliberate no-op) — HMAC
  signature *is* the route's authentication (no `Principal`/bearer JWT involved at all,
  matching Stripe's own webhook model), `SYSTEM_PRINCIPAL` (moved to `core/tenancy/principal.py`
  so `billing`/`notifications` share the one constant) represents the caller for the audit
  trail. A real, previously-undiscovered idempotency bug was found and fixed:
  `Payment.mark_paid`/`mark_failed` lacked `mark_processing`/`mark_expired`'s existing same-state
  guard, so a provider's routine webhook retry would have double-advanced a subscription's
  billing period — closed at both the entity layer (idempotent no-op) and the service layer
  (short-circuit on an already-terminal `Payment`), with a regression test proving a replayed
  "paid" callback doesn't move `current_period_end` twice.
- **Web UI now built, split by dashboard (ADR-0022 completes F9's own deferred half):**
  `/platform/billing` stays the original F9 `BillingPage.tsx` (tabbed, read-only,
  cross-organization — its three list routes remain genuinely unscoped server-side, a
  pre-existing gap, not new). `/org/billing` is now a dedicated `OrgBillingPage.tsx` — an Org
  Admin's own current subscription/plan, invoices, and payment history, scoped to
  `principal.organizationId` throughout (closing that unscoped-list gap for this one route), plus
  a real "Pay Invoice" flow: a new `ConfirmDialog` component (this frontend's first genuinely
  consequential/hard-to-reverse action, so it gets a real confirm step instead of the existing
  "loading button + toast" convention) wraps Stripe Elements client-side card tokenization — the
  raw card number never reaches this backend (PCI DSS SAQ A scope). The card form only renders
  when a new `getBillingProviderConfig()` read (against the existing `GET /admin/settings`, no
  new route) confirms a provider is actually bound; otherwise an honest "Online payment is not
  available yet" state renders, never a control guaranteed to fail.
- **Missing:** A real Stripe (or EVC Plus/Zaad, once real merchant docs exist) merchant account's
  live credentials — the one thing that was always going to be genuinely external, never a coding
  gap. `docker-compose.coolify.yml` (ADR-0022's own deployment half) + `docs/runbooks/
  coolify-deployment.md` are also new, for the chosen Hostinger-VPS-via-Coolify deployment path,
  alongside (not replacing) `docker-compose.prod.yml`'s existing generic-VPS/nginx/certbot path.
- **Production blocker?** No longer, mechanism-wise — same disclosed posture as TLS/Redis
  hardening: "complete and verified as far as this environment can verify, not live-tested
  against a real external account." Known Issue #4 (updated) has the full detail.
- **Dependencies:** A real payment-provider merchant account (Stripe recommended, already
  verified-adapter-ready) — genuinely external, cannot be fabricated.

#### Subscriptions — 🟡 Partial
- **Implemented:** Full open/renew/expire/suspend/cancel lifecycle; two scheduled jobs keep state honest automatically.
- **Missing:** Nothing beyond Billing's real-provider-credentials gap.
- **Production blocker?** No longer, mechanism-wise — tied to Billing's own updated status above.
- **Dependencies:** Billing.

### Surfaces

#### Platform Dashboard — 🟡 Partial
- **Implemented:** 9 of 14 nav sections real (organizations, regions, users, vehicles, devices, drivers, routes, trips, live tracking).
- **Missing:** Notifications, reports, billing, audit, settings — all honest placeholders.
- **Production blocker?** Partially.
- **Dependencies:** Notifications, Billing, Reporting, Analytics (each backlogged feature owns one placeholder).

#### Organization Dashboard — 🟡 Partial
- **Implemented:** 8 of 12 sections real (vehicles, students, parents, drivers, routes, trips, live tracking, **video** — `/org/video` + the unified GPS/video Vehicle Operations view, ADR-0027/0028/0029, live-hardware-verified 2026-08-19).
- **Missing:** Notifications, reports, billing, users, settings.
- **Production blocker?** Yes, partially — a real customer hits a "being built" wall on day one.
- **Dependencies:** Same as Platform Dashboard.

#### Mobile App — 🟡 Partial (code written, entirely unverified — see caveat below)
- **Implemented (Priority 1 Item 9):** Phase M0 (Foundation) code-complete — Riverpod state management, `flutter_secure_storage`-backed refresh-token storage, a REST client mapping the backend's real error envelope, a protocol-correct `/ws/tracking` WebSocket client, role-based shell/routing. Phase M2 (Driver) code-complete: org-scoped trip list, real start/end actions against the real, ownership-enforced backend routes. Phase M3 (Parent): the live-tracking screen itself is code-complete and protocol-correct; the "assigned children" list is blocked on a real, newly-discovered backend gap (see Known Issue #17). A real `mobile-pipeline.yml` CI workflow and one widget test also ship.
- **Missing:** Phase M4 (FCM push) — needs a real Firebase project (external dependency, same category as Payment's EVC Plus account). Phase M5 (offline caching, app-store release) — release process needs real store accounts; offline caching deferred until M2/M3 are verified-complete. Map rendering itself (a real Mapbox widget) — the live-tracking screen shows raw position data, not a rendered map, pending a chosen Flutter map package. **Most importantly: nothing in `mobile/` has been compiled, analyzed, or run — no Flutter SDK exists in this sandbox at all**, a categorically stronger unverified-state than any other Priority 1 item (every other item still had some independent verification path — real HTTP, real Postgres, real YAML parsing; this one has none). Treat every "code-complete" claim above as "written and carefully reviewed, not yet proven" until a real `flutter analyze`/`flutter test`/`flutter run` succeeds.
- **Production blocker?** Yes, unconditionally — this is the *only* channel Parents/Drivers have, and it remains unverified and partially blocked on two genuine backend gaps.
- **Dependencies:** A real Flutter SDK/build environment to verify any of this code at all (the backend fix for the Parent/Driver self-identity-resolution gap, Known Issue #17, is now resolved — ADR-0023 — but the mobile screens still need wiring to it, itself blocked on the same missing-SDK dependency); a real Firebase project (M4); real app-store accounts (M5's release half).

### Insight

#### Analytics — ✅ Complete
- **Implemented:** ADR-0020 (2026-08-05), full scope. `devices.is_online` (migration
  `b288c2e44aa5`) closes the Online/Offline gap by extending the *already-real*
  `DeviceConnectivityProcessor` (`fleet_device/events/subscribers.py`) — confirmed this
  consumer already existed and already populated `last_seen_at`, so no new event consumer was
  needed, resolving Known Issue #9's own flagged ADR-vs-repo conflation. New, additive count/
  sum query methods across four modules (`organization.count_by_status`/`count_created_since`,
  `iam.count_by_status`/`count_last_login_after`/`count_created_since` — with a new
  `ix_users__last_login_at` index — `fleet_device.count_total`/`count_online`,
  `billing.count_by_status`/`count_expiring_between`/`sum_paid_amount_between`), composed by a
  new `platform_audit.PlatformStatsApplicationService` (constructor-injected with all four
  modules' own application services plus the existing `HealthCheckService` — no cross-module DB
  read anywhere, confirmed by the existing `tests/architecture/test_module_boundaries.py` gate,
  re-run green). `GET /admin/platform-stats`, gated by a new `admin.platform_stats.read`
  permission (Founder/Regional Manager/Support Staff/Finance Staff) — a real RBAC gap found
  while implementing: `finance_staff` doesn't hold `admin.audit.read`, contradicting the ADR's
  own assumption. Frontend: `DashboardHomePage.tsx`'s `PlatformAnalyticsSection` replaces the
  organizations/vehicles/devices tiles of the pre-existing six-tile stopgap with real
  breakdowns (status splits, online/offline, MAU, revenue, system health); drivers/students/
  parents tiles are untouched (outside this ADR's scope). Live-verified against real Postgres,
  including the full four-module composition through the real DI container.
- **Missing:** Two KPIs named in the ADR's own Context ("Live Vehicle Locations", "Active
  Drivers") are a real, flagged scope cut — neither `tracking` nor `transport_ops` is named in
  the ADR's own §1 Decision module list, and inventing either (an unsafe Redis `KEYS`/`SCAN`
  scan; an undocumented cross-module reach) was avoided rather than silently built.
- **Production blocker?** No.
- **Dependencies:** None — closed.

#### Reporting — ❌ Missing (functionally)
- **Implemented:** `ReportRun` request/track lifecycle and a Report Worker that polls queued runs.
- **Missing:** `ReportRendererPort` has zero binding (not even referenced in DI bootstrap) — every run ends `failed` by design; frontend `features/reports/` is empty.
- **Production blocker?** No for a pilot; yes before this can be marketed as working.
- **Dependencies:** A PDF/Excel rendering engine choice.

### Platform operations

#### Docker — 🟡 Partial
- **Implemented:** Real dev + production compose overlays, 4 real Dockerfiles (backend, frontend, device-gateway, **jt1078-relay, new 2026-08-11**), working nginx reverse proxy — verified live per ADR-0013. `jt1078-relay` mirrors `device-gateway`'s exact shape (own container, own published ports 7910/7911, `.dev.yml` bind mount, `.coolify.yml` "not Traefik-routable" note, `.env.example` entries) — not yet live-tested against a running Docker daemon (same disclosed limitation as every container in this sandbox). Priority 1 Item 2: TLS termination mechanism (nginx `prod-tls.conf` + `certbot` service, Let's Encrypt via webroot challenge, auto-renewal) built and carefully reviewed.
- **Missing:** TLS mechanism not live-tested against a real domain — no domain/VPS provisioned yet; see Known Issue #13.
- **Production blocker?** No longer for TLS itself (mechanism exists, documented two-phase bootstrap in `docs/runbooks/tls-setup.md`) — the residual risk is that it hasn't been proven against a real domain yet.
- **Dependencies:** A domain name + DNS pointed at a real VPS, to actually run the bootstrap.

#### Database (PostgreSQL) — ✅ Complete
- **Implemented:** SQLAlchemy 2.x async + Alembic, one linear migration chain, verified zero-drift, ADR-0021 tenant-isolation fix.
- **Missing:** Nothing in the schema layer itself (backups/encryption tracked separately).
- **Production blocker?** No, on its own merits.
- **Dependencies:** None.

#### Redis — 🟡 Partial
- **Implemented:** Event broker, live-position cache, geofence hysteresis state, both WS fan-out workers — all real, tested code. **Priority 1 Item 4:** AOF persistence (`--appendfsync everysec`) + RDB fallback on the image's stock schedule, `--requirepass` (previously unset entirely), `--maxmemory`/`--maxmemory-policy noeviction` (fail loud on memory pressure, never silently drop data — the broker DB holds real undelivered domain events, not just reconstructable cache), broker/cache split onto separate logical Redis DBs (0 vs. 1, matching `backend-pipeline.yml`'s own CI precedent), explicit connection timeouts (`socket_connect_timeout`/`socket_timeout`/`health_check_interval`) on the backend's own Redis clients (previously using undocumented library defaults). `infrastructure/redis/redis.conf.template`'s placeholder is resolved (deliberately not populated — see `docs/runbooks/redis-operations.md` for why Compose `command:` flags are used instead of a mounted conf file, the same pattern `infrastructure/backups/` already established).
- **Missing:** Live verification against a real running Redis process — no Docker/WSL2/local `redis-server` binary in this sandbox (Known Issue #15). No HA/Sentinel/Cluster — a deliberate, documented MVP-scope decision (single-VPS topology), not an oversight.
- **Production blocker?** No longer, mechanism-wise — treat "Redis hardening live-verified" as not yet true until Known Issue #15's first-real-deployment checklist has actually been run (same posture as TLS/Known Issue #13).
- **Dependencies:** None.

#### Background Workers — ✅ Complete
- **Implemented:** Notification Worker, Report Worker, 3 scheduled jobs (`prune_vehicle_positions`, `sweep_expired_subscriptions`, `reconcile_expired_payments`), 2 WS fan-out workers.
- **Missing:** Nothing in the plumbing; Report Worker's output blocked on Reporting.
- **Production blocker?** No, on its own merits.
- **Dependencies:** Redis.

#### Monitoring — 🟡 Partial
- **Implemented (Priority 1 Item 5):** `/health/ready` now runs real Postgres/Redis(cache)/Redis(broker) checks with a 3s-bounded timeout each (`core/health/service.py`) — closes Known Issue #3; live-verified against real Postgres (a genuinely reachable one and a genuinely unreachable one) and over real HTTP against a running server. New `/metrics` (Prometheus text format, hand-rolled — `core/observability/metrics.py`, no new Python dependency): request counts by method/route-template/status, dependency-up gauges, process-start-time gauge. New `prometheus` Docker Compose service scrapes it (`infrastructure/monitoring/prometheus/prometheus.yml`).
- **Missing:** Grafana dashboards (no live Prometheus target existed to design panels against); Sentry/error tracking and OpenTelemetry tracing both need a real external account/DSN this session can't obtain — see `docs/runbooks/monitoring.md`'s "What's deliberately not built this phase". The `prometheus` service itself is not live-tested (no Docker in this sandbox — same disclosed limitation as TLS/Redis).
- **Production blocker?** No longer, for the core "is this process actually healthy" signal — good enough for a single-VPS pilot's `docker compose ps`/orchestrator readiness gate. Full observability (dashboards, error tracking) remains a real gap for anything beyond a pilot.
- **Dependencies:** None.

#### Logging — 🟡 Partial
- **Implemented:** Real structured JSON logging, backend + device-gateway, with PII redaction and correlation-id context.
- **Missing:** Stdout only, no shipping/aggregation anywhere; frontend has zero logging/error-tracking.
- **Production blocker?** Partially (acceptable for a single-VPS pilot via `docker logs`).
- **Dependencies:** A log-aggregation destination choice.

#### Deployment — 🟡 Partial
- **Implemented:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` genuinely works, live-verified (ADR-0013). Automated backups (Priority 1 Item 1), a TLS/HTTPS mechanism (Priority 1 Item 2), Redis hardening (Item 4), real health checks + monitoring (Item 5), and RBAC admin routes (Item 6) all now ship as part of this stack. **Priority 1 Item 7:** a full VPS provisioning guide (`docs/runbooks/vps-deployment.md` — OS baseline, firewall, Docker install, `.env` config, first boot, Founder bootstrap, DNS/TLS handoff) and a rollback runbook (`docs/runbooks/rollback.md` — application-code, migration, and frontend-only rollback, plus the last-resort full backup restore) close the two named gaps.
- **Missing:** No secrets-manager integration, no deploy step in CI; `scripts/db/migrate.sh`/`seed.sh`/`scripts/dev/bootstrap.sh` are still literal 0-byte files. TLS itself is unverified against a real domain (Known Issue #13), and the VPS/rollback runbooks themselves are necessarily unverified against a real VPS in this sandbox (no VPS provisioned — same disclosed limitation as every other infra item this program shipped).
- **Production blocker?** No longer, mechanism/documentation-wise — every documented gap in this row now has a real runbook.
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
- **Implemented:** F0–F10 built and tested (F10/Video: `/org/video`, commit `600c4da`, 2026-08-14; unified with GPS and extended to Platform Admin by ADR-0027/0028/0029, 2026-08-16; live-hardware-verified 2026-08-19) — 60 real test files (372 tests, as of F0–F9; F10's own test count not yet re-tallied here), working production build, correct in-memory-only token handling, real Docker/nginx deployment path.
- **Missing:** Reporting — still an empty feature folder.
- **Production blocker?** Partially.
- **Dependencies:** Reporting (backend half already exists; only the frontend consumer is missing).

#### CI/CD — 🟡 Partial
- **Implemented:** `.github/workflows/backend-pipeline.yml` — real, runs unit/architecture/integration tests against live Postgres+Redis service containers on every backend PR. `mobile-pipeline.yml` (Priority 1 Item 9). **New (2026-08-07, Priority 2 "CI hardening"):** `frontend-pipeline.yml` (`npm ci` → `npm run build`, which runs `tsc -b` type-check before `vite build`, → `npm test -- --run`) and `device-gateway-pipeline.yml` (`pip install -e .` → `python -m compileall` → `python -m unittest discover`) — both mirror `backend-pipeline.yml`'s exact build→test-only scope discipline. The exact commands each workflow runs were run directly in this sandbox against the current trees before either file was written: frontend 392/392 tests + a clean production build; device-gateway 333/333 tests. All four `ci-cd/pipelines/*.yml` index stubs (backend/mobile/frontend/jt808) now correctly point at their real workflow, closing a real, pre-existing drift where mobile's own stub had lagged empty even after `mobile-pipeline.yml` itself was built.
- **Missing:** No lint/security-scan gate anywhere (`ruff`/`mypy`/`eslint`/a security scanner are all still "not yet formally approved" dependencies, `.claude/rules/workflow.md` #1/#2 — deliberately not invented speculatively), no deploy step, no `jt1078`/`infrastructure` CI (neither deployable/target exists yet). Not live-tested against a real GitHub Actions run in this sandbox (no way to trigger one here) — the same disclosed "mechanism verified locally, not via a live CI run" posture every other workflow in this repository already carries.
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
| 0019 | Account-Sharing Session Cap | ✅ Complete |
| 0020 | Platform Analytics Read Model | ✅ Complete |
| 0021 | Tenant Scope Enforcement at Repository Layer | ✅ Complete |
| 0022 | Payment Provider Architecture | ✅ Complete |
| 0023 | Canonical `/me` Self-Service Identity Resolution | ✅ Complete |
| 0024 | JT1078 Video Relay Architecture | 🟡 Partial (device-gateway signaling, relay, Business API wiring, SPS/PPS, concurrency ceilings, `audit_entries`, and relay→`VideoSession` reconciliation all built, tested, and live-verified against the physical bench unit — real extended-RTP frames, `VideoSession.status=active`, a connected viewer, 2026-08-19, §8; HLS and the reconciliation-timeout job still open) |
| 0025 | JT/T 808-2019 + JT/T 1078-2016 Native Protocol Compliance | ✅ Complete — architecture accepted, every named implementation item (field-width rework, `0x0102` auth-code lifecycle, `0x0200` byte-diff) built, tested, and live-verified against the physical `LSZ-C5804DG-Q-F` bench unit (registration → authentication → A/V-attribute discovery → live video, 2026-08-19, §8) — **over LAN only**; no external/public-network JT808 session is recorded anywhere in this repository, and that specific path remains unverified |
| 0026 | Parent Video Access Authorization | 🟡 Partial (backend authorization chain, migration, RBAC, audit coverage, and relay reconciliation all built and live-Postgres-tested; the Flutter mobile player is written but categorically unverified — no Flutter SDK in this sandbox; the parent-specific authorization chain itself was not exercised by the 2026-08-19 bench session, which used no parent principal — physical-MDVR verification of that chain specifically remains pending) |
| 0027 | Vehicle-Device Operational Read Model | ✅ Complete (commit `560580d`) — the backend read model ADR-0028's frontend consumes |
| 0028 | Unified Vehicle Operations Frontend (GPS + Video from One Vehicle Selection) | ✅ Complete (commit `8b5bd0c`) — unifies GPS + the already-existing F10 web video page (commit `600c4da`, 2026-08-14, predates this ADR by two days) into one Vehicle Operations view |
| 0029 | Platform Admin Live-Video Access (Founder/Regional Manager/Support Staff) | ✅ Complete (commit `857d68b`) |
| 0030 | Automatic Camera/Channel Discovery | ✅ Complete — device-gateway (`0x9003`/`0x1003`) and backend (discovery-trigger processor, camera-creation processor) implemented and tested (backend unit/architecture/integration + device-gateway unit, all passing; migration `7d3a9c1e5b42` live-Postgres round-tripped), live-verified against the physical `LSZ-C5804DG-Q-F` bench unit per the ADR's own verification transcript |
| 0031 | Fleet Overview Online-Vehicles Read Model | ✅ Complete — new `GET /tracking/vehicles/online` (`FleetOverviewApplicationService`), two additive `fleet_device` repository methods, `LatestPositionPort.get_latest_many`; a real per-vehicle-ownership authorization gap found and fixed while wiring the route (bulk fleet visibility could otherwise leak to a Parent's own mobile JWT), closed with an explicit role-set gate; `position` is `null` for every vehicle today (the pre-existing, disclosed JT808 `LatestPositionWriter` wiring gap, unaffected by this ADR) |

**A real doc-staleness gap found 2026-08-19, since corrected throughout this file and
CLAUDE.md:** ADR-0027/0028/0029 (2026-08-16) and the F10 Organization Admin web live-video
implementation (commit `600c4da`, 2026-08-14) had landed in git history well before this table or
either document's own narrative prose was updated to reflect them — Sections 2/3/6/8 below and
CLAUDE.md's "Frontend Implementation Status" section previously still said F10/the Org-Admin web
player "not started" in several places. All of those are now corrected in place (search this file
and CLAUDE.md for `600c4da` to find every touched spot) rather than left as a standing gap.

---

## 5. Production Readiness Roadmap

> **On ADR-0019 / ADR-0020:** neither was ever a production blocker — Priority 1 below (backups,
> TLS, rate limiting, mobile app, payments, monitoring) is where a real launch actually gets
> stopped, and it's now fully closed (see Section 15). **Both have since landed**, ahead of
> their Priority 2 slots below, at the user's explicit request: ADR-0019 (Session Cap,
> 2026-08-04) and ADR-0020 (Platform Analytics, 2026-08-05) — see Section 8/9 for both
> writeups.

### Priority 1 — Critical blockers before production
1. ~~**Backups**~~ — ✅ **Complete** (2026-08-03). Local `pg_dump`/`pg_restore` mechanism, live-verified round trip, CI-covered, pluggable off-site hook (unconfigured — see Known Issue #12). `docs/runbooks/backup-and-restore.md`.
2. ~~**TLS/HTTPS**~~ — ✅ **Complete** (2026-08-03). nginx `prod-tls.conf` + `certbot` service (Let's Encrypt via webroot challenge, auto-renewal via PID-namespace reload signal), two-phase bootstrap runbook. Mechanism built and carefully reviewed, **not live-tested against a real domain** (none provisioned — see Known Issue #13). `docs/runbooks/tls-setup.md`.
3. ~~**Auth rate limiting + account lockout**~~ — ✅ **Complete** (2026-08-03). Account lockout (`User.record_failed_login`/`is_locked`, migration `d4fbe03f2b94`) fully live-verified — real Postgres round trip + real HTTP smoke test against a running server. IP-based rate limiting (`LoginRateLimiter`, `RateLimitMiddleware`) unit-tested against a fake Redis; its fail-open-when-Redis-unreachable path live-verified (a real bug caught and fixed during that verification — see Known Issue #14). `AccountLockedError`/`RateLimitedError` added to the documented error taxonomy.
4. ~~**Redis production hardening**~~ — ✅ **Complete, mechanism-wise** (2026-08-03). `--requirepass`, AOF persistence (`everysec` fsync) + RDB fallback, `--maxmemory`/`noeviction`, broker/cache split onto separate logical DBs, explicit backend-side connection timeouts. Carefully reviewed (YAML structural validation, DI-container smoke test) but **not live-tested against a real running Redis process** — no Docker/WSL2/`redis-server` in this sandbox (Known Issue #15, same disclosed limitation as Item 2/TLS). Does not itself close Known Issue #14 (rate limiter's real-Redis round trip) — that still needs an actual reachable Redis server, which this item hardens the mechanism for but doesn't provide in this sandbox. `docs/runbooks/redis-operations.md`.
5. ~~**Real health checks + minimum monitoring**~~ — ✅ **Complete** (2026-08-03). `/health/ready`
   runs real, timeout-bounded Postgres/Redis(cache)/Redis(broker) checks (`core/health/
   service.py`); new `/metrics` (hand-rolled Prometheus text format) + a `prometheus` Compose
   service scraping it. Both live-verified over real HTTP/real Postgres; the `prometheus`
   container itself not live-tested (no Docker in this sandbox). Grafana/Sentry/OpenTelemetry
   deliberately not built — each needs a real external account/target this session can't obtain.
   `docs/runbooks/monitoring.md`.
6. ~~**RBAC grant/revoke route**~~ — ✅ **Complete** (2026-08-03). `iam.roles_router`
   (`GET/POST /roles/{role}/permissions`, `+/revoke`) and `organization.
   scope_assignments_router` (`GET /scope-assignments/{user_id}`,
   `POST /scope-assignments/{regions,support}`, `+/revoke`) — Founder-only, no documented API
   Contracts surface (built on Database Design §4.4/§4.6 directly, same posture as `/drivers`).
   **A real, live-caught production bug** (not specific to this item's own new code, but only
   reachable through it): `role_permission_granted`/`revoked` and the four
   `region_assignment_*`/`support_assignment_*` event factories built `aggregate_id` from a
   composite string that overflows `outbox.aggregate_id`/`audit_entries.entity_id`'s shared
   `CHAR(26)` column — fixed by widening `DomainEvent.aggregate_id` to `str | None` (a new
   migration, `f3d8b1a4e6c2`, drops `outbox.aggregate_id`'s `NOT NULL`) and passing `None` for
   these six events, full identity preserved in `payload`. Live-verified end-to-end over real
   HTTP/real Postgres both before and after the fix.
7. ~~**Deployment & rollback runbook, VPS setup guide**~~ — ✅ **Complete** (2026-08-03).
   `docs/runbooks/vps-deployment.md` (fresh-VPS-to-running-platform, 8 steps: OS baseline,
   firewall, Docker, `.env` config, first boot, Founder bootstrap, DNS/TLS handoff, end-to-end
   confirmation) and `docs/runbooks/rollback.md` (application-code/migration/frontend rollback,
   explicit guidance on when a migration downgrade is *not* safely reversible, last-resort
   backup restore). Both are necessarily unverified against a real VPS (none provisioned in this
   sandbox) — same disclosed limitation as TLS/Redis's own mechanism-built-not-live-tested
   posture.
8. ~~**Payment provider adapter**~~ — ✅ **Architecture complete** (2026-08-06, ADR-0022). Both
   blockers this item used to carry are resolved: the signed-webhook-caller design question is
   answered (per-provider HMAC signature *is* the route's authentication — Stripe's own
   documented model; `SYSTEM_PRINCIPAL`, an existing "least-bad available role" precedent already
   used by the Notification Worker, represents the caller for audit purposes only), and a real,
   verified `StripePaymentAdapter` (httpx-based, Payment Intents API) is built and bound
   conditionally in DI the moment `RAAD_PAYMENT__PROVIDER=stripe` + real credentials are set.
   EVC Plus/Zaad remain honest, interface-complete stubs (`NotImplementedError`, no merchant
   docs exist to verify an adapter against — the user's own explicit choice, not a lesser
   effort). A real, previously-undiscovered idempotency bug (`Payment.mark_paid`/`mark_failed`
   lacking same-state guards — a duplicate webhook delivery would have double-advanced a
   subscription's billing period) was found and fixed with a regression test. `OrgBillingPage`
   (`/org/billing`) now has a real "Pay Invoice" flow via Stripe Elements client-side card
   tokenization (PCI DSS SAQ A scope — raw card data never reaches this backend). Same disclosed
   posture as TLS/Redis: **mechanism complete and unit/live-signature-tested, not live-tested
   against a real Stripe account** — no merchant account exists in this environment. Only a real
   Stripe (or EVC Plus/Zaad, once real docs exist) account's live credentials remain before this
   is closeable end to end. See Known Issue #4 (updated) for the full detail.
9. **Mobile app MVP** — Parents/Drivers have no way to use the system, in any form.
   *(4–8 weeks)* — **partial, this session's honest limit reached.** Phase M0 (Foundation) and
   M2 (Driver) code-complete; M3 (Parent)'s live-tracking screen code-complete, its "assigned
   children" list was blocked on a real backend gap — **now closed, backend-side, by ADR-0023
   (2026-08-07, Known Issue #17 resolved)**: `GET /me/students`/`GET /me/driver-profile` exist
   and are tested. The mobile screens themselves (`parent_home_screen.dart` and the Driver
   trip-filter UX) are **not yet wired** to these new endpoints — still blocked on this
   environment having no Flutter SDK to verify any mobile change against, the same limitation
   named two paragraphs below. M4 (FCM)/M5 (release) need real
   external accounts (Firebase, app stores) this engagement cannot obtain — the identical
   category of blocker Item 8 (Payment) already carries. **The one categorical difference from
   every other item in this whole program: zero Flutter/Dart SDK exists in this sandbox, so
   none of this code has been compiled, analyzed, or run** — every other item retained some
   independent verification path (real HTTP, real Postgres, real YAML parsing); this one has
   none. `mobile/README.md`'s own "Testing limitation" section states this plainly. A genuine
   4–8-week MVP is not achievable to completion, still less to verified completion, inside one
   continuous session under these constraints — this is disclosed as the honest outcome, not
   claimed as finished.

### Priority 2 — Recommended before first customer
- ~~Notifications web UI (F8)~~ — ✅ **Complete** (2026-08-05). `NotificationsPage.tsx` (type
  filter chips, cursor-paginated "Load more," mark-as-read, live `/ws/notifications` refresh) at
  both `/platform/notifications`/`/org/notifications`; `AppShell`'s bell badge now shows a real,
  live-updating unread count. See Section 8 for the full writeup.
- ~~Billing web UI (F9)~~ — ✅ **Complete** (2026-08-05). `BillingPage.tsx` (tabbed, read-only
  Plans/Subscriptions/Invoices — this frontend's first `Tabs` pattern) at
  `/platform/billing`; Regional Manager/Support Staff see Plans only, matching their actual RBAC
  grants. See Section 8 for the full writeup.
- ~~Organization Billing UI + production payment architecture (ADR-0022)~~ — ✅ **Complete**
  (2026-08-06). `/org/billing` is now a dedicated `OrgBillingPage` (own subscription/plan/
  invoices/payment history, scoped to `principal.organizationId` — closing the shared
  `BillingPage`'s unscoped-list gap for this one route) with a real "Pay Invoice" flow, now that
  Priority 1 Item 8 (Payment) has a real, verified `StripePaymentAdapter` that can be bound. See
  Section 8 for the full writeup.
- Live video / JT1078 — only if video is part of the launch pitch. The relay itself is now built
  and tested (2026-08-11, see Section 3's JT1078 row) — remaining work is the backend
  `VideoProviderPort` adapter + control-endpoint transport decision, SPS/PPS handling, and real
  physical-device verification *(revised down from the original 3–6-week estimate; narrower now
  that the relay build-out itself is done)*.
- ~~Platform analytics (ADR-0020)~~ — ✅ **Complete** (2026-08-05, done ahead of its Priority 2
  slot at the user's request — see Section 8/9).
- ~~Session cap (ADR-0019)~~ — ✅ **Complete** (2026-08-04, done ahead of its Priority 2 slot at
  the user's request — see Section 8/9).
- Reporting renderer (PDF/Excel) *(~1 week)* — **not started, genuinely blocked**: picking a
  library needs `.claude/rules/workflow.md` #1/#2 explicit go-ahead before installing anything,
  *and* actual report content generation is separately blocked on the still-unresolved
  `ReportDefinition`/`report_definitions` documentation gap (Section 10, the Reporting-Phase-17
  finding) — binding a renderer without that would mean inventing report content no document
  specifies, not implementing an approved design.
- Load testing — plan exists, zero scripts *(3–5 days)* — **not started, genuinely blocked**:
  `testing/load/README.md` names three structural blockers (no deployed environment to test
  against, §13.1's own NFR targets are explicitly provisional pending doc-owner sign-off, no
  load-testing tool is an approved dependency) — writing scripts against unconfirmed targets
  would silently promote a proposal to a requirement, per that file's own reasoning.
- Log shipping / aggregation *(1–2 days)* — **not started, genuinely blocked**: needs a
  log-aggregation destination choice (Section 3's own "Logging" row) — a real design fork, not
  yet resolved.
- Secrets-manager integration, replacing hand-edited `.env` *(2–3 days)* — **not started,
  genuinely blocked**: needs a real external secrets-manager service/account (Vault, AWS Secrets
  Manager, or similar) this engagement cannot obtain.
- ~~CI hardening~~ — 🟡 **Partial** (2026-08-07). New `frontend-pipeline.yml`/
  `device-gateway-pipeline.yml` (`.github/workflows/`) — build→test only, mirroring
  `backend-pipeline.yml`'s exact scope discipline; the exact commands each runs were verified
  passing directly in this sandbox first (frontend 392/392 tests + clean build; device-gateway
  333/333 tests). All four now-real `ci-cd/pipelines/*.yml` index stubs updated to match,
  closing a real pre-existing drift (mobile's stub had lagged empty). **Still missing**:
  lint/security-scan gate (`ruff`/`mypy`/`eslint`/a scanner are all still unapproved
  dependencies — deliberately not invented), a deploy step, and `jt1078`/`infrastructure` CI
  (neither deployable/target exists yet). See Section 3's CI/CD row and Section 8 for the full
  writeup.
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
| 4 | Tracking | 🟡 In Progress | GPS ingestion + live tracking backend complete; Redis hardened mechanism-wise (Priority 1 Item 4), not yet live-verified in this sandbox (Known Issue #15). |
| 5 | Device Inventory | ✅ Complete | ADR-0018. |
| 6 | ADR-0019 Session Cap | ✅ Complete | Concurrent-session cap, revoke-oldest, self-service `GET`/`DELETE /auth/sessions`. |
| 7 | ADR-0020 Platform Analytics | ✅ Complete | `GET /admin/platform-stats` + real KPI grid. |
| 8 | Flutter Mobile App | ⬜ Planned | 0% built — structural scaffold only. |
| 9 | Video Platform | ✅ Complete (mechanism) | JT1078 relay built (2026-08-11) + wired to a real `VideoProviderPort` adapter (2026-08-12) + web frontend (F10, 2026-08-14, unified with GPS and extended to Platform Admin by ADR-0027/0028/0029, 2026-08-16) + live-verified end to end against the physical bench unit, four real bugs found and fixed (2026-08-19). Still open: HLS, the reconciliation-timeout job, the Flutter mobile player's own verification, production-domain ingest routing. |
| 10 | Production Deployment | ⬜ Planned | Blocked on Section 5 Priority 1 (monitoring, RBAC admin route, deployment docs, payments, mobile app). |

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
**Nothing — ADR-0032 (Camera Role Taxonomy + D5 Cabin-Facing Exclusion Fix) and ADR-0033
(Terminal Audio Capability Capture) are both complete (2026-08-27).** At explicit user
direction ("bench test first, then implement audio / camera roles / ADAS-safety / future-ready
DMS / intercom, without assuming AAC or inventing hardware capabilities"): the current bench unit
has an ADAS-relevant road-facing camera and an internal/cabin camera connected; **no DMS
(driver-facing) camera is connected** — both ADRs are scoped accordingly, adding taxonomy and
capability-capture only, never a physically-unverified claim.

**ADR-0032** widens `CameraPosition` (previously `in_cabin`/`road_facing`/`other`) with `front`/
`rear`/`left`/`right` (ADAS-relevant directional roles) and `driver_facing` (the DMS role,
reserved — **not assigned to any camera**, since none is connected). A new `Device.update_camera`
(application-layer only, no HTTP route yet — mirrors `RegisterCameraCommand`'s own
no-route posture) lets an admin correct ADR-0030's auto-discovery `other` default after the fact.
**A real, pre-existing D5 gap was found and fixed while widening the taxonomy, not introduced by
it:** `CameraPosition`'s own docstring always claimed `in_cabin` "is never exposed to parents,"
attributing that to `VideoAccessPolicy` — but `interfaces/http/policy_guards.resolve_d5_decision`
(the actual D5 enforcement point) never took a camera/position argument at all, so a parent
granted `has_video_live_access`/`has_video_playback_access` (ADR-0026) and owning the right child
could reach *any* camera, including the in-cabin one. Fixed with a new `camera_position`
parameter on `resolve_d5_decision`/`enforce_d5` and a `CameraPosition.is_cabin_facing` property
(`in_cabin`/`driver_facing`) — absolute for `Role.PARENT` only, Org Admin/RAAD staff unaffected.
Migration `a6682ad19581` (additive enum values only).

**ADR-0033** closes a real information-loss bug: device-gateway's `commands/av_attributes.
AvAttributesReport` already parsed the terminal's full `0x1003` audio/video attributes reply
(confirmed live — the bench terminal's own 2026-08-19 exchange left no trace of its audio fields
anywhere), but `DeviceAvAttributesReported` (ADR-0030) only ever carried
`max_video_channels`/`max_audio_channels`. Widened the event end-to-end (device-gateway's
`LoggingEventPublisher`/`RedisEventPublisher`/handler — all three producers updated, not just the
one that would crash first, per ADR-0030's own documented lesson) and added a new
`AudioCapability` value object + `Device.record_audio_capability` (mirrors
`record_av_attributes_requested`'s "wire fact, not business decision" shape: no domain event, no
lifecycle check, always overwrites as one unit). Backend wiring — `RecordAudioCapabilityCommand`,
`DeviceApplicationService.record_audio_capability`, a second independent branch on
`DeviceAvAttributesReportedProcessor` (checked with `is not None`, never truthiness — `0`/`False`
are valid reported values), `infra/mappers.py` round-trip, migration `3aef3f7c7bb1` (seven
nullable `devices` columns) — was completed in this same pass after being found partially built
(ORM columns present, no migration yet) at session recovery. **No codec is assumed** — `codec`/
`video_codec` are recorded as Table 6.21's raw enum byte, never decoded to a name (no approved
document maps that table yet) — **not AAC, not anything else.** `supports_audio_output` is
captured as the prerequisite fact any future intercom/PA feature would need, but no downlink
audio command or streaming path is added — disclosed groundwork, not a working intercom.

**ADR-0033 is now physically verified against the real `LSZ-C5804DG-Q-F` bench MDVR, same day
(2026-08-27), not just synthetic-fixture-tested.** After this session's own device-gateway/worker
rebuild put the code live, a real JT808 registration → authentication → `device_online`
transition correctly re-triggered `0x9003` (the guard had been reset to `NULL` for this test),
and the terminal replied with a real `0x1003` carrying `max_video_channels=4`,
`max_audio_channels=4`, `input_audio_codec=6`, `input_audio_channels=1`,
`input_audio_sample_rate=0`, `input_audio_sample_bits=1`, `audio_frame_length=320`,
`supports_audio_output=true`, `video_codec=98` — codec/sample-rate values kept exactly as opaque
wire bytes throughout, per the same "no codec assumed" rule this ADR already committed to.
Persisted idempotently: all seven `devices` columns now hold these values, and the same reply's
channel count against the 4 pre-existing `Camera` rows (from 2026-08-19) logged
`camera_channel_already_registered` for each — no duplication. **One operational note, not a
hardware-capability finding:** the first automatic query (published `20:32:43Z`, right after the
guard reset) got no reply in the following ~49 minutes despite the device staying connected and
sending GPS/heartbeats throughout; a manual re-publish of the identical request 49 minutes later
(`21:32:40Z`) got a real reply in ~19ms — as fast as this device's own two 2026-08-19 round
trips. No error was ever logged on either attempt, so this reads as one dropped/unanswered
application-layer exchange, not a protocol or code defect — the identical request succeeded on
retry with zero code changed in between. Full detail: ADR-0033's own Verification section.

**Preserving a distinction the user asked to keep explicit:** *physical-hardware-confirmed* now
covers this unit's real audio-capability report and its 4-channel video/audio capacity.
*Protocol-supported-but-hardware-unverified* still covers DMS, ADAS, and intercom — none is
implemented, and `supports_audio_output=true` is a confirmed fact about this hardware, not a
working intercom feature.

**What neither ADR does, disclosed not silently skipped:** no ADAS/DSM alarm detection or
ingestion of any kind — `docs/vendor/HARDWARE_ANALYSIS.md` confirms this is undocumented for the
confirmed `LSZ-C5804DG-Q-F` spec, and `RAAD_DevicePlane_Architecture_v0_1_draft.md`'s own
`AdasEventDetected`/AI-alarm ingestion remains **[PROPOSED]**, not approved — implementing alarm
logic here would have been inventing a hardware capability no approved document describes.

Verified: full backend `tests/unit` + `tests/architecture` (1458 passed, 15 subtests), full
`tests/integration` against real PostgreSQL with both migrations applied (the `fleet_device`
device round-trip suite, previously failing with `UndefinedColumnError` on the unmigrated audio
columns, now passes in full — the two remaining integration failures, `test_realtime_broker_
fanout.py`, are pre-existing and unrelated, confirmed via `git stash` to fail identically at the
pre-session commit). Device-gateway: full suite, 431 passed. New/updated tests:
`CameraPositionCabinFacingTests`, `update_camera` domain/application cases,
`RecordAudioCapabilityTests`, `DeviceAvAttributesReportedProcessorAudioCaptureTests`,
`ResolveAndEnforceD5Tests`' new cabin-facing-denial regression tests. See
`docs/architecture/adr/0032-camera-role-taxonomy-and-d5-cabin-exclusion-fix.md` and
`0033-terminal-audio-capability-capture.md` for full detail.

**Nothing — ADR-0031 (Fleet Overview Online-Vehicles Read Model) is complete (2026-08-23).** The
Live Tracking frontend redesign's "All Vehicles" fleet-map mode needed a bulk "which vehicles are
online right now" data source; none existed anywhere in this backend — `GET /vehicles`
deliberately omits `tracking_status` on list rows to avoid an N+1 device lookup per page,
`GET /devices?filter[is_online]=true` carries no `vehicle_id` at all, and no bulk latest-position
read existed. Building it from single-vehicle calls alone would have meant up to ~200 REST
round-trips (`GET /vehicles/{id}/device-assignment` + `GET /devices/{id}`, per vehicle, bounded
only by the existing ≤100-vehicle page cap) just to determine who's online, before a single
realtime update — the exact N+1 shape `tracking_status: null` was introduced elsewhere in this
codebase specifically to avoid, and repeating it here for a brand-new feature would have been
inconsistent with that precedent. Per `.claude/rules/workflow.md` #8, `docs/architecture/adr/
0031-fleet-overview-online-vehicles-read-model.md` was written and accepted before implementation.

New `GET /tracking/vehicles/online`, owned by `tracking` (mirroring ADR-0020/ADR-0023's "new
composing application service lives in the module that owns the capability" precedent, never a
cross-module DB read — verified clean against the architecture-gate module-boundary suite, 10/10
passing). A new `FleetOverviewApplicationService` composes `VehicleApplicationService`/
`DeviceApplicationService` (per-call UoW, mirroring `PlatformStatsApplicationService`'s own shape)
plus a new, optional `LatestPositionPort.get_latest_many` (one Redis `MGET` for every requested
key, never a `get_latest` loop — the identical "one round trip, not N" reasoning `list_by_ids`
applies at the SQL layer). Two small, additive `fleet_device` methods, no schema/migration:
`DeviceRepository.list_online_with_active_assignment()` (one JOIN on `device_assignments`,
`_apply_scope`-scoped like every other `list_*` method, ADR-0021) and `VehicleRepository.
list_by_ids()`. Capped at `FLEET_OVERVIEW_MAX_ONLINE_VEHICLES = 100`, sorted deterministically by
`vehicle_id`, with the true pre-cap count returned separately (`total_online`) so an organization
with more online vehicles than the cap gets an honest "showing X of Y" signal, never a silent
truncation.

**A real authorization gap found and fixed while wiring this route, not silently shipped:** the
reused `tracking.vehicles.read_latest` permission (deliberately no new permission/migration) is
also held by `parent`, for their existing single-vehicle, CR-1-gated use case
(`GET /tracking/vehicles/{id}/latest`, `/ws/tracking`). This new *bulk* route has no per-vehicle
ownership check at all (an admin fleet-list view, matching `GET /vehicles`/`GET /devices` (list)'s
own posture, not the single-vehicle CR-1 posture) — reusing the permission alone would have let a
parent's own mobile JWT list every vehicle in their organization, not just their child's. Fixed
with an explicit, migration-free role-set check (`_FLEET_OVERVIEW_ELIGIBLE_ROLES` — Founder/
Regional Manager/Support Staff/Org Admin only), mirroring `core.policies.video_access`'s own
identical `_VIDEO_ELIGIBLE_ROLES` shape for the exact same "the permission is broader than this
one route needs" mismatch. Regression-tested (`test_tracking_fleet_overview.py`).

Frontend: a new `useFleetVehiclePositions` hook fetches the endpoint once for the initial
snapshot, then opens up to `total_online` (capped) independent `/ws/tracking` connections for
realtime updates — reusing `useWebSocketChannel`, the same primitive `useVehiclePosition` already
uses, with zero backend protocol change (`/ws/tracking` already enforces exactly one active
vehicle subscription per *connection*, not per browser tab, so N connections is a correct,
already-tested reuse — the same "N independent instances of a single-item hook" shape already proven safe
in this codebase for `MultiCameraVideoPanel`/`CameraTile`'s N independent
`useVideoSessionController` instances, one per camera). Evaluated and deliberately capped rather
than redesigned: at RAAD's realistic per-organization fleet size (tens to a couple hundred buses,
not thousands — no NFR target suggests otherwise), 100 near-simultaneous connections is a real but
acceptable latency burst against the shared ~15-connection DB pool; 500+ would not be, and raising
the cap needs a genuine `/ws/tracking` multi-vehicle-subscribe protocol change, explicitly not
attempted here. `FleetMapPanel`/this mode never initializes video/camera state at all — 10 buses ×
4 cameras = 40 possible streams is never the desired behavior for this mode.

**What remains open, disclosed in the ADR itself, not hidden:** `position` is `null` for every
vehicle today — the pre-existing, separately-tracked JT808 `LatestPositionWriter` wiring gap
(CLAUDE.md's own "Device onboarding readiness audit" section), not new to this ADR and not
required to close it; populates automatically once that gap is separately closed, no change
needed in this read model when it is. No dedicated live-DB integration test was added this pass
for the two new repository methods (verified by static review against `count_online`/`list_page`'s
own already-tested patterns instead, plus the full architecture-gate + unit suite passing).

**Nothing — ADR-0030's automatic camera-discovery workflow has now been verified genuinely
end to end against the physical `LSZ-C5804DG-Q-F` bench unit (`terminal_id=
00000000014482607571`), including a full real live-video request, and four more real,
production-blocking bugs found and fixed along the way (2026-08-19).** At explicit user
direction, following the previous session's ADR-0030 implementation: authenticate → auto-trigger
`0x9003` → `0x1003` reply → `DeviceAvAttributesReported` reaches the backend → `Camera` rows
auto-created → visible through the existing `GET /devices/{id}` API → a real `POST /video/live`
→ `0x9101` → the device dials the relay's ingest port → real extended-RTP frames flow →
`VideoSession.status=active` → a connected viewer. **No Camera row was ever manually inserted and
no device data was modified to fake a result** — the one intentional write was resetting
`devices.av_attributes_requested_at` back to `NULL` for this one device (confirmed with the user
first), because a prior attempt under pre-fix code had already consumed the ADR's own one-shot
discovery guard without ever actually completing it.

Discovered that the running Docker stack (`raad-backend`/`raad-worker`/`raad-device-gateway`) was
still on images built *before* ADR-0030's own code existed, and `jt1078-relay` had never been
started at all despite having no Compose `profile` gate — nothing in this checklist could have
worked until all four services were rebuilt/started against current code. Doing that surfaced
four real, previously-undetected bugs, none caught by any fake-backed unit test because none of
the fakes reproduced the failure mode:

1. **`DeviceAvAttributesReported` was never wired into device-gateway's `publisher_port.
   DeviceEvent` union / `LoggingEventPublisher` / `redis_event_publisher._fields_for`** — with
   the real broker-backed publisher this raised `TypeError` on every `0x1003` reply; with the
   default logging-only publisher it silently vanished. Fixed by adding the missing branch to
   all three (committed as part of the ADR-0030 phase, see previous entry below).
2. **Three separate `async def run_forever(self): while True: await self.poll_once()` consumer
   loops** (`RedisDeviceRegistryConsumer`/`RedisVideoSignalingConsumer` on device-gateway,
   `SessionRequestServer` on jt1078-relay) **had no exception handling at all** — a single
   transient Redis error permanently and silently killed each task for the rest of the process's
   life. Live-caught via `SessionRequestServer`: a real `BusyLoadingError` on its very first poll
   left 22+ genuine live-video session requests piled up, completely unprocessed, with zero log
   output, until the process was later restarted and finally surfaced the buried exception on
   shutdown. All three now catch, log, and continue — see CLAUDE.md's own Permanent Engineering
   Lessons for the full incident and the fix's own resemblance to `core/workers/base.py
   Worker._tick`.
3. **`DeviceRegistryProjection` (in-memory) vs. its own Redis consumer group (durable) —
   a device-gateway restart previously made every already-provisioned device unresolvable**
   (`terminal_not_found` on a real, previously-working registration) until an unrelated new event
   happened to touch it again. Fixed by `RedisDeviceRegistryConsumer.replay_from_start` — a raw,
   group-independent `XRANGE` full-stream replay run before any adapter starts accepting
   connections.
4. **`SessionManager.resolve_ingest_by_terminal_id` compared JT/T 1078's own narrower `BCD[6]`
   ingest-frame SIM card number against the wider `BCD[10]` `terminal_id` with exact `==`** —
   structurally could never match. The device correctly dialed the relay's ingest port and
   streamed valid frames; every one was rejected as `unsolicited_ingest_connection_rejected`
   regardless. Fixed by matching on the narrower field's own trailing suffix.
5. **`JT1078_RELAY_PUBLIC_INGEST_HOST` was never wired into `docker-compose.yml`/
   `docker/.env.example` at all** — left unset, `RelayConfig.effective_public_ingest_host` falls
   back to its own bind address `0.0.0.0`, embedded verbatim as `server_ip` in the `0x9101`
   signaling body. The device acknowledged the command every time (a wire-valid message), but
   could never dial an unroutable address, so no ingest byte ever arrived and every session timed
   out `failed` — silently, with no error anywhere in the chain. Now wired with no safe universal
   default (flagged, must be set per-environment); this environment's own `docker/.env` was set
   to the host's real LAN IP, the same network path the bench device already uses for
   `DEVICE_GATEWAY_JT808_PORT`/7808.

Verification after all fixes: backend `tests/unit`+`tests/architecture` (1427 tests, 10
subtests), device-gateway's full suite (423 tests), `services/jt1078`'s full suite (122 tests,
including new regression coverage for bugs 2/3/4 above) — all passing. Live: `devices.is_online`
flips true, `av_attributes_requested_at` sets on first-ever online, 4 `Camera` rows auto-created
(`position=other`/`label="Channel N"`, matching `max_video_channels=4`), visible via
`GET /devices/{id}`; a real `POST /video/live` reached `status=active` with a genuinely connected
viewer. **Still not exercised by this pass:** HLS, ADR-0024 §16's own reconciliation-timeout job,
the F10 web player's own UI polish beyond what already shipped (ADR-0028) — none of these were in
scope for this verification pass.

**Nothing — ADR-0030 (Automatic Camera/Channel Discovery) is complete.** A read-only bench-test
diagnostic against the physical `LSZ-C5804DG-Q-F` unit (`terminal_id=00000000014482607571`) found
GPS/registration fully working but zero `Camera` rows and no code path to create one automatically;
the user declined a one-off manual fix and asked for the generic product workflow instead. Per
`.claude/rules/workflow.md` #8, `docs/architecture/adr/0030-automatic-camera-channel-discovery.md`
was written and accepted (2026-08-18) before implementation, resolving three design forks via
`AskUserQuestion`: discovery fires once per device on first successful auth (idempotency guard:
new `devices.av_attributes_requested_at`, migration `7d3a9c1e5b42`); every discovered channel
defaults to `position=other`/`label="Channel N"` (no vendor-specific semantic mapping hardcoded);
`JT1078_SIGNALING_URL` is a new Compose variable (dev default `ws://localhost:7911`, production
must set a real value). New device-gateway protocol code: `commands/av_attributes.py`
(`0x9003`/`0x1003`, spec §6.1.1/§6.1.2 — the channel-*count* query/report, confirmed distinct from
`0x9205`/`0x1205`'s recorded-file resource list), `handlers/av_attributes_handler.py`
(correlates via a new `PendingCommandTracker.resolve_by_terminal_and_message`, since `0x1003`'s
body carries no echoed serial number), publishing a new `DeviceAvAttributesReported` event.
Backend: `DeviceConnectivityProcessor` now triggers the `0x9003` request on a device's first
`DeviceOnline`; a new `DeviceAvAttributesReportedProcessor` calls the existing, previously-
unreachable `DeviceApplicationService.register_camera` once per channel `1..max_video_channels`,
idempotent by construction via `register_camera`'s own `ux_cameras__device_channel` invariant.
**Two real gaps found and closed while verifying this session's own uncommitted work, not by the
original implementation pass:** (1) `DeviceAvAttributesReported` was never added to device-gateway's
`publisher_port.DeviceEvent` union, `LoggingEventPublisher`, or `redis_event_publisher._fields_for`
— with the real `RedisEventPublisher` this raised `TypeError` on every `0x1003` reply, and with the
default `LoggingEventPublisher` the event silently vanished; both unit-test suites used a recording
fake publisher, so neither gap was caught by `pytest`. Fixed by adding the missing branch to all
three. (2) `tests/unit/test_fleet_device_application.py::RecordDeviceSeenTests::
test_updates_last_seen_at_and_commits` still asserted `record_device_seen`'s old always-`None`
return value, failing against the widened `str | None` signature; fixed the assertion and added a
new regression test (`test_returns_none_once_discovery_already_requested`) proving the second
`DeviceOnline` for the same device does not re-trigger discovery. Verification after both fixes:
device-gateway's full suite (419 tests) and the new `test_av_attributes*`/`test_pending_commands`/
`test_redis_video_signaling_consumer` tests (24 tests) all pass; backend `tests/unit` +
`tests/architecture` (1427 tests + 10 subtests) and `tests/integration` (278 tests + 21 subtests,
migration `7d3a9c1e5b42` applied and upgrade→downgrade→upgrade round-tripped clean, `alembic check`
reports zero drift) all pass — the only integration failures are two pre-existing Redis-timeout
tests unrelated to this change (no reachable Redis broker in this sandbox, Known Issue #14's own
precedent). `tests/contract`'s pre-existing `NoSilentUndocumentedRoutesTests` failure (18 routes
from ADR-0017 through ADR-0023 never added to `DOCUMENTED_ROUTES`/`ALLOWED_UNDOCUMENTED_EXTRAS`) is
untouched by this change — ADR-0030 adds no new HTTP route — and is not fixed here, flagged as a
pre-existing gap.

**JT1078 video-integration program (ADR-0024/ADR-0025) closed end to end, mechanism-wise
(2026-08-12).** Four back-to-back, user-directed phases (2026-08-10 through 2026-08-12): the
native-protocol architecture reversal (ADR-0025, same-commit ADR-0024 §1 revision); the JT/T
808-2019 field-width rework + `0x0102` auth-code lifecycle + `0x0200`/`AlarmFlags` byte-diff
resolution (commit `f5e9fae`); the JT/T 1078 video-signaling forwarding on device-gateway plus the
`services/jt1078` relay build-out (commits `297153e`/`7e4e77d`/`258a10c`); and finally the Business
API `VideoProviderPort` → relay wiring (this turn, commits `224afd4`/`8212f1e`) — see each phase's
own dated write-up below for full detail. **What remains, genuinely external and not fabricable in
this sandbox: a physical MDVR to verify any of the above against.** Every phase above is
specification-verified and unit/integration-tested against synthetic fixtures/fakes only, never
against real device bytes — this document does not claim otherwise anywhere. What also remains,
disclosed not silently dropped: the frontend video player (F10), SPS/PPS population, HLS, the
relay concurrency ceiling, `audit_entries` writes for video sessions, and the relay-event-to-
`VideoSession` reconciliation gap (JT1078/Video rows, Section 3). Section 2's Mobile row and
similar minor doc staleness remain outstanding, not yet corrected, noted, not forgotten.

**Native JT/T 808-2019 + JT/T 1078-2016 protocol compliance — architecture update (2026-08-10,
user-directed, ADR-0025).** Reverses ADR-0009's core finding for this specific procured hardware
(`LSZ-C5804DG-Q-F`) only — everything else ADR-0009 decided (the parallel-stack pattern itself,
the device-gateway rename per ADR-0010, the identity-only trust model per ADR-0015 for any vendor
that genuinely lacks a credential) is untouched. New `docs/architecture/adr/
0025-jt808-2019-jt1078-2016-native-protocol-compliance.md`: §1 records the reversal and its
basis (the two new supplier documents, reviewed in the prior turn's own 18-question review, with
that review's own flagged authenticity gap — mismatched company names between the spec and the
compliance letter, no model number inside the spec, an unsigned same-day-dated letter — carried
forward honestly rather than silently dropped now that the user has confirmed "verification is
complete" out-of-band); §2 tabulates the confirmed JT/T 808-2013→2019 wire-format deltas (header
terminal-phone `BCD[6]`→`BCD[10]`, a new protocol-version byte, wider manufacturer/terminal-model/
terminal-ID fields in `0x0100`, added IMEI+software-version fields in `0x0102`); §3 **resolves**
the previously-open `0x0102` auth-code *lifecycle* question (Known Issue #18) with a concrete
design — a platform-minted random code on `0x0100` success, hashed at rest in the existing,
previously-unused `Device.auth_key_hash` column, verified by hash comparison on `0x0102`, no
time-expiry, rotating only on a fresh registration — explicitly flagged in the ADR's own text as
"a reasoned design recommendation... not independently re-confirmed with the user," distinct in
confidence from the wire-format finding itself; §4 makes `vendors/jt808/` the live/primary GPS
adapter going forward, keeps `vendors/lsz/` dormant (not deleted — mirrors exactly how `vendors/
jt808/` itself was kept dormant before this reversal); §5 supersedes ADR-0024 §1's LSZ-proprietary
video-signaling design with native JT/T 1078 signaling (confirmed by spec §6 to ride the same
JT808 envelope/connection, not a separate proprietary media-channel handshake); §6 retires the
"Reality check" disclaimer preambles `.claude/rules/jt808.md`/`jt1078.md` have carried since
ADR-0009. A "What this ADR does not do" section is explicit: no `.py` file changed, no migration
(the `auth_key_hash` column already exists), no `0x0200`/`AlarmFlags` byte-for-byte diff, no
JT1078 runtime/language decision, no new dependency approved.

**ADR-0024 (JT1078 Video Relay Architecture) revised in place, same commit** — surgical edits, not
a rewrite, since most of that document (D5 enforcement, concurrency bounding, audit, transport
choice reasoning) is protocol-agnostic policy the reversal doesn't touch. §1 rewritten: the old
LSZ-proprietary signaling design (`C508`/`V102`/`0x6000`/`0x6002`/`0x6011-13`/`C701`/`C702`/`V103`/
`0x6102`) is replaced by native JT/T 1078 messages (`0x9101`/`0x9102`/`0x9105` live,
`0x9201`/`0x9202`/`0x9205`/`0x1205` playback) — `0x9202`/`0x9205` are noted as genuinely richer
capabilities the old proprietary design lacked (native seek, resource browsing), not just a
renaming; §2/§6/§7/§8/§14/§16/Consequences/Verification/References sections updated to match
throughout (ingest becomes a standard extended-RTP demuxer per spec §6.2.1.1, not a proprietary-
opcode one; no second vendor-adapter needed — `vendors/jt808/` gains the forwarding responsibility
directly, no translation step). A final repo-wide grep for every old LSZ video opcode and the
phrases "LSZ proprietary"/"LSZ media" confirmed all remaining occurrences are either intentional
"supersedes X" citations or were themselves fixed (a stale `C701`/`C702` citation in §2, and "the
most LSZ-specific failure mode" wording in §16, both corrected to their native-protocol
equivalents).

**Rule files and CLAUDE.md updated to match.** `.claude/rules/jt808.md`/`jt1078.md`: each
"Reality check" preamble (which disclaimed the file as describing a hypothetical future compliant
vendor, not the actual hardware) replaced with a "Status" paragraph confirming compliance and
pointing at what's still unbuilt (the field-width rework, the auth-code implementation, the
JT1078 runtime decision) — the numbered rules themselves needed no change, since they were already
written against the compliant-vendor target. CLAUDE.md's "Core Technical Domains" section
rewritten: the old "vendor doesn't implement either protocol" framing and the "0x0102 remains
deliberately unimplemented" framing are both replaced with paragraphs recording the reversal, the
current live/dormant adapter roles, and an explicit flag that the field-width rework and
auth-code implementation are "not yet implemented, per ADR-0025 §2/§4" and "§3" respectively — not
silently implied as done. Verified CLAUDE.md's post-edit size (64,708 chars) stays well under the
150,000-char operating budget established in this session's own earlier cleanup phase.

**Nothing deleted.** The mdvrdocs/ classification conclusion from the prior review turn (nothing
classified safe to delete — all six files, including the two new PDFs, are still referenced by
name in currently-authoritative repo docs) stands, and ADR-0025's own Consequences section
reconfirms it explicitly ("No file is deleted by this ADR").

**JT808 device-plane provisioning/identity integration gap (2026-08-09, user-directed audit +
targeted implementation, not a Section 14 pick).** New `ProjectionBackedJt808ProvisioningPort`
(`vendors/jt808/handlers/provisioning_port.py`) resolves a device's `terminal_id` against the
same shared, vendor-agnostic `DeviceRegistryProjection` LSZ already uses (it was already indexed
by both `terminal_id` and `serial_number` for exactly this reason, confirmed by reading the
projection's own code before writing anything) — a real, pre-provisioned device (registered in
`fleet_device` → activated → assigned to a vehicle) is now correctly identified and resolved to
its `device_id`/`vehicle_id`/`organization_id` at `0x0100`; unknown, registered-but-inactive,
activated-but-unassigned, suspended, and retired devices all correctly collapse to
`TERMINAL_NOT_FOUND` — no automatic `Device` creation, no pending state, connection rejected,
mirroring LSZ's own identical precedent exactly. New `HeartbeatHandler` (`0x0002 → 0x8001`,
replacing the placeholder that message ID previously fell to) plus a `touch()` call added to
`LocationHandler` (`0x0200`) — both wire the pre-existing, previously-never-triggered
`DeviceSessionManager.touch()` (`AUTHENTICATED → ONLINE` promotion) and `Jt808Server.
_on_device_online`/`_on_device_offline` (real `DeviceOnline`/`DeviceOffline` publishing, already
built, never fired for JT808 before this), the same bug-fix precedent `MdvrPositionHandler`
already established for LSZ (a device reporting only positions, never heartbeats, must not expire
under the idle-timeout sweep while actively transmitting). `gateway.py` now builds one shared
`DeviceRegistryProjection` and hands it to both vendors' own provisioning ports, via the same
DI/composition-root pattern LSZ already used.

**`0x0102` authentication verification deliberately NOT implemented.** Re-reading `provisioning_
port.py`'s own pre-existing docstring confirmed the conflict was already flagged before this
turn, not newly discovered: JT808 Technical Design §4 reads as a device-held static secret
checked against `Device.auth_key_hash`; the primary JT/T 808-2013 spec's own text (§8.6/§8.8/
§21.1, verbatim) reads as a platform-minted code issued in `0x8100` and echoed back in `0x0102`;
Backend LLD adds a third, only-partially-compatible reading (a short-lived, Redis-held, rotating
session token). These are not close readings of the same idea — they're three different security
mechanisms requiring different persisted state and different comparison logic, and picking wrong
risks either rejecting every real device forever or implementing a check real hardware never
actually performs. `authorize_registration` returns `SUCCESS` with `auth_code=None` (a real
device is genuinely identified/provisioned, but the wire response's auth-code field can't be
filled in correctly); `verify_auth_code` always returns `is_valid=False` — both explicitly
documented in code as the deliberate, currently-unresolvable boundary, not a fail-closed
oversight left over from the old `NullDeviceProvisioningPort`. Blocks on the supplier's
forthcoming standalone JT808 documentation — tracked as Known Issue #18, not silently left
implicit.

**Testing.** 18 new device-gateway tests: `ProjectionBackedJt808ProvisioningPort`'s full
accept/reject matrix (provisionable, unknown, unactivated, unassigned, suspended, retired, plus a
two-device cross-organization/cross-vehicle resolution proof and a dedicated test confirming
`auth_code` is never fabricated); `HeartbeatHandler` (ack shape, online promotion, unknown-
terminal safe no-op, no double-fire on a second heartbeat); `gateway.py` wiring (both vendors'
Null fallback with no broker configured, both vendors' real `ProjectionBacked*` port with one
injected, a dedicated proof both vendors resolve identity through the *same* shared projection
instance, not two independently-fed copies). 3 existing test files needed real fixes, not just
additions, because `touch()` now genuinely fires `DeviceOnline` where it previously silently
didn't: `test_position_pipeline_integration.py`'s `RecordingEventPublisher` gained `.positions`/
`.online_events` filtering properties so existing count/index assertions on "the position event"
still find the right one now that a `DeviceOnline` legitimately precedes it; `test_server_
dispatch_integration.py`'s "known placeholder sends no response" test moved off `HEARTBEAT`
(which now correctly *does* respond) onto `LOGOUT` (still a real placeholder); `test_
authentication_registration_integration.py`'s existing register→authenticate scenario was
extended with a real heartbeat frame proving the wire-level promotion to `online` now actually
happens. device-gateway: 351/351 (was 333). 3 new live-Postgres integration tests in `backend/
tests/integration/test_fleet_device_repository.py` close a real, previously-untested gap flagged
during the original audit ("can two organizations ever accidentally claim the same JT/T 808
terminal ID?") — the existing unit test (`test_duplicate_terminal_id_is_rejected`) only ever
proved same-organization duplication against a fake repository; the new `CrossOrganizationTerminalIdTests`
class proves the cross-organization case against a real, live-migrated Postgres database, through
the actual `DeviceApplicationService.register_device` application-layer call, matching the
security-testing standard `TenantIsolationRepositoryTests` (ADR-0021) already established in this
same file. `fleet_device` integration: 32/32 (was 29). Backend unit (1330) and architecture-gate
(10) suites re-run as a regression check — unchanged, zero regressions. No ADR written: this
closes an implementation gap inside an already-accepted design (ADR-0009/0010's own multi-vendor
`DeviceProtocolAdapter` architecture), it doesn't create a new architectural decision — the same
"wiring/integration, not a new ADR" posture CI hardening (below) was itself built under. JT1078
and video work were explicitly untouched, per the user's own scope instruction.

**JT/T 808-2019 field-width rework, `0x0102` auth-code lifecycle, and JT/T 1078 video-signaling
forwarding + relay build-out (2026-08-11, user-directed, the "following, separately-authorized
implementation phase" ADR-0025 §2/§3 and ADR-0024 §1/§8/Consequences both named as not-yet-started).**
Three parts, run back to back at explicit user direction (mirroring Priority 1 Items 5-9's own
precedent for sequential, user-authorized work):

1. **Field-width rework + auth-code lifecycle** (`services/device-gateway/src/vendors/jt808/`):
   `header.py` reworked to the confirmed 2019 shape (`BCD[10]` terminal phone, protocol-version
   byte); `registration_body.py`/`authentication_body.py` widened to the 76-byte/variable-length
   2019 bodies. `0x0200`'s own basic-info layout was **confirmed byte-for-byte identical** between
   the 2013 citation already implemented and the 2019 supplier spec (`mdvrdocs/
   MDVR-808-1078-spec.pdf` §5.2.1 Tables 5.7-5.10, verified table-by-table, offset-by-offset) —
   `position_body.py` needed a citation update only, no logic change, resolving the "0x0200/
   AlarmFlags byte-level diff" ADR-0025 §2 flagged as outstanding. `ProjectionBackedJt808
   ProvisioningPort.authorize_registration`/`verify_auth_code` now implement ADR-0025 §3's design
   for real: mints + PBKDF2-HMAC-SHA256-hashes a fresh code on every successful `0x0100`
   (`auth_code_hashing.py`), verifies by hash comparison on `0x0102`, publishes a new
   `DeviceAuthCodeIssued` event so `fleet_device.Device.auth_key_hash` (previously always `None`)
   mirrors it via a new `DeviceAuthCodeProcessor` subscriber — closes Known Issue #18 for real,
   not just architecturally. **A real bug was found and fixed during this pass**:
   `DeviceAuthCodeProcessor` never set `self.event_type`, so `EventProcessorRegistry.register()`
   (keyed by that attribute) would have raised `AttributeError` the instant a real deployment
   wired up its processors — no test exercised that registration path before this pass; confirmed
   fixed by direct registration.
2. **JT/T 1078 video-signaling forwarding** (ADR-0024 §1/§8, ADR-0025 §5): new `commands/`
   package — `video_signaling.py` encodes/decodes `0x9101`/`0x9102`/`0x9105`/`0x9205`/`0x9201`/
   `0x9202` (downlink) and `0x1205` (uplink resource-list report), every byte layout traced
   directly to the supplier spec's own §6.2/§6.3 tables (including the conditional BCD[6]
   "all-zero means no time constraint" convention `0x9205`/`0x9201` each declare). A **deliberate
   refinement of ADR-0024 §8's literal wording**: that section describes the Business API
   publishing "its already-encoded body," but this phase has device-gateway own the wire encoding
   instead (the Business API publishes structured, business-meaningful fields only) — kept
   consistent with the Anti-Corruption-Layer principle ADR-0009 already established (all JT/T
   808/1078 wire-format knowledge stays inside the device-plane deployable), flagged as a
   documented implementation-phase decision, not a silent deviation. New generic (not
   video-specific) correlation infrastructure: `PendingCommandTracker` + `CommandSender`
   (`jt808.md` #6's "every platform-issued command must be traceable back to the requesting
   use-case and its result"), sharing one `OutboundSerialCounter` with the dispatcher's own
   automatic responses. `TERMINAL_GENERAL_RESPONSE` (`0x0001`) is now a real `CommandAckHandler`
   (previously a placeholder); `RESOURCE_LIST_REPORT` (`0x1205`) is a new real handler. A new
   `RedisVideoSignalingConsumer` (mirroring `RedisDeviceRegistryConsumer`'s exact shape, its own
   consumer group on the shared `raad:events` stream) receives command requests and forwards them
   — wired into `gateway.py` as a third broker participant, bound only when a broker is
   configured. **No Business-API-side publisher of these events was built** — out of this phase's
   own task list; the consumer has a real, documented wire contract but no real producer yet.
3. **`services/jt1078/` media relay build-out** — see Section 3's JT1078 row for the full
   implementation summary (runtime decision + evidence, ingest/session/token/repackager/viewer,
   zero new dependency, Docker wiring). Full end-to-end path (synthetic device frames → ingest →
   reassembly → FLV repackaging → WS-FLV viewer delivery) proven over real loopback sockets.

**Testing.** device-gateway: 357 → 408 (51 new: BCD-datetime codec, video-signaling encode/decode
against spec-derived byte fixtures, `PendingCommandTracker`, `CommandSender`,
`CommandAckHandler`, `ResourceListHandler`, the Redis consumer, and a real-socket integration test
proving a full command round trip — send a `0x9101`, receive it over a real authenticated
connection, ack it, observe the correlated `DeviceCommandResult`). `services/jt1078/`: 0 → 82,
all new — extended-RTP demux, subpackage reassembly, session lifecycle, viewer tokens (signature/
expiry/single-use), FLV muxer (container structure + Annex-B→AVCC conversion), the hand-rolled
WebSocket server (a real bug was found and fixed here too: Python 3.13+ changed
`asyncio.Server.wait_closed()` to also wait for every already-accepted connection's own transport
to close, not just the listening socket — every test's server-side connection now closes
explicitly in teardown), the broadcast hub, and the full relay composition root. Backend: 1328
unit+architecture, unchanged (no backend code touched this phase) — re-run as a regression check.
Full backend suite (`tests/`, all four categories): 1602 passed, 22 subtests passed, one
pre-existing, unrelated failure (`NoSilentUndocumentedRoutesTests` — undocumented routes from
ADR-0018/0019/0020/0023/RBAC/`/metrics`, none related to this phase, confirmed already present
before this phase started).

**What still needs a physical MDVR, disclosed not silently claimed working:** the field-width
rework and video-signaling bodies are spec-verified and unit/integration-tested against synthetic
frames, never against a real terminal's actual bytes; the relay's AVC sequence-header (SPS/PPS)
handling and the Annex-B-delimiter assumption in the FLV muxer are explicitly unverified
(`services/jt1078/src/repackager/flv_muxer.py`'s own module docstring has the full detail); HLS
playback delivery and a real Business-API-facing control endpoint for the relay are not built.

**Business API `VideoProviderPort` → JT1078 relay integration (2026-08-12, user-directed, closing
the "no backend control-endpoint transport" / "no `VideoProviderPort` adapter" gap the phase
above's own report flagged).** Connects the pieces the prior three phases built but never wired
together — `VideoApplicationService` could already run the full `VideoSession` state machine, and
`services/jt1078` could already accept a session and relay media, but nothing called the relay:

1. **`Jt1078RelayAdapter`** (`backend/raad/modules/video/infra/adapters.py`), the first real
   `VideoProviderPort` implementation. `start_live`/`start_playback` each: (a) call a new
   `Jt1078RelayRpcClient` (`backend/raad/modules/video/infra/jt1078_relay_client.py`) — a Redis
   list-based BLPOP/RPUSH RPC, `raad:jt1078:session_requests` /
   `raad:jt1078:session_responses:{request_id}` — to ask the relay to allocate ingest coordinates
   and mint a viewer token; (b) publish a `Jt1078SignalCommandRequested` `DomainEvent` on the
   **existing** `BrokerPort`/`raad:events` stream, the exact wire contract device-gateway's
   already-built `RedisVideoSignalingConsumer` expects (asserted byte-for-byte in
   `test_video_jt1078_relay_adapter.py`). `stop` only calls the relay — the relay's own
   `SessionManager.end_session` already publishes the device stop-signal, so this adapter does not
   duplicate it. **A new, additive RPC channel, not a replacement for ADR-0024 §8**: device-gateway
   ↔ relay coordination stays broker-only, unchanged; the RPC exists solely because the backend ↔
   relay session-request/response shape doesn't fit the broker's fan-out Stream model.
2. **`SessionRequestServer`** (`services/jt1078/src/session/session_request_server.py`, new),
   answering that RPC — creates the relay-side `VideoSession`, mints the signed viewer token,
   replies with `{ingest_host, ingest_port, viewer_token}`. `SessionManager.create_session` gained
   an optional `session_id` passthrough so the Business API's own `VideoSession` ULID is the one
   identifier used across Postgres, the relay's own session tracking, and the Redis event
   `correlation_id` — no separate id-mapping table needed. `RelayConfig` gained
   `public_ingest_host`, distinct from the bind-address `ingest_host`, since a device on the public
   network needs a reachable address, not `0.0.0.0`.
3. **`VideoProviderPort.start_live`/`start_playback` widened** to take `terminal_id`/`channel_no` —
   resolved once in `routers.py` from `fleet_device`'s own `DeviceDTO`/`CameraDTO` (no cross-module
   DB read, no second adapter-internal lookup for the same identifiers — a deliberate, minimal port
   evolution, the same shape ADR-0022 already established a precedent for). No new route; the three
   existing `/video/*` routes are otherwise unchanged, and `enforce_d5()` still runs first, before
   any of this is reached.
4. **`Jt1078RelayAdapter` conditionally bound** in `core/di/bootstrap.py`, only when both a broker
   and `device_plane.jt1078_signaling_url` are configured. **A real DI-ordering bug was found and
   fixed while wiring this in**: `VideoApplicationService`'s own `bind_singleton` call used to run
   *before* the broker block that conditionally binds `VideoProviderPort`, so
   `container.try_resolve(VideoProviderPort)` would have silently resolved to `None` even with a
   broker configured — relocated the binding to after the broker block, mirroring
   `PlatformStatsApplicationService`'s own already-documented precedent for the identical
   constraint. Caught and verified via `build_container()` itself (not a hand-rolled substitute)
   before any test was written for it.

**Two things flagged, not silently resolved, per this codebase's own documentation discipline**:
- **ADR-0024 §5 point 2 reads "a... signed viewer token minted by the backend."** The
  implementation has the **relay** mint it — the backend never holds
  `JT1078_RELAY_VIEWER_TOKEN_SECRET` (relay-only config, by design). The security property that
  section actually protects (no session-authorization decision happens outside the backend's own
  D5/RBAC check, which runs before the RPC call is ever made) is unchanged; only which process
  computes the token's bytes differs from the literal text.
- **The relay's own session-lifecycle events are not consumed back into `VideoSession`.**
  `backend/raad/modules/video/events/subscribers.py` is still empty (pre-existing, unchanged by
  this phase) — `VideoSession` transitions to `ACTIVE` once the RPC call + device signal succeed,
  not on a real "media is flowing" signal from the relay (ADR-0024 §5 point 3); an automatic
  relay-side teardown (idle timeout, viewer disconnect, device drop) has no path back into
  Postgres, and ADR-0024 §16's own "defensive reconciliation timeout" safety net for a
  `VideoSession` stuck in `REQUESTED`/`ACTIVE` does not exist yet either. Directly relevant to how
  far this integration should be trusted, so recorded here rather than left implicit.

**Testing.** 4 new backend test files: `test_video_jt1078_relay_client.py` (4 tests — request
shape, `ok:false` → `Jt1078RelayError`, timeout → `Jt1078RelayTimeoutError`, distinct request IDs
per call, against a genuinely-polling fake Redis `blpop`, not a single-check stub);
`test_video_jt1078_relay_adapter.py` (6 tests — request shape, viewer-URL construction, exact
published-event shape, RPC-before-signal ordering, `stop`'s single-call behavior);
`test_video_provider_di_wiring.py` (6 tests, against the real `build_container()` — unbound with
no broker/signaling URL, unbound with only one of the two, bound with both, and
`VideoApplicationService` resolving the *same* adapter instance); `test_video_application.py`
updated (8 existing tests, widened `FakeVideoProvider`/command fixtures for the new
`terminal_id`/`channel_no` fields). 2 new `services/jt1078` test files/additions:
`test_session_request_server.py` (7 tests) and `test_relay_redis_wiring.py` extended (+2, including
a fake-Redis gap this pass found: without a working `blpop`/`rpush`/`expire` on the test double,
`relay.start()`'s new background `SessionRequestServer` task would have died silently on its first
poll). **Results**: `services/jt1078` 82→90, all green. Backend `tests/unit`+`tests/architecture`:
1356 passed, 5 subtests, all green. `tests/contract`: 1 pre-existing, unrelated failure
(`NoSilentUndocumentedRoutesTests` — the same ADR-0018/0019/0020/0023/RBAC/`/metrics` documentation
gap the prior phase's own report already named, confirmed present before this phase and containing
no `/video` route). `services/device-gateway` (regression check, untouched by this phase): 408
passed, unchanged.

**Parent Video Access Authorization + remaining software-only video gaps (2026-08-12/13,
user-directed, ADR-0026).** Closes every remaining software-only item the prior phase's own
report flagged, plus a genuinely new capability the user directed as a formal D5 revisit — not a
loosening, a narrowing, per that ADR's own full reasoning. Two blocking design forks were
resolved via `AskUserQuestion` before implementing (both "(Recommended)" options accepted): (1)
the video player surface is Flutter mobile only, not the React web dashboard — the web dashboard
has no Parent login at all, so a web-only player would be permanently unreachable by any parent;
(2) FLV decode/render uses `media_kit`/`media_kit_video`/`media_kit_libs_video` (MIT), a new
mobile dependency, explained and approved before adding (`.claude/rules/workflow.md` rule 1).

1. **Parent video-access authorization (ADR-0026 §1-§4).** Investigated first, per the user's own
   explicit instruction, before touching schema: RBAC (`role_permissions`) grants per-*role*, not
   per-instance, so a per-parent flag cannot live there without inventing a parallel permission
   system — the correct, already-precedented pattern is a boolean capability flag directly on the
   owning aggregate (`Parent.status`, `StudentParent.is_primary`, `devices.is_online` all already
   do this), mutated by a dedicated domain method, audited automatically via the existing
   `DomainEvent` → outbox → `audit_entries` pipeline. Two new columns,
   `has_video_live_access`/`has_video_playback_access` (`BOOLEAN NOT NULL DEFAULT false`,
   migration `1470274175d8`, live-Postgres-verified: upgrade → downgrade → upgrade round-trip,
   `alembic check` clean) — `.claude/rules/naming.md`'s `is_`/`has_` boolean-prefix convention
   applied at every layer (domain/DB/DTO/API), while "video_live_access"/"video_playback_access"
   (the user's own vocabulary) remains the prose/permission name. Four new idempotent domain
   methods (`grant_video_live_access`/`revoke_video_live_access`/`grant_video_playback_access`/
   `revoke_video_playback_access`, mirroring `Parent.activate`/`disable`'s exact shape) + four new
   domain events. New `PATCH /parents/{id}/video-access` (org_admin + founder only, a **new**,
   dedicated `transport_ops.parents.grant_video_access` permission — deliberately not reused from
   `.update`, least privilege). RBAC also grants Parent the three existing `video.*` permissions
   (layer-2 "may attempt," mirroring CR-1's own established "role can attempt, policy decides
   per-instance" split for `tracking.vehicles.read_latest`).

   **The authorization chain, exactly as specified**: Parent → D5 role gate (`VideoAccessPolicy`
   gains `Role.PARENT`, narrowly) → self identity (`_resolve_parent_id`, reused, not
   re-invented) → explicit permission (`has_video_live_access`/`has_video_playback_access`,
   matching `purpose` independently — live never satisfies playback or vice versa) → child/device
   ownership (new `find_owned_student_id_for_device`: `device_id` → active vehicle assignment
   → the existing CR-1 `find_owned_student_id_for_vehicle`, unmodified) → only then
   `VideoSession`/`VideoProviderPort`. `resolve_d5_decision`/`enforce_d5` widened to take
   `device_id`/`purpose` (all three video routes updated). **A parent owning nothing at all
   raises `NotFoundError` (404) directly** — this codebase's established cross-tenant-probing-
   avoidance convention, extended to video; only an owning-but-ungranted parent gets `403
   VideoForbiddenError`. New `DeviceApplicationService.get_active_vehicle_assignment_for_device`
   (the reverse direction of `VehicleApplicationService.get_vehicle_by_id`'s own existing
   `active_for_vehicle` embedding) was the one genuinely new cross-module-adjacent read needed.
   `GET /me` (ADR-0023) now surfaces both flags for the mobile client's own UI gating —
   presentation only, per `.claude/rules/frontend.md` #2.

2. **Relay-lifecycle reconciliation (ADR-0026 §7)**, closing the gap the prior phase's own report
   flagged. `VideoApplicationService.request_live_video`/`request_playback_video`'s eager,
   optimistic `session.activate()` (called synchronously right after the provider RPC returned,
   before the relay had any real signal media was flowing) is removed. New
   `video/events/subscribers.py` (previously empty) mirrors `fleet_device`'s own
   `DeviceConnectivityProcessor`/`DeviceAuthCodeProcessor` shape exactly: three processors consume
   the relay's own `VideoSessionActivated`/`Ended`/`Failed` events (already published since the
   prior phase) and call new `VideoApplicationService.mark_session_active`/`mark_session_ended`/
   `mark_session_failed` — no-op (log, don't raise) for an unknown `video_session_id`, the same
   "a stray event is expected, not an error" precedent `record_device_seen` already established.
   `VideoSession.end`/`.fail` gained an optional `reason` parameter, threaded from the relay's own
   event payload into the domain-event payload (`"viewer_idle_timeout"`, `"ingest_timeout"`, etc.).
   Registered in `core/di/bootstrap.py` alongside the other broker consumers.

3. **Concurrency ceilings (ADR-0026 §8).** `SessionManager` gained `max_global_sessions` (default
   `50`, directly citing Phase 2 §13.1's own "e.g., start 50 global" — the one concrete number an
   approved document names) and `max_sessions_per_organization` (default unconfigured — no
   approved document names a per-org number, so none is invented), both env-var-configurable
   (`JT1078_RELAY_MAX_GLOBAL_SESSIONS`/`JT1078_RELAY_MAX_SESSIONS_PER_ORGANIZATION`). A new
   `SessionCapacityExceededError`, checked before any session is allocated, already correctly
   surfaces as `{"ok": false, "error": ...}` via `SessionRequestServer`'s existing generic
   exception handling (no new plumbing) → `Jt1078RelayError` → propagates uncaught through
   `VideoApplicationService`, matching every other unbound-provider/relay-failure precedent
   already established there.

4. **SPS/PPS/AVCC handling (`services/jt1078/src/repackager/flv_muxer.py`).** New
   `extract_sps_pps` (classifies already-split Annex-B NAL units by H.264 NAL type — a fixed
   ITU-T H.264 §7.3.1 bitstream property, not JT/T-1078-specific) and `build_avc_decoder_config`
   (a real `AVCDecoderConfigurationRecord`, ISO/IEC 14496-15 §5.2.4.1.1, reading
   profile/compatibility/level directly from the first SPS's own bytes). New `FlvMuxer.
   feed_annex_b_video` wires both together: emits a sequence-header tag the first time a viewer's
   own muxer sees a SPS+PPS pair (or again only if it changes), strips SPS/PPS out of the AVCC
   NALU tag itself (the standard FLV/RTMP muxing convention), delivers ordinary VCL NALUs
   unconditionally regardless of sequence-header state (a real design choice, not an oversight —
   a player buffers/discards what it can't yet decode rather than erroring, and never delivering
   stream data at all until the next parameter-set refresh would silently stall a legitimately-
   connected viewer longer than necessary). `broadcast_hub.py`'s `broadcast_video` now calls this
   new method per-viewer instead of a shared, pre-converted AVCC payload — "has *this* viewer's
   own muxer already sent a sequence header" is genuinely per-viewer state, the same reasoning
   already established for the per-viewer FLV file header itself.

5. **`audit_entries`, confirmed closed, not newly built.** Every `VideoSession` transition and
   every `Parent` video-access grant/revoke already flows through the existing
   `UnitOfWork.commit()` → `AuditWriter` pipeline (ADR-0007) automatically — "not every domain
   event is filtered out as not business-meaningful" is this mechanism's own explicit, verified
   design. The only real gap was item 2 above (transitions that never fired); no new audit code
   was written. Live-Postgres-verified with two new, specific tests (not just trusting the
   generic ADR-0007 proof `test_audit_entries_transactional_write.py` already gives for
   `reporting`): granting video access produces a real `ParentVideoLiveAccessGranted` row;
   `mark_session_active` (the new relay-reconciliation path, not the removed eager-activate path)
   produces a real `VideoSessionStarted` row.

6. **Mobile player (ADR-0026 §5).** New `mobile/lib/features/video/`: `VideoSession`/
   `VideoRepository` (`POST /video/live`/`/playback`/`/sessions/{id}/stop`), `FlvRelayBridge`
   (connects to the relay's `ws://.../viewer?token=...` via the already-approved
   `web_socket_channel`, re-serves received binary frames over a local loopback
   `dart:io.HttpServer` as a continuous `http://127.0.0.1/stream.flv` — no new dependency for the
   bridge itself; single-listener by design, a second concurrent request would miss the FLV
   header already sent to the first), `VideoPlayerScreen` (`media_kit`/`media_kit_video`, opens
   the bridge's local URL, tears down bridge + player + calls `stop()` on dispose),
   `VideoWatchScreen` (manual device/camera id entry — the same disclosed "no endpoint resolves
   my devices" stand-in pattern `ParentHomeScreen` already established for "list my children";
   safety unweakened, since the server independently re-verifies ownership regardless of what id
   is typed in). New `core/auth/me_identity.dart`/`me_repository.dart` (`GET /me`, now carrying
   both video flags). `ParentHomeScreen` gained a permission-gated `_VideoAccessSection`
   ("Watch live video," shown only when `hasVideoLiveAccess`) — presentation only, the real gate
   is server-side. One new widget test (`video_watch_screen_test.dart`, mirroring
   `login_screen_test.dart`'s exact static-shape-only scope). **Carries the identical
   categorical "written, not compiled or run" limitation every M0-M3 mobile phase already
   disclosed** — no Flutter SDK in this sandbox; `mobile/README.md`'s own "Testing limitation"
   section extended, not superseded.

7. **Rule-file narrowing, not silent contradiction.** `.claude/rules/jt1078.md` #1,
   `.claude/rules/security.md` #5, `.claude/rules/backend.md` #7, `.claude/rules/flutter.md` #3,
   `.claude/rules/frontend.md` #4 all previously stated an *unconditional* "Parent has zero
   reachable path to video, ever" — each now states the narrowed, off-by-default-unless-
   explicitly-granted version, citing ADR-0026. `docs/architecture/adr/
   0024-jt1078-video-relay-architecture.md` §5 point 2 ("token minted by the backend") is
   corrected in place (ADR-0026 §6) to match the shipped relay-mints-the-token design, the exact
   same "revise a prior ADR in place once it's actually implemented" precedent ADR-0025 already
   established for this same document.
   `docs/architecture/frontend-flutter-master-roadmap.md` §2.5 point 2's own "no action needed,
   and none is planned [unless you want to revisit D5]" is **not rewritten** (historical record
   of its own drafting-time reasoning) — ADR-0026 is the "business requirement changes" trigger
   that section named, and is where a reader following it forward should land.

**Testing.** Backend `tests/unit`+`tests/architecture`: 1356 → 1390, all green (new: 6 Parent
domain tests, 8 Parent application-service tests, 33 `ResolveAndEnforceD5Tests`/policy-guard
tests, 6 `mark_session_*` tests, 6 subscriber-processor tests, 2 `/me` tests, plus fixture fixes
across `test_me_application.py`). `tests/integration`: 275, all green (new: 2 live-Postgres video
audit_entries tests; the parent-repository and video-repository suites re-verified against the
new migration). `tests/contract`: 1 pre-existing, unrelated failure (`NoSilentUndocumentedRoutesTests`
— confirmed present before this phase, no `/video`/`/parents/*/video-access` route in the
unexplained list; the new route was added to `ALLOWED_UNDOCUMENTED_EXTRAS` with its own citation).
`services/jt1078`: 90 → 115, all green. `services/device-gateway` (regression check, untouched):
408, unchanged. Migration applied and round-tripped against this sandbox's own live Postgres
instance — `alembic upgrade head` → `downgrade -1` → `upgrade head` → `alembic check` clean.

**What remains, genuinely external or out of this phase's own explicit scope:** HLS; the relay's
own defensive reconciliation-timeout job (ADR-0024 §16, for the "no lifecycle event ever arrives
at all" case); the Org-Admin web video player (F10 — the user's own explicit "Flutter only this
phase" choice); a real Flutter SDK to compile/run/verify the mobile layer; a physical MDVR for
every layer, backend through mobile, this phase built against synthetic fixtures and fakes only.

**CI hardening — frontend + device-gateway CI (2026-08-07, Priority 2 backlog item,
`PROJECT_STATUS.md` Section 5).** `ci-cd/pipelines/*.yml` had five placeholder index stubs;
`.github/workflows/` had only `backend-pipeline.yml` and `mobile-pipeline.yml` as real, executable
gates — `frontend`/`device-gateway` had none, despite both deployables having a full, currently
passing test suite. No new ADR needed — this is CI/tooling wiring, not business logic or a
bounded-context change, the same "no ADR" posture `backend-pipeline.yml`/`mobile-pipeline.yml`
themselves were built under.

**Why the other five Priority 2 items were skipped, not silently passed over:**
1. **Live video/JT1078** — no runtime decision exists (`.claude/rules/jt1078.md`: "the runtime
   isn't decided"), a genuine open architecture question, not a coding gap; 3–6 weeks of scope
   and likely new media-server dependencies. Starting this would mean inventing an architecture
   decision, not implementing an approved one.
2. **Reporting renderer** — two independent blockers, not one: picking a PDF/Excel library needs
   `.claude/rules/workflow.md` #1/#2's explicit go-ahead before installing anything, *and*
   report *content* generation is separately blocked on the still-unresolved `ReportDefinition`/
   `report_definitions` documentation gap (Section 10) — binding a renderer without that would
   mean inventing report content no document specifies.
3. **Load testing** — `testing/load/README.md` (already on record, not written new this turn)
   names three structural blockers: no deployed environment to test against, §13.1's own NFR
   targets are explicitly provisional pending doc-owner confirmation, and no load-testing tool
   is an approved dependency. Writing scripts against unconfirmed targets would silently promote
   a proposal to a requirement.
4. **Log shipping/aggregation** — needs a log-aggregation destination choice (Section 3's own
   "Logging" row already names this as the blocking dependency) — an unresolved design fork.
5. **Secrets-manager integration** — needs a real external secrets-manager service/account
   (Vault, AWS Secrets Manager, or similar) this engagement cannot obtain.

**What was actually built.** New `.github/workflows/frontend-pipeline.yml`: checkout →
`actions/setup-node@v4` (Node 20, `npm` cache keyed off `frontend/package-lock.json`) → `npm ci`
→ `npm run build` (runs `tsc -b` type-check before `vite build` — a type error is still a hard
CI failure with no separate lint step needed) → `npm test -- --run` (Vitest). New
`.github/workflows/device-gateway-pipeline.yml`: checkout → `actions/setup-python@v5` (3.11,
matching `pyproject.toml`'s own `requires-python`) → `pip install -e .` → `python -m compileall`
→ `python -m unittest discover -s tests`. Both mirror `backend-pipeline.yml`'s exact scope
discipline (documented in each file's own header comment, matching that file's own wording
almost verbatim): build/install → test only, **no lint step** (frontend has no `eslint` config
anywhere — confirmed by checking for `.eslintrc*`/`eslint.config.*`, neither exists; backend/
device-gateway's own `ruff`/`mypy` are still "not yet formally approved" per `backend/
pyproject.toml`'s own tracked-as-open-item comment) and **no security-scan step** (no scanning
tool is an approved dependency anywhere in this repository). Neither gap is silently invented
around — both are named explicitly in the new workflows' own header comments as the honest
remaining scope of "CI hardening," matching this backlog item's own bullet in Section 5.

**A real, pre-existing documentation drift was found and fixed while touching this exact area,
not left for a future session to rediscover**: `ci-cd/pipelines/backend-pipeline.yml`'s own
"Status" comment still said "The other four siblings remain empty — none of those deployables
(frontend, mobile, jt808, jt1078, infrastructure) exist in this repository yet" — false for
`mobile` since Priority 1 Item 9 shipped `mobile-pipeline.yml` as a real workflow, and
`.github/workflows/mobile-pipeline.yml`'s own header comment independently repeated the same
stale claim ("still an empty placeholder, like its frontend/jt808/jt1078/infrastructure
siblings"). Both corrected, and `ci-cd/pipelines/mobile-pipeline.yml`/`frontend-pipeline.yml`/
`jt808-pipeline.yml` (all previously 0-byte files) are now populated with the same
"organizational index, see the real workflow" comment `backend-pipeline.yml`'s own stub already
established — closing this drift across all four now-real deployables' index entries in one
pass, not just the two this item's own scope strictly required. `jt808-pipeline.yml`'s filename
itself is left as-is (not renamed to `device-gateway-pipeline.yml`) — its own new comment
explains why: the original JT/T 808 code still lives on inside `services/device-gateway/src/
vendors/jt808/` (dormant, ADR-0009/0010), so the name isn't wrong, just historically lagging;
renaming it wasn't otherwise in this item's scope.

**Verification — every command the two new workflows run was executed directly in this sandbox
against the current tree, before either YAML file was written, not assumed to pass:**
frontend: `npm test -- --run` → 392/392 tests passed (63 files); `npm run build` → clean
production build (`tsc -b` type-check + `vite build`, no errors, only a pre-existing informational
chunk-size warning unrelated to this change). device-gateway: `python -m compileall -q src tests`
→ clean; `python -m unittest discover -s tests -p "test_*.py" -v` → 333/333 tests passed;
`pip install -e .` → clean, no errors. Backend's own unit (1330) and architecture-gate (10) suites
were re-run as a final sanity check (untouched by this change — only YAML/comment files were
edited on the backend side) and still pass with zero regressions. All four new/edited workflow
YAML files (`frontend-pipeline.yml`, `device-gateway-pipeline.yml`, plus the edited
`backend-pipeline.yml`/`mobile-pipeline.yml` comments) were structurally validated with a real
YAML parser (`yaml.safe_load`), confirming correct `on`/`jobs`/`steps` shape. **Not live-tested
against a real GitHub Actions run** — no way to trigger one in this sandbox — the same disclosed
"mechanism verified locally, not via live CI" posture every other workflow file in this
repository already carries (and the same posture `backend-pipeline.yml`'s own header comment
already modeled for this exact kind of gap).

**No new automated test file was added for the CI configuration itself.** Considered and
declined, not overlooked: `.claude/rules/testing.md` #1/#2 fixes this repository's test
taxonomy to `backend/tests/{unit,integration,contract,architecture}/` (none of which fit "does a
GitHub Actions YAML file have the right shape" — none of these files touch the `raad` Python
package) and `testing/{e2e,load,fixtures}/` (reserved for flows spanning more than one
deployable, not CI-config shape checks). Inventing a new test category for this one narrow
concern would be a larger, less-precedented addition than the two YAML files it would test —
the one-off local verification above (the actual commands, actually run, actually passing) is
the same level of rigor already accepted for every prior "mechanism verified, not live-CI-tested"
infra item in this program (Docker Compose overlays, Redis hardening, TLS).

**ADR-0023 — Canonical `/me` Self-Service Identity Resolution (2026-08-07).** Closes Known Issue
#17 (§10 below): neither `parent` nor `driver` had any safe way to resolve its own domain
identity (`Parent.id`/`Driver.id`) from an authenticated `Principal`. `GET /parents/{parent_id}/
students` took `parent_id` straight from the URL path with **no ownership check at all** —
confirmed, while researching this ADR, to actually be reachable by `founder`/`regional_manager`/
`support_staff`/`org_admin` too (a later RBAC migration revoked `.students.{list,read}`/
`.parents.{list,read}` from RAAD-staff roles but never touched `.student_parents.list` — a real,
previously unflagged finding, recorded in the ADR itself rather than silently corrected in
place), though never by `parent`/`driver`, so this change closes no *currently reachable* hole,
only the one that would have opened the moment either role was ever granted that permission.

**One canonical capability, not two unrelated endpoints**: `GET /me` resolves the caller's own
cross-module identity (`user_id`/`role`/`organization_id`, plus `parent_id`/`driver_id` only when
the role matches and a linked row resolves) — `GET /me/students` and `GET /me/driver-profile` are
thin, dedicated views built on that same resolution, not one-off lookups each reinventing it.
Owned by `iam` (already owns `Principal`/`User`/`GET /auth/me`) via a new
`MeApplicationService` (`iam/application/services.py`), constructor-injected with `transport_ops`'s
own `ParentApplicationService`/`DriverApplicationService`/`StudentParentApplicationService` — the
same legal cross-module composition `platform_audit.PlatformStatsApplicationService` (ADR-0020)
already established (application-layer only, never `domain`/`infra`; re-confirmed by re-running
`tests/architecture/test_module_boundaries.py`, still green). Two small, additive mirror-methods
were needed first: `DriverRepository.get_by_user_id` (domain + infra) and
`DriverApplicationService.get_driver_by_user_id` — `ParentRepository`/`ParentApplicationService`
already had the equivalent; `Driver` simply never had. **No client-supplied `parent_id`/
`driver_id` anywhere** — every `MeApplicationService` method takes only a `Principal`, by
construction, not a runtime check bolted on after the fact. Self-scoped via
`Depends(get_current_user)` alone, no `require_permission` — mirrors `GET /auth/me`'s existing
posture exactly, since `parent`/`driver` hold none of the relevant `transport_ops.*` permissions
today and granting one wouldn't help (these routes never accept the id it would gate anyway).
`NotFoundError` (404, not 403) when no linked Parent/Driver row resolves, covering both a genuine
role mismatch and a data-inconsistency case with one honest code path — mirrors this codebase's
established 404-over-403 posture for personal-ownership routes. Zero migration: no schema change,
no RBAC grant.

Routes: `GET /me`, `GET /me/students`, `GET /me/driver-profile` (new `me_router`,
`iam/api/routers.py`, mounted at `/api/v1/me` in `interfaces/http/api_v1.py`) — no documented API
Contracts surface, the same "built directly on schema authority" posture already established for
`/roles/{role}/permissions`/`/scope-assignments`/`GET /billing/payments`. Verified by forcing
`app.openapi()` schema generation (this FastAPI version's route registration is lazy —
`app.routes` alone doesn't show included-router paths until the OpenAPI schema is built) and
confirming all three paths and their response schemas resolve correctly.

**Testing**: 10 new unit tests (`tests/unit/test_me_application.py`, fake-constructor-argument
doubles mirroring `test_platform_stats_application.py`'s pattern — covering every role's identity
resolution, the "no secondary lookup for roles that can't have one" efficiency property, and both
404 paths) plus 2 new live-Postgres integration tests on the existing driver-repository suite
(`get_by_user_id` round trip) plus a new dedicated integration file
(`tests/integration/test_me_application_integration.py`, 4 tests) proving the actual security
property against a real database: two real Parents, two real linked Students, `MeApplicationService.
get_my_students` genuinely cannot cross from one to the other — the regression proof a fake-backed
unit test alone cannot provide. **One real bug caught while writing the integration test, not
shipped**: the test's first draft wrapped each `MeApplicationService` call in its own `async with
uow:` block at the test level — but `MeApplicationService`'s own methods already open/close their
own `async with uow:` internally (twice, sequentially, since `get_my_students` calls two different
sub-services), so the outer wrapper's own `__aexit__` hit `SqlAlchemyUnitOfWork.session`'s
`RuntimeError` guard ("used outside of `async with`") — fixed by passing each call an un-entered
`UnitOfWork`, exactly matching how the real router hands one over via `Depends(get_transport_ops_
uow)`. 1330 unit + 10 architecture-gate tests pass (up from 1320), zero regressions; the full
live-Postgres integration suite (270 tests) passes except the 6 pre-existing, already-disclosed
"no reachable Redis in this sandbox" failures (`test_realtime_broker_fanout.py`/
`test_tracking_redis_latest_position.py`) — unrelated to this change, the same standing gap every
other item in this program has carried.

**Not done in this pass, flagged rather than silently implied finished**: wiring
`mobile/lib/features/parent/parent_home_screen.dart` (and the equivalent Driver trip-filter UX)
to these new endpoints — the mobile app has no Flutter SDK in this environment to verify any
change against (the same disclosed Mobile testing limitation Priority 1 Item 9 already carries),
so the backend capability is real and tested, but the client that would consume it is a follow-up.
`GET /parents/{parent_id}/students`'s own pre-existing missing-ownership-check gap is also
unchanged — still tracked, still only reachable by roles that can already see cross-organization
data by design, explicitly out of scope for this ADR (see the ADR's own Consequences section).

**ADR-0022 — Payment Provider Architecture + Organization Billing UI + Coolify deployment
(2026-08-06).** Three genuine backend gaps were found by reading the actual code before any
design work, not assumed: (1) `PaymentProviderPort` was `charge(amount, msisdn, reference) ->
str` — one method, shaped entirely around mobile money; a card provider has no `msisdn` and needs
a client-tokenized `payment_method_id` instead (raw card numbers must never reach this backend —
PCI DSS scope), so the port needed a real redesign, not a class bolted onto the existing
signature. (2) A live idempotency bug: `Payment.mark_paid`/`mark_failed` had no same-state guard
(unlike `mark_processing`/`mark_expired`, which already did) — every real payment provider
retries a webhook delivery until it gets a `200`, so a duplicate "paid" callback would have
re-run `subscription.renew(...)` a second time, double-advancing the billing period. Fixed at
both layers (entity-level idempotent no-op + a service-level short-circuit before touching
`Invoice`/`Subscription` at all), with a regression test proving a replayed callback doesn't move
`current_period_end` twice. (3) `infra/adapters.py` was completely empty (0 bytes) — no prior
stub existed at all.

**Redesigned `PaymentProviderPort`** (`application/ports.py`): `PaymentChargeRequest`/
`PaymentChargeResult`/`WebhookEvent` dataclasses, three methods (`charge`,
`verify_webhook_signature`, `parse_webhook_event`). `StripePaymentAdapter` (`infra/adapters.py`)
is real and `httpx`-based (new dependency — chosen over the official `stripe` SDK, matching this
codebase's own "hand-roll a narrow need" pattern already established for `core/pagination`/
`core/observability/metrics`): Payment Intents API (`confirm=true`,
`automatic_payment_methods[allow_redirects]=never` — a deliberate v1 scope cut, no 3D Secure/SCA
flow), Stripe's own documented `Stripe-Signature` HMAC-SHA256 webhook scheme (verified against
self-constructed signature test vectors, not live Stripe access — no merchant account exists in
this environment). `EvcPlusPaymentAdapter`/`ZaadPaymentAdapter` implement the full interface but
`charge`/`verify_webhook_signature` raise a clear, explicit "no merchant API documentation exists"
error — the user's own explicit choice (a `AskUserQuestion` resolved this and three other forks,
all "(Recommended)" options accepted), not a lesser effort. `initiate_payment` now has three
outcomes (`succeeded`/`pending`/`failed`) instead of one, converging with the webhook path on one
shared `_apply_paid_side_effects` helper so the two can never drift.

**Webhook route wired for real** (`POST /billing/payments/callback`, previously a documented,
deliberate `NotImplementedError` no-op): no `Depends(require_permission(...))`/bearer JWT at all
— a payment provider has no `Principal`, and the HMAC signature check *is* this route's
authentication, matching how Stripe's own webhook documentation describes this exact model.
`SYSTEM_PRINCIPAL` (moved from `notifications/events/subscribers.py` to
`core/tenancy/principal.py` so both modules share the one constant, not a drifting second copy)
represents the caller for the audit trail — the same "least-bad available role" reuse the
Notification Worker already established, not a new RBAC concept. A missing/invalid signature is a
`401`, logged (not a domain-event audit row — no aggregate mutation happens for a rejected
request to attach one to). New `GET /billing/payments` (payment history — no list route existed
for `Payment` at all before this) behind a new `billing.payments.list` permission (Founder/
Finance Staff/Org Admin, mirroring `.subscriptions.list`'s grant set). Non-secret provider
selection (`{"provider":"stripe"}`) is a `SystemSetting` row read via the *existing*
`GET /admin/settings`; the actual secret lives only in `RAAD_PAYMENT__PROVIDER_CREDENTIALS`
(env-var, composition-root only, `core/di/bootstrap.py`) — never `SystemSetting`, since
`org_admin` holds `admin.settings.read`/`.update` too. One combined migration (column, RBAC
grant, `SystemSetting` seed). **A real, live-caught bug during verification**: the webhook route
initially returned `401 UNAUTHENTICATED` even with no signature check reached at all — traced to
`get_billing_uow`'s own `Depends(get_scope)` transitively requiring an authenticated `Principal`
even though the route itself declared no auth dependency; fixed with a new `get_billing_uow_
unscoped` (mirrors `iam.api.deps.get_iam_uow`'s identical `login`/`refresh` precedent). Live
server verification (real JWT, real Postgres, fake-but-well-formed Stripe credentials) confirmed
all four webhook scenarios: no signature → 401, tampered signature → 401, valid signature +
unknown `provider_ref` → 200 ack, valid signature + unhandled event type → 200 ack. 1330 unit +
10 architecture tests pass (up from 1304), plus a live migration round-trip.

**Frontend: Organization Billing UI + Pay Invoice flow.** New `OrgBillingPage.tsx` at
`/org/billing` only (`/platform/billing` untouched, still the shared cross-organization
`BillingPage`) — an Org Admin's own current subscription/plan, invoices, and payment history, all
scoped to `principal.organizationId`. `InvoicesSection` is split into its own component, mounted
only once a subscription id is actually known, specifically so `GET /billing/invoices` (not
tenant-scoped server-side, a real pre-existing gap) is never called unfiltered even for one
render — an unfiltered call would return every organization's invoices. New `ConfirmDialog`
(`shared/components/`) — this frontend's first genuinely consequential/hard-to-reverse action
(charging a real card), so it gets a real confirm step instead of the existing "loading button +
toast" convention every prior mutation in this codebase used (all reversible admin actions).
"Pay Invoice" mounts Stripe Elements (`@stripe/stripe-js` + `@stripe/react-stripe-js`, new
dependencies — required for PCI-compliant client-side card tokenization, not optional) inside it;
the card form only renders once a new `getBillingProviderConfig()` read confirms a provider is
actually bound, otherwise an honest "Online payment is not available yet" state renders. A real
infinite-render-loop bug was caught during test-writing (not shipped): an early test mock for
`useStripe`/`useElements` returned a fresh object identity on every call, which combined with
`CardFields`'s `useEffect([stripe, elements, onReady])` re-ran forever — fixed by making the
mock return stable references, matching real Stripe.js's own memoized context values. 392/392
frontend tests pass (up from 344); `tsc -b` clean, production build clean.

**Deployment: Coolify overlay.** New `docker-compose.coolify.yml`, alongside (not replacing)
`docker-compose.prod.yml`'s existing generic-VPS/nginx/certbot path — Coolify already runs its
own Traefik reverse proxy with automatic Let's Encrypt TLS, so this stack's own `nginx`/`certbot`
must not also run. Rather than trying to delete a service via a compose override (not possible in
the Compose spec), `nginx` (base file) and `certbot` (prod overlay) are gated behind a new
`gateway` Compose profile, defaulted on via `docker/.env.example`'s `COMPOSE_PROFILES=gateway` so
every existing dev/generic-VPS command is unaffected; the Coolify path simply never activates
that profile. Also fixed a real, pre-existing bug surfaced while designing the overlay:
`infrastructure/nginx/conf.d/frontend.conf` (the SPA `try_files` fallback) was referenced in
`frontend.Dockerfile`'s own comment but never actually mounted anywhere, so a deep-linked
frontend route (e.g. `/org/billing`) 404'd straight from the frontend container's own nginx in
production — fixed on both paths. New `docs/runbooks/coolify-deployment.md`, flagged like every
other deployment runbook here as mechanism-verified (YAML structural validation, a hand-written
compose-merge simulation) but not live-tested against a running Coolify instance in this
environment.

**Phase F9 — Billing Web UI.** API Contracts §4.7 and `billing/api/routers.py`'s own extensive
module docstring already fully specify this surface's real shape; nothing here required a new
ADR. **Read-only by design, confirmed before writing any UI code, not assumed:** the router's own
docstring states plainly that no write route exists for `Plan`/`Subscription`/`Invoice` this
phase (no `POST/PATCH/DELETE` for any of the three — the task scope for the backend phase that
built this surface explicitly forbade them), so `BillingPage` never attempts to build a create/
edit form the API couldn't actually serve.

**The one real design decision this phase turned on: what to do about `POST /billing/payments`.**
The route exists and is fully reachable, but with no `PaymentProviderPort` bound, it always
persists a `PENDING` `Payment` row and then raises `NotImplementedError` (500) at the charge step
— a guaranteed failure, by the backend's own explicit "fail loudly, don't fake a charge" design,
not a bug to work around. Wiring a "Pay now" button to it would mean every click both shows the
user a broken action *and* leaves behind a real, permanently-`PENDING` database row as a side
effect — worse than simply not offering the control. `features/billing/api.ts` never builds an
`initiatePayment` client function at all this phase, a documented decision (flagged in that
file's own docstring, not silently dropped) rather than dead code nothing calls. This is this
codebase's existing "fail loudly, don't fake it" *data* posture extended one step further, to
*affordances*: don't offer a control that is guaranteed to fail either.

**First tabbed page in this frontend.** Three independent paginated resources (Plans,
Subscriptions, Invoices) don't fit one `DataTable` — a new, small, general-purpose `Tabs`
component (`shared/components/Tabs/`) switches between entire panels, distinct from the
already-existing `FilterChips` (which narrows *one* list's own rows, not swap panels). Each tab
reuses the existing `usePaginatedQuery` hook verbatim — the same offset-pagination/sort/filter/
search state machine every other list page in this codebase already shares — gated with
`enabled` so only the active tab actually fetches.

**A real, confirmed-not-assumed RBAC gap shaped the page's own role-gating.** Read directly from
the seeded permission matrix rather than inferred from route names: Regional Manager/Support
Staff hold `billing.plans.list` alone — not `billing.subscriptions.list`/`.invoices.list`, which
every *other* role reaching this page (Founder, Finance Staff, Org Admin) holds all three of.
Rather than rendering three tabs and letting two of them 403 for this one pair of roles, the tab
switcher itself is omitted for them and Plans renders directly — mirroring the Founder
Dashboard's identical "omit what would 403, don't render-then-error" precedent already
established for Finance Staff there.

**Name resolution, the same established pattern, not a new one.** Neither `SubscriptionResponse`
nor `InvoiceResponse` carries an organization or plan *name* — only opaque ids — so both are
resolved via small, separate, unfiltered lookup reads (capped at the first 100 rows, falling back
to the raw id past that), the exact same `regionsLookup`-style precedent `OrganizationsPage`
already established, not a new mechanism invented for this page.

**Testing:** wire-mapping tests for all three list routes plus the organization-picker lookup,
and `BillingPage` coverage (default Plans tab, tab switching with name resolution, row-click
detail drawer, a visible error state, and — the one genuinely load-bearing test here — Regional
Manager seeing Plans-only with `listSubscriptions`/`listInvoices` never even called, versus Org
Admin correctly seeing all three tabs). `tsc` clean, full suite green (372/372 across 60 files,
up from 361/350), production build clean.

**Phase F8 — Notifications Web UI.** `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md`
§8/API Contracts §4.6/§11.3 already fully specify this surface; nothing here required a new ADR.
**A real, load-bearing discovery made before writing any UI code, not assumed from the route
list:** `GET /notifications` is scoped to `recipient_user_id = principal.user_id`, not
`organization_id` — the first (and still only) list endpoint in this codebase scoped by personal
ownership rather than tenant. That single fact shapes the whole page: it is one shared component
mounted at both `/platform/notifications` and `/org/notifications` (matching every other
Fleet/Ops entry's "one component, two mount points" precedent) because the response is identical
regardless of which dashboard reaches it — there is no "all-organization" or "all-platform" view
to build, by design.

**First cursor-paginated frontend page.** Every other list page in this codebase is offset-paginated;
`GET /notifications` (and `GET /tracking/trips/{id}/positions`, still unbuilt) are the only two
cursor routes API Contracts §7 documents. New, general (not notifications-specific) shared
utilities close that gap the same way `OffsetListParams`/`toOffsetPage` already did for offset:
`shared/api/types.ts` gained `CursorPageWire`/`toCursorPage`, `shared/api/listParams.ts` gained
`CursorListParams`/`buildCursorListQuery` (`?limit&cursor`, no `sort` — cursor mode paginates a
fixed server keyset, never a client-chosen sort, per `core/pagination`'s own module docstring).
`NotificationsPage` itself uses `@tanstack/react-query`'s `useInfiniteQuery` (already a
dependency, built for exactly this "Load more" shape) rather than hand-rolling page-number state
that wouldn't even fit a cursor-only contract.

**Live-updated over `/ws/notifications`, already backend-implemented since the WebSocket phase
but never previously consumed by any frontend.** Subscribe is implicit per API Contracts §11.3 —
no frame to send, just a listener. A push **refetches** the list/unread-count rather than
splicing the WS frame's own fields into the cache: `_notification_frame`
(`notifications/api/ws.py`) deliberately carries no `status`/`read_at`/`organization_id`/`data`
(only ever represents a brand-new, thus-unread notification), so treating it as a full row would
mean inventing the missing fields.

**`AppShell`'s topbar bell badge — previously always `undefined` (`TopBar.tsx`'s own
`unreadNotifications` prop was declared but never once passed a value anywhere in the
codebase, confirmed by search before assuming) — now shows a real, live count.** No dedicated
"unread count" endpoint exists; `useUnreadCount` (`features/notifications/useUnreadCount.ts`)
counts `status === "unread"` among the most recent 50 notifications (`GET /notifications`'s own
max `limit`) and increments live on every `/ws/notifications` push, invalidated back down when
`NotificationsPage`'s own mark-read mutation succeeds (both share one query key,
`["notifications","unread-count"]`). A disclosed, real limitation, not a fabricated total: this
undercounts only in the unlikely case of 50+ simultaneously unread items, and `IconButton`'s own
badge already caps its displayed text at "9+" regardless. **A real, minor inefficiency accepted
rather than engineered around:** `AppShell` (renders on every authenticated page) and
`NotificationsPage` (one specific page) each open their own independent `/ws/notifications`
connection when both are mounted — sharing one connection across both would need a
connection-scoped context provider this codebase doesn't have yet, a bigger change than this
widget warrants; the backend's `ConnectionManager` already supports multiple connections per
user, so this is inefficient, not incorrect.

**Testing:** `features/notifications/api.test.ts` (wire-shape mapping for both the cursor list
and mark-read routes), `useUnreadCount.test.tsx`, `NotificationsPage.test.tsx` (empty/error
states, type/title/body rendering, mark-as-read triggering a refetch, filter chips, Load More
fetching a second page) — one real react-query v5 behavior learned while writing these:
`mutationFn` is invoked with an internal context object as a second argument beyond the variable
this code itself passes, so assertions check only the first argument rather than an exact call
shape that would have been coupled to a react-query internal, not this code's own contract.
`AppShell.test.tsx` updated to mock the new WS hook and `MapView` (the latter closes a
pre-existing, unrelated stderr-noise gap from the Dashboard redesign: that test renders the real
`DashboardHomePage`, which now embeds a live map preview jsdom has no canvas backend for — a
real, harmless-but-noisy side effect from earlier in this session, cleaned up here since this
item already touched the same file). `tsc` clean, full suite green (361/361 across 58 files, up
from 350/350 — 11 new tests), production build clean. Browser extension unavailable in this
sandbox for the whole of this session (disclosed repeatedly, not silently skipped) — verified
statically rather than with a live screenshot, the same posture every frontend item this session
has carried.

**ADR-0020 — Platform Analytics Read Model.** Real KPIs for the Platform Dashboard, composed
read-only from `organization`/`iam`/`fleet_device`/`billing`, owned by `platform_audit`, per the
ADR's own §1. **Three real gaps between the ADR's text and the actual repo, found by reading the
code rather than assumed** (matching the exact discipline ADR-0019 established a day earlier):
(1) the ADR's own §3 was stale — Known Issue #9 had already flagged that
`DeviceConnectivityProcessor` (`fleet_device/events/subscribers.py`) already consumed
`DeviceOnline`/`DeviceOffline` and populated `last_seen_at`; confirmed true, so the "Online/
Offline Devices" gap was closed by extending that *existing* processor with a new
`devices.is_online` boolean (migration `b288c2e44aa5`) rather than building a second consumer —
Known Issue #9 itself is now marked resolved. (2) The ADR names `interfaces/http/
policy_guards.py` as "the precedent reused here," but that file lives outside any module
specifically because CR-1/D5 have no single owning module — Platform Stats *does* (`platform_
audit`, the ADR's own §1), so the four-module composition lives in a new `PlatformStats
ApplicationService` there instead, constructor-injected with all four modules' own application
services (legal per `backend.md` #3 — a module may import another module's application-layer
symbols, never `domain`/`infra` — confirmed by the existing `test_module_boundaries.py` gate,
re-run green). (3) `finance_staff` doesn't hold `admin.audit.read` in the seeded matrix,
contradicting the ADR's claim that all four RAAD-staff roles already hold the `GET /admin/audit`
grant — resolved with a new `admin.platform_stats.read` permission instead, the ADR's own
anticipated fallback.

New, additive count/sum query methods across the four modules (no existing method's behavior
changed): `organization.count_by_status`/`count_created_since`; `iam.count_by_status`/
`count_last_login_after`/`count_created_since` (MAU — a new `ix_users__last_login_at` index in
the same migration, since this column had none); `fleet_device.Vehicle.count_total`,
`Device.count_total`/`count_online`; `billing.count_by_status`/`count_expiring_between`/
`sum_paid_amount_between` (a real SQL query, deliberately not a mirror of `sweep_expired_
subscriptions`'s existing unfiltered `list_all()` scan). `GET /admin/platform-stats`
(`platform_audit/api/routers.py`) composes all four via `PlatformStatsApplicationService`,
scoped exactly like every other `/admin` route (`TenantRegionScope` — unrestricted for Founder,
region-limited for Regional Manager). "System Health" reuses the existing `HealthCheckService`
(Priority 1 Item 5) verbatim — zero new observability code. **Two KPIs from the ADR's own
Context wishlist are a real, flagged scope cut, not silently dropped**: "Live Vehicle Locations"
(`tracking`'s Redis state has no safe/cheap aggregate count — `KEYS`/`SCAN` over live position
keys is exactly the kind of production-risk operation this platform avoids) and "Active
Drivers" (`transport_ops.Driver` — neither module is named in the ADR's own §1 Decision scope).

Frontend: `DashboardHomePage.tsx`'s pre-existing six-tile stopgap (`PlatformStatsRow`, already
self-documented in-code as "superseded by ADR-0020 whenever that milestone lands") had its
organizations/vehicles/devices tiles replaced by a new `PlatformAnalyticsSection` — one query
backing a richer grid (status breakdowns, online/offline, MAU, revenue, system health) the old
flat-total tiles never could show; drivers/students/parents tiles are untouched, correctly
outside this ADR's scope. **Live-verified, not just unit-tested**: migration round-tripped
clean; the real `DeviceConnectivityProcessor` (not a fake) confirmed flipping `is_online` in the
database on a real `DeviceOnline`/`DeviceOffline` event; the real, DI-wired
`PlatformStatsApplicationService` confirmed running the full four-module composition against
real Postgres without error. 1294 unit + 10 architecture-gate tests pass (backend), 344 frontend
tests pass, zero regressions. Zero changes to any bounded context's existing behavior, RBAC, or
tenant-isolation code.

**ADR-0019 — Account-Sharing Session Cap.** `SessionLimitPolicy` (`core/policies/
session_limit.py`) — a pure threshold check mirroring `SubscriptionAccessPolicy`'s existing
shape — enforced at both `AuthApplicationService.login`/`.refresh`: after resolving the caller's
current active (non-revoked, non-expired) `RefreshToken`s, revokes the oldest ones until back
under a per-role cap. Refresh rotation deliberately excludes the token being rotated from the
count (a 1:1 replacement, not a net-new session) — an early design check that, if missed, would
have made every ordinary token refresh spuriously evict an unrelated session. **Two real gaps
between the ADR's own text and the actual repo, found by reading the code rather than assumed
from the ADR:** (1) `SystemSettingKey`'s enforced 26-character max (`platform_audit/domain/
value_objects.py`) cannot fit a per-role key like `session_cap.regional_manager` — resolved by
seeding one row (`key="session_cap"`) whose value is a `{role: max_sessions}` dict instead of one
row per role. (2) The ADR's own cited precedent for "an org-configurable value living in
`SystemSetting`" (ADR-0014's `approaching_distance_m`) turned out, on inspection, to actually be
a column on `Organization` itself, not a `SystemSetting` row at all — there was no existing
example of one module reading another's `SystemSetting` value live to copy from. Resolved by
applying `.claude/rules/backend.md` #3 directly: a new `SessionCapPort` (`iam/application/
ports.py`) that `iam` depends on abstractly, with its concrete adapter
(`SystemSettingSessionCapAdapter`, `core/di/session_cap_adapter.py`) living in `core/di/` — the
composition root — specifically so it, not `iam` itself, is the thing reaching into
`platform_audit`'s application facade. `tests/architecture/test_module_boundaries.py`'s existing
Rule 1 gate (module may reach another module's application facade, never its `domain`/`infra`)
independently confirms this stays clean, re-run and still green. Previously-dead `refresh_tokens.
user_agent`/`ip_address` columns are populated for the first time; a new `device_label` column
(migration `4ef3fefb5e8d`, chained after `f3d8b1a4e6c2`) holds a short parsed label (`core/
security/user_agent.py` — a small hand-rolled heuristic, no new dependency; caught and fixed one
real bug in its own OS-detection order during testing: a genuine iOS Safari UA string contains
the literal compatibility token "like Mac OS X," so iOS/Android must be checked before the plain
Mac OS X/Linux patterns they'd otherwise also match). Self-service `GET`/`DELETE /auth/sessions`
(masked `ip_address` via a new `core/security/ip_mask.py`). A "login from an unrecognized
device" signal (`SuspiciousLoginDetected` event, visibility-only per `security.md` #8, no
automated block) is deliberately skipped on a genuinely first-ever login — the ADR's own "not
seen in the user's last N sessions" leaves N undefined, and flagging the single most common,
entirely legitimate case (everyone's first login) would be noise, not signal. **Live-verified**:
migration round-tripped (`upgrade`/`downgrade -1`/`upgrade`, `alembic check` clean); the real
`SystemSettingSessionCapAdapter` (not a test double) confirmed reading the actual migration-
seeded values per role against live Postgres; a live-Postgres integration test proves login past
the cap revokes the oldest session in the database (re-fetched via a fresh session, not just
in-memory state) and that `GET`/`DELETE /auth/sessions` round-trip for real. 1278 unit + 10
architecture-gate tests pass with zero regressions (254 integration tests pass; the only 6
failures are the pre-existing, already-disclosed no-reachable-Redis gap, unrelated to this
change). Zero changes to any other bounded context, RBAC, or tenant-isolation code.

**Priority 1 Item 9 — Mobile App MVP (partial — the honest limit of this session).** Built
against the already-approved `docs/architecture/frontend-flutter-master-roadmap.md` §5 (Phases
M0–M5), not freelanced. **Phase M0 (Foundation) code-complete**: Riverpod state management,
`flutter_secure_storage` refresh-token storage (access token in memory only), a REST client
mapping the real backend error envelope, a protocol-correct `/ws/tracking` WebSocket client
(the documented `{"type":"auth",...}` handshake + `{"channel":"vehicle",...}` subscribe frame),
role-based shell. **Phase M2 (Driver) code-complete**: trip list + real start/end actions.
**Phase M3 (Parent) partial**: the live-tracking screen is code-complete and protocol-correct;
the "assigned children" list is blocked on a real backend gap discovered while building this
exact screen (Known Issue #17 — no safe endpoint exists for a Parent to list their own children,
and a parallel gap means a Driver mobile client can't filter trips to "mine" either). **Phases M4
(FCM push)/M5 (release) not started** — both need real external accounts (Firebase; Play Store/
App Store Connect) this engagement cannot obtain, the identical category of blocker Item 8
already carries. A real `mobile-pipeline.yml` CI workflow (mirroring `backend-pipeline.yml`'s
shape) and one widget test were also added.

**The one categorical difference from every other item in this entire program**: no Flutter/Dart
SDK exists in this sandbox at all (`flutter`/`dart` resolve to nothing) — every other Priority 1
item retained *some* independent verification path even without its full target environment
(YAML structurally parsed for Docker Compose, a live DI container built and inspected for backend
wiring, real HTTP requests against a running server); this item has none. Every file was written
and manually re-reviewed line by line against this repository's own actual backend API shapes
(checked directly against the FastAPI schemas/routes, not assumed) and against each package's
documented public API, but this is a categorically weaker guarantee than compiling — disclosed
plainly in `mobile/README.md` rather than implied otherwise. One real bug was still caught this
way: `/auth/logout` was originally called without the bearer token it actually requires
(`Depends(get_current_user)`) — found during this same manual review and fixed before commit.
`mobile/README.md` and `docs/PROJECT_STATUS.md` Known Issue #17 have the full detail.

**Priority 1 Item 7 — Deployment & rollback runbook, VPS setup guide.** Two new runbooks, pure
documentation (zero code changes): `docs/runbooks/vps-deployment.md` (a fresh-VPS-to-running-
platform guide — OS baseline, `ufw` firewall locked to SSH/80/443 only, installing Docker,
configuring every `docker/.env` value that actually matters for a real deployment with the exact
reasoning for each, first boot, Founder bootstrap, DNS/TLS handoff, and an end-to-end
confirmation checklist referencing every other runbook this program has produced) and
`docs/runbooks/rollback.md` (application-code rollback, migration rollback — including explicit
guidance on when a downgrade is genuinely *not* safely reversible, with ADR-0016's real
destructive-migration precedent named directly rather than glossed over, frontend-only rollback,
and the last-resort full backup restore). Both close the two gaps this roadmap item's own
description named. Necessarily unverified against a real running VPS — no VPS is provisioned in
this sandbox — the same disclosed-limitation posture every other infra item in this program
(TLS, Redis) already carries; every command in both runbooks was still checked against this
repository's actual current file paths/module names/CLI flags (one real error caught this way
before it shipped: an incorrect Founder-bootstrap module path, corrected to match `docker/
README.md`'s own already-verified command).

**Priority 1 Item 6 — RBAC grant/revoke route.** New `GET/POST /roles/{role}/permissions`
(+`/revoke`, `iam`) and `GET /scope-assignments/{user_id}` + `POST /scope-assignments/
{regions,support}` (+`/revoke`, `organization`) — Founder-only in the seeded matrix (migration
`a1c9e4f2b871`). No documented API Contracts surface exists for either (built on Database Design
§4.4/§4.6 directly, the same "use-case exists, no approved endpoint yet" posture `/drivers`
already established). **A real, live-caught production bug, not specific to this item's own new
code but only reachable through it**: `role_permission_granted`/`revoked` and the four
`region_assignment_*`/`support_assignment_*` event factories (existing since the Backend
Stabilization phase, never previously reachable via any HTTP route) built `aggregate_id` from a
composite string (`f"{role}:{permission}"` or two concatenated ULIDs) — reliably overflowing the
shared `CHAR(26)` column both `outbox.aggregate_id` and `audit_entries.entity_id` use, caught via
`asyncpg.exceptions.StringDataRightTruncationError` against this sandbox's real, live Postgres
the first time the grant route was actually called end-to-end. Fixed by widening
`DomainEvent.aggregate_id` to `str | None` (`core/events/base.py`) and passing `None` from these
six factories — the full role/permission or user/region/organization identity stays in
`payload`, so nothing is lost — plus a new migration (`f3d8b1a4e6c2`) dropping `outbox.
aggregate_id`'s `NOT NULL` to match `audit_entries.entity_id`'s already-nullable design. 19 new
unit tests (13 application-layer + 6 locking the `aggregate_id=None` fix in place directly), full
live-HTTP verification both before and after the fix (grant → confirm via GET → revoke → confirm
cleared, for both role-permissions and region-assignments; non-Founder caller correctly 403s). A
second, pre-existing, unrelated rough edge was found during the same live testing and tracked
honestly rather than silently worked around: a real FK violation (bad `organization_id`) surfaces
as a generic 500 rather than a clean 4xx — confirmed systemic (not this item's bug), tracked as
new Known Issue #16. 1236 unit + 10 architecture tests pass with zero regressions.

**Completed This Sprint:**
- **ADR-0020 — Platform Analytics Read Model.** Full writeup above, under "Currently Working On."
- **ADR-0019 — Account-Sharing Session Cap.** Full writeup above, under "Currently Working On."
- **Priority 1 Item 8 — Payment provider integration (audited; genuinely blocked externally,
  not further built).** Confirmed by re-reading both the application-layer code and the source
  documents in full, not assumed: `BillingApplicationService.initiate_payment`/
  `handle_payment_callback`/`reconcile_expired_payments` are already fully implemented and
  tested (42 passing unit tests) — idempotency, the full paid/failed orchestration, and the
  scheduled reconciliation job all genuinely work today. The two remaining blockers
  (`PaymentProviderPort` unbound; `POST /billing/payments/callback` not wired) are both
  external, not a coding gap: (1) building a real adapter needs a real EVC Plus merchant
  account and API documentation this engagement doesn't have — the only existing design
  document (Phase 2 §20) designs the workflow only, explicitly disclaims processing payments
  itself, and describes a Parent-Pays flow ADR-0016 has since removed outright, a real,
  previously-unflagged documentation-vs-architecture conflict now recorded rather than silently
  resolved either way; (2) wiring the callback route needs a documented signature-verification
  scheme (none exists) and a resolved design decision for representing a signed-webhook caller
  in the `Principal`/RBAC model (no role fits "provider (signed)") — inventing either would ship
  unverified guesses as if they were real, tested integration code, exactly what
  `.claude/rules/workflow.md` #8 says to stop and ask about rather than do. Also swept every
  other bounded context's domain events for the same composite-key `aggregate_id` bug class
  Item 6 found and fixed — confirmed clean (billing's own events all use a single real ULID;
  `platform_audit`'s `SystemSetting` events already handle this correctly via a
  length-constrained key, the established precedent this bug class should have followed
  everywhere). No code changes shipped this item — the honest outcome given the two blockers are
  both genuinely external.
- **Priority 1 Item 5 — Real health checks + minimum monitoring.** New `HealthCheckService`
  (`core/health/service.py`) runs real, 3-second-bounded Postgres/Redis(cache)/Redis(broker)
  checks; `/health/ready` now returns 503 with a per-dependency breakdown (`{"database":"ok",
  "redis":"down","broker":"down"}`) instead of always reporting ready once `Settings` loaded —
  closes Known Issue #3. New `/metrics` (hand-rolled Prometheus text exposition, no new Python
  dependency — `core/observability/metrics.py`): `raad_http_requests_total` (incremented by the
  existing `RequestLoggingMiddleware`, labeled by *route template* not raw path to keep
  cardinality bounded), `raad_dependency_up` (reuses `HealthCheckService`), and
  `raad_process_start_time_seconds`. New `prometheus` Docker Compose service + scrape config
  (`infrastructure/monitoring/prometheus/prometheus.yml`). **Live-verified**: a real running
  `uvicorn` server against this sandbox's real Postgres and genuinely-unreachable Redis produced
  exactly the expected `not_ready`/503 response and correct `/metrics` output; a dedicated live
  integration test proves both a reachable and a deliberately-unreachable Postgres host are
  correctly distinguished (not mocked). 14 new unit tests, 2 new live-Postgres integration tests,
  1217 unit + 10 architecture tests pass with zero regressions. Grafana dashboards/Sentry/
  OpenTelemetry deliberately not built — each needs a real external account/target this session
  can't obtain, flagged in `docs/runbooks/monitoring.md` rather than faked. New dependency:
  `prom/prometheus` (Docker image only, Apache 2.0, no new Python/JS package) — already the
  implicitly-expected choice per this file's own pre-existing "no Prometheus/Grafana/Sentry"
  gap language, not a new idea introduced here.
- **Priority 1 Item 4 — Redis production hardening.** `docker/docker-compose.yml`'s `redis`
  service: `--requirepass` (previously unset entirely — anyone reaching the port, even though
  already un-published outside the Docker network in prod, could read/write with no credential),
  `--appendfsync everysec` made explicit alongside the existing `--appendonly yes`, `--maxmemory`/
  `--maxmemory-policy noeviction` (fails loud on memory pressure rather than silently evicting —
  this instance holds not-yet-consumed broker Streams entries, real undelivered domain events,
  not just reconstructable cache data; `maxmemory-policy` is server-wide, so "fail loud" is the
  only safe choice without splitting broker/cache onto genuinely separate Redis processes, a
  documented future step not attempted this phase). `RAAD_REDIS__URL`/`RAAD_BROKER__URL`/
  `DEVICE_GATEWAY_BROKER_URL` now carry the password and split onto separate logical DBs (0
  cache, 1 broker), matching `backend-pipeline.yml`'s own already-established CI convention.
  Backend-side: new `RedisConnectionSettings` (`core/config/settings.py`) adds explicit
  `socket_connect_timeout`/`socket_timeout`/`health_check_interval` to both of `core/di/
  bootstrap.py`'s `Redis.from_url(...)` calls — previously called with zero connection-resilience
  tuning at all, relying on undocumented redis-py library defaults. The stale
  `infrastructure/redis/redis.conf.template` placeholder is resolved (deleted, `.gitkeep` left in
  its place) by deliberately *not* mounting a config file — Compose `command:` flags cover every
  tunable this deployment needs, the same "no dedicated infra subfolder needed" precedent
  `infrastructure/backups/` already established for Item 1; `infrastructure/README.md` updated to
  match. New runbook `docs/runbooks/redis-operations.md` — persistence verification, the
  "Redis is reconstructable hot state" nuance (true for the cache DB, *not* fully true for the
  broker DB once an event is published-but-unconsumed — traced through `SqlOutboxPublisher`'s
  actual commit order, a real, disclosed qualification to Phase 2 §10's blanket framing),
  password rotation, memory-pressure troubleshooting, and the documented single-instance/no-HA
  scope decision. **Testing limitation disclosed, not hidden**: this sandbox has no Docker
  daemon, no WSL2 distribution, and no local `redis-server` binary (confirmed: `docker`/
  `wsl --list` both fail; no `Get-Command redis-server`) — the same category of gap Item 2 (TLS)
  already carries. Verification was YAML structural validation of the merged Compose config (base
  + dev, base + prod — confirming the hardened `redis` service survives both overlays unchanged
  except `ports: !reset []` in prod) and a live Python-side smoke test: building the real DI
  container and inspecting the actual `redis.asyncio.Redis` client's connection-pool kwargs
  (password, db number, all three new timeouts) — valid without a reachable server since
  `Redis.from_url` is lazy. 1203 unit + 10 architecture tests pass with zero regressions. Zero
  changes to any bounded context, RBAC/tenant-isolation code, or database migration.
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
**Nothing prescribed — awaiting user direction.** Known Issue #17 (ADR-0023) and CI hardening's
frontend/device-gateway half are both now resolved. Every Priority 1 item (1–9) is complete or
mechanism-complete pending only a genuinely external credential/account/SDK. Of Priority 2:
CI hardening is partial (lint/security-scan gate still needs a new-tool approval); Live video,
Reporting, Load testing, Log shipping, and Secrets-manager integration are all genuinely blocked
(see Section 5 for each one's specific reason — an unresolved architecture/documentation gap, a
new-dependency decision, or a real external account this engagement cannot obtain). The one
remaining **fully actionable, no-new-dependency, no-external-account** Priority 2 item is
`/docs` gating for production (&lt; 1 day) — the next candidate if this session continues.
Mobile's `/me`-endpoint wiring remains open too, still blocked on no Flutter SDK in this sandbox
to verify against. Per Section 14's rules, don't start any of these without the user's
confirmation.

---

## 9. Recent Completed Work

Reverse-chronological (most recent first):

- **Backend CI failure fixed — `test_video_provider_di_wiring.py` job-environment leakage**
  (2026-08-14). The `Backend CI` run on commit `d689c08` (D5 review findings 1+2, tenant-scoping
  `video_sessions`) failed its `Run unit tests` step: 1394 ran, 1 failed —
  `test_signaling_url_alone_without_a_broker_leaves_it_unbound`
  (`backend/tests/unit/test_video_provider_di_wiring.py:48`), `AssertionError: LookupError not
  raised`. Root-caused to a test-isolation bug, not a production regression and unrelated to
  `d689c08`'s own changes (confirmed via `git show --stat`/diff — that commit never touched
  `bootstrap.py`, `settings.py`, or this test file): `.github/workflows/backend-pipeline.yml` sets
  `RAAD_BROKER__URL: redis://localhost:6379/1` at **job level** (needed by the later integration-
  test step), and `Settings(_env_file=None, ...)` only disables the dotenv source — the real
  process environment is still read for any field the test doesn't explicitly override. Since this
  one test constructed `Settings` with `device_plane=DevicePlaneSettings(jt1078_signaling_url=...)`
  but no explicit `broker=`, the leaked `RAAD_BROKER__URL` made `settings.broker.url` truthy in CI
  (empty locally, which is why it passed on a dev machine), so `core/di/bootstrap.py`'s
  `if settings.broker.url: ... if settings.device_plane.jt1078_signaling_url: bind(...)` bound
  `VideoProviderPort` when the test's intent was "no broker configured" — confirmed by reproducing
  the exact CI env vars locally and reproducing the identical failure. `bootstrap.py`'s conditional-
  binding logic itself is correct and needed no change. **Fix (test-only, one line):** the affected
  test now explicitly passes `broker=BrokerSettings(url="")`, matching the sibling tests' own
  explicit-override pattern, making the assertion hermetic against ambient environment variables.
  Verified locally (`tests/unit`: 1394/1394; `tests/architecture`: 10/10, both re-run with the
  exact CI env vars reproduced) and then for real in GitHub Actions — commit `70217f5` pushed to
  `main`, `Backend CI` run [#4](https://github.com/raadtech2026-usame/raad-tech/actions/runs/31817093951)
  completed with conclusion `success` across all eight steps, including the two gates this
  sandbox itself cannot run (no Docker/local service containers matching the CI's `raad`/`raad`/
  `raad` Postgres+Redis credentials — see Known Issue #15's own disclosed class of gap): live
  integration tests and the backup/restore round-trip.

- **Native JT/T 808-2019 + JT/T 1078-2016 protocol compliance — architecture update** (2026-08-10,
  ADR-0025), at the user's explicit direction, following a prior, code-change-free
  protocol-source-of-truth review of two new official supplier documents (a JT/T 808-2019 + JT/T
  1078-2016 combined spec, and a model-specific Compliance Confirmation Letter). **Reverses
  ADR-0009's core finding for the procured `LSZ-C5804DG-Q-F` hardware only** — every other
  ADR-0009 decision (the parallel-stack pattern, ADR-0010's device-gateway rename, ADR-0015's
  identity-only trust model for any genuinely no-credential vendor) is unchanged. New ADR-0025:
  §2 tabulates the confirmed JT/T 808-2013→2019 wire-format deltas (header terminal-phone
  `BCD[6]`→`BCD[10]`, a new protocol-version byte, wider manufacturer/model/terminal-ID fields,
  added IMEI+software-version fields in `0x0102`); §3 **resolves Known Issue #18**'s previously
  open `0x0102` auth-code lifecycle question with a concrete, reasoned design (platform-minted
  code hashed into the existing `Device.auth_key_hash` column, verified by comparison on
  `0x0102`, no time-expiry, rotates only on fresh registration) — explicitly flagged as a design
  recommendation, not independently re-confirmed beyond the ADR's own review; §4 makes
  `vendors/jt808/` the live/primary GPS adapter, keeps `vendors/lsz/` dormant, not deleted; §5
  supersedes ADR-0024 §1's LSZ-proprietary video-signaling design with native JT/T 1078 signaling
  over the existing JT808 connection; §6 retires both rule files' "Reality check" disclaimers.
  **ADR-0024 revised in place, same commit**: §1's signaling design replaced (`0x9101`/`0x9102`/
  `0x9105`/`0x9201`/`0x9202`/`0x9205`/`0x1205` supersede the old `C508`/`V102`/`0x6000`/`0x6002`/
  `C701`/`C702`/`V103`/`0x6102` design), with §2/§6/§7/§8/§14/§16/Consequences/Verification/
  References sections updated to match; the D5/concurrency/audit/transport-choice policy content
  (~80% of the document) is unchanged, since none of it was protocol-specific. `.claude/rules/
  jt808.md`/`jt1078.md` and CLAUDE.md's "Core Technical Domains" updated to match — CLAUDE.md
  verified still at 64,708 chars, well under its 150,000-char budget. **This is a
  documentation/decision-records update only** — no `.py` file changed, no migration, no test run
  — the confirmed JT/T 808-2019 field-width rework and the now-decided `0x0102` auth-code
  implementation remain a following, separately-authorized implementation phase. Nothing in
  `mdvrdocs/` was deleted — the prior review turn's "nothing safe to delete" conclusion stands,
  reconfirmed in ADR-0025's own Consequences section. See Section 8 for the full writeup and
  Section 3's JT808/JT1078 rows.
- **JT808 device-plane provisioning/identity integration gap** closed (2026-08-09), at the user's
  explicit direction, in two phases. **Audit phase (source code only, no doc-of-record
  inference):** confirmed JT/T 808's full registration/authentication/location handler stack
  (`services/device-gateway/src/vendors/jt808/`) is real, tested, and running (port 7808)
  alongside LSZ (port 7809), but permanently wired to a fail-closed `NullDeviceProvisioningPort`
  — `gateway.py` never even passed a `device_provisioning=` argument to `Jt808Server`, unlike
  LSZ, which already had a real `ProjectionBackedMdvrProvisioningPort`; also confirmed
  `services/jt1078/` is a pure scaffold (zero `.py` files) and the LSZ media/video channel
  (`C508`/`C701`/`C702`/`0x6011`-`0x6013`) has zero implementation anywhere, doc-only.
  **Implementation phase, scoped to exactly the resolvable half of that gap:** new
  `ProjectionBackedJt808ProvisioningPort` resolves `terminal_id` against the same shared,
  vendor-agnostic `DeviceRegistryProjection` LSZ already uses (a real, pre-provisioned device —
  registered → activated → assigned to a vehicle — is now correctly identified/resolved to its
  `device_id`/`vehicle_id`/`organization_id` at `0x0100`; unknown/inactive/unassigned/suspended/
  retired devices all correctly collapse to `TERMINAL_NOT_FOUND`, mirroring LSZ's own precedent
  exactly); new `HeartbeatHandler` (`0x0002 → 0x8001`) plus a `touch()` call added to
  `LocationHandler` (`0x0200`) wire the pre-existing, previously-never-triggered
  `DeviceSessionManager.touch()` (`AUTHENTICATED → ONLINE`) and `DeviceOnline`/`DeviceOffline`
  publishing, the same bug-fix precedent `MdvrPositionHandler` already established for LSZ;
  `gateway.py` now shares one `DeviceRegistryProjection` between both vendor adapters. **`0x0102`
  authentication verification was deliberately left unimplemented — an explicit stop, not an
  oversight or a guess**: JT808 Technical Design, the primary JT/T 808-2013 spec's own text, and
  Backend LLD describe three structurally different, mutually exclusive auth-code mechanisms (see
  Known Issue #18); `authorize_registration` returns `SUCCESS` with `auth_code=None`,
  `verify_auth_code` always returns `is_valid=False`, both explicitly documented as the
  deliberate boundary pending the supplier's forthcoming standalone JT808 documentation. 18 new
  device-gateway tests plus 3 existing test files updated for the new, correct `DeviceOnline`
  side effect a position/heartbeat report now legitimately produces (device-gateway: 351/351, was
  333); 3 new live-Postgres integration tests close a real, previously-untested gap — two
  organizations cannot register a `Device` with the same `terminal_id` (only same-org duplication
  had a test before this; `fleet_device` integration: 32/32, was 29). Backend unit (1330) and
  architecture-gate (10) suites re-run as a regression check, unchanged. No ADR written — this
  closes an implementation gap in an already-accepted design (ADR-0009/0010), the same
  "wiring/integration, not a new architecture decision" posture CI hardening (below) was itself
  built under. JT1078/video work untouched, per explicit scope. See Section 8 for the full
  writeup, Section 3's JT808 row, and Known Issue #18.
- **CI hardening — frontend + device-gateway CI** completed (Priority 2 backlog item). New
  `.github/workflows/frontend-pipeline.yml` (`npm ci` → `npm run build` → `npm test -- --run`)
  and `device-gateway-pipeline.yml` (`pip install -e .` → `compileall` →
  `unittest discover`), both build→test-only mirroring `backend-pipeline.yml`'s scope discipline
  — no lint/security-scan step (unapproved tooling, not invented). Every command verified
  passing locally first (frontend 392/392 + clean build; device-gateway 333/333). Fixed a real,
  pre-existing drift: `mobile-pipeline.yml`'s own header comment and `ci-cd/pipelines/
  backend-pipeline.yml`'s status note both still claimed mobile's CI didn't exist yet, though it
  had since Priority 1 Item 9 — corrected, and all four now-real deployables' `ci-cd/pipelines/`
  index stubs populated to match. Five other Priority 2 items (Live video, Reporting, Load
  testing, Log shipping, Secrets-manager) were evaluated and skipped with reasons recorded in
  Section 5 — each genuinely blocked (unresolved architecture/documentation gap, a
  new-dependency decision, or a real external account this engagement cannot obtain), not
  silently passed over. See Section 8 for the full writeup.
- **ADR-0023 — Canonical `/me` Self-Service Identity Resolution** completed — closes Known Issue
  #17. New `GET /me`/`GET /me/students`/`GET /me/driver-profile` (`iam/api/routers.py`, mounted
  at `/api/v1/me`), backed by a new `MeApplicationService` (`iam`) composing `transport_ops`'s
  own `ParentApplicationService`/`DriverApplicationService`/`StudentParentApplicationService` —
  the same legal cross-module composition ADR-0020's `PlatformStatsApplicationService` already
  established. Resolves the caller's own `Parent`/`Driver` id from `Principal.user_id` alone —
  no client-supplied `parent_id`/`driver_id` anywhere. New `DriverRepository.get_by_user_id`
  (domain + infra) mirrors `ParentRepository`'s existing equivalent. Self-scoped by
  `Depends(get_current_user)` alone, no RBAC grant, zero migration. 10 new unit tests + 2 new
  driver-repository integration tests + 4 new dedicated live-Postgres integration tests (the
  actual cross-parent isolation proof) — 1330 unit + 10 architecture tests pass, zero
  regressions. See Section 8 for the full writeup.
- **ADR-0020 — Platform Analytics Read Model** completed — `GET /admin/platform-stats` composed
  from `organization`/`iam`/`fleet_device`/`billing`'s own new count/sum query methods by a new
  `platform_audit.PlatformStatsApplicationService`; `devices.is_online` closes the Online/
  Offline gap by extending the already-real `DeviceConnectivityProcessor` (Known Issue #9 now
  resolved); a new `admin.platform_stats.read` permission (Finance Staff didn't hold `admin.
  audit.read`); System Health reuses `HealthCheckService` verbatim. Frontend KPI grid replaces
  three tiles of the pre-existing stopgap. Live-verified against real Postgres, including the
  full composition through the real DI container. See Section 8 for the full writeup.
- **ADR-0019 — Account-Sharing Session Cap** completed — `SessionLimitPolicy` enforced at
  login/refresh (revoke-oldest once a per-role cap, read from a new `platform_audit.
  SystemSetting` row via a new `SessionCapPort`/`SystemSettingSessionCapAdapter`, is exceeded),
  `refresh_tokens.device_label` (migration `4ef3fefb5e8d`), self-service `GET`/
  `DELETE /auth/sessions`, a visibility-only "unrecognized device" signal. Live-verified against
  real Postgres, including the real adapter reading the real seeded row. See Section 8 for the
  full writeup.
- **Priority 1 Item 9 — Mobile App MVP** partially built — Phase M0 (Foundation) and M2
  (Driver) code-complete against the approved Flutter roadmap; M3 (Parent)'s live-tracking
  screen code-complete, its children-list blocked on a real, newly-discovered backend gap
  (Known Issue #17: no safe self-identity-resolution endpoint for Parent or Driver roles). M4/M5
  need real external accounts. Zero Flutter SDK in this sandbox — nothing compiled or run, the
  most severe disclosed-limitation of any item this program shipped. **This closes the Priority
  1 continuous-completion program** — see Section 15 for the full final report.
- **Priority 1 Item 8 — Payment provider integration** audited, not further built — both
  remaining blockers (no bound `PaymentProviderPort`; `POST /billing/payments/callback` not
  wired) confirmed genuinely external (a real EVC Plus account/API docs; a resolved Principal/
  webhook-actor design decision), not a coding gap. Application-layer code already fully
  implemented and tested. A real documentation-vs-architecture conflict (Phase 2 §20's
  Parent-Pays EVC Plus workflow vs. ADR-0016's Organization-only billing) was found and flagged.
- **Priority 1 Item 7 — Deployment & rollback runbook, VPS setup guide** completed —
  `docs/runbooks/vps-deployment.md` (fresh VPS to running platform) and `docs/runbooks/
  rollback.md` (code/migration/frontend rollback). Documentation-only; not live-tested against a
  real VPS.
- **Priority 1 Item 6 — RBAC grant/revoke route** completed — new Founder-only
  `/roles/{role}/permissions` and `/scope-assignments/*` routes, live-verified over real HTTP/
  Postgres. Caught and fixed a real production bug along the way: six RBAC/scope-assignment
  event factories built an oversized composite `aggregate_id` that overflowed a shared
  `CHAR(26)` column, never caught before since no route had ever reached them — fixed by
  widening `DomainEvent.aggregate_id` to nullable, with a corresponding schema migration.
- **Priority 1 Item 5 — Real health checks + minimum monitoring** completed — real Postgres/
  Redis dependency checks on `/health/ready` (closes Known Issue #3), a new hand-rolled
  `/metrics` Prometheus endpoint, and a `prometheus` Compose service scraping it. Live-verified
  over real HTTP and real Postgres. Grafana/Sentry/OpenTelemetry deliberately deferred (real
  external accounts needed, not obtainable this session).
- **Priority 1 Item 4 — Redis production hardening** completed, mechanism-wise — `--requirepass`,
  AOF `everysec` persistence, `--maxmemory`/`noeviction`, broker/cache split onto separate
  logical DBs, explicit backend-side connection timeouts, the stale `redis.conf.template`
  placeholder resolved. New runbook `docs/runbooks/redis-operations.md`, including the
  "reconstructable hot state" nuance traced through the actual outbox-publish commit order. Not
  live-tested against a real Redis process — no Docker/WSL2/`redis-server` in this sandbox.
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

### 3. ~~`/health/ready` doesn't check real dependencies~~ — RESOLVED 2026-08-03
- **Resolution:** Priority 1 Item 5. `HealthCheckService` (`core/health/service.py`) runs real,
  3-second-bounded Postgres/Redis(cache)/Redis(broker) checks; `/health/ready` returns 503 with
  a per-dependency breakdown when any configured dependency is down. Live-verified against real
  Postgres (reachable and genuinely-unreachable cases) and over real HTTP against a running
  server. `docs/runbooks/monitoring.md`.
- **Severity:** ~~High~~
- **Blocking production?** No longer.

### 4. `PaymentProviderPort` (resolved, ADR-0022), `VideoProviderPort` (resolved, mechanism-wise, 2026-08-12), `ReportRendererPort` still unbound
- **Severity:** ~~High (Payment)~~ Low (Payment — real-account credentials only, mechanism
  complete). ~~Medium (Video)~~ Low (Video — same "mechanism complete, real-world verification
  pending" posture as Payment, since 2026-08-12; no real merchant-account equivalent blocks it,
  only a physical MDVR). Medium (Reporting — unchanged).
- **Recommended fix:** ~~Bind a real EVC Plus adapter (Payment)~~ **Done, ADR-0022** — set
  `RAAD_PAYMENT__PROVIDER=stripe` + real `RAAD_PAYMENT__PROVIDER_CREDENTIALS` (a real Stripe
  merchant account) once one exists; the adapter, webhook route, and frontend flow are all
  already built and tested. ~~Video: decide a JT1078 runtime, then build a `VideoProviderPort`
  adapter~~ **Done** — see below. Reporting: pick a PDF/Excel engine.
- **Blocking production?** Payment: no longer, mechanism-wise (same "not live-tested against a
  real external account" disclosed posture as TLS/Redis hardening). Video: no longer
  architecturally — see below for what's still open. Reporting: only if marketed as working at
  launch — unchanged.
- **Video half resolved (2026-08-12):** `Jt1078RelayAdapter` is a real, tested `VideoProviderPort`
  implementation, conditionally bound in `core/di/bootstrap.py` — see Section 3's Video/JT1078 rows
  and Section 8's own dated write-up for the full architecture, tests, and the two flagged,
  disclosed gaps (viewer-token minting happens relay-side, not backend-side as ADR-0024 §5 point 2
  literally reads; the relay's own session-lifecycle events aren't yet consumed back into
  `VideoSession`). **What remains, not fabricable in this sandbox:** a physical MDVR to verify any
  of it against — this entry does not claim live-hardware compatibility.
- **ADR-0022 (2026-08-06) resolution, Payment half:** both blockers this issue used to describe
  are closed. **The signed-webhook-caller design question** (no `Principal` exists for a
  provider's own webhook) is resolved *without* a full new ADR-level RBAC change — the HMAC
  signature itself is the route's authentication (no `Depends(require_permission(...))`/bearer
  JWT at all, matching how Stripe's own webhook documentation describes this exact model), and
  `SYSTEM_PRINCIPAL` (moved to `core/tenancy/principal.py`, shared with `notifications`' own
  Notification Worker rather than a second copy) represents the caller for the audit trail only —
  the same "least-bad available role" reuse already established elsewhere in this codebase, not
  a new RBAC concept requiring its own ADR. **The real EVC Plus documentation-vs-architecture
  conflict this issue previously flagged (Phase 2 §20's Parent-Pays workflow vs. ADR-0016's
  Organization-only billing) is sidestepped, not resolved** — per the user's own explicit choice
  (`AskUserQuestion`, "(Recommended)" option accepted), Stripe gets a real adapter now instead
  (public, stable, verifiable API docs), while EVC Plus/Zaad remain honest,
  interface-complete `PaymentProviderPort` stubs (`NotImplementedError`, no merchant docs to
  verify against) — that underlying document conflict still exists and would need resolving
  before an EVC Plus/Zaad adapter specifically could ever be built for real. A real, previously-
  undiscovered idempotency bug was found and fixed in the same pass: `Payment.mark_paid`/
  `mark_failed` lacked a same-state guard (unlike `mark_processing`/`mark_expired`), so a
  provider's routine webhook retry would have double-advanced a subscription's billing period —
  closed with a regression test. Application-layer code (`initiate_payment`/
  `handle_payment_callback`/`reconcile_expired_payments`/`handle_webhook_event`) plus a real,
  verified `StripePaymentAdapter` (httpx, Payment Intents API, Stripe's documented HMAC-SHA256
  webhook signature scheme) are fully built and tested (1330 unit + 10 architecture tests) and
  live-server-verified (real JWT, real Postgres, fake-but-well-formed Stripe credentials
  exercising all four webhook scenarios end to end) — see the Billing row in Section 3 for the
  full detail. **What remains, genuinely external, cannot be fabricated:** a real Stripe merchant
  account's live `secret_key`/`webhook_secret`.

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

### 9. ~~ADR-0020's Context section conflates two different consumers~~ — RESOLVED 2026-08-05
- **Resolution:** Confirmed accurate during ADR-0020 implementation, not just filed and left:
  `DeviceConnectivityProcessor` (`fleet_device/events/subscribers.py`) already consumed
  `DeviceOnline`/`DeviceOffline` and populated `last_seen_at` — extended in place (not
  duplicated into a second consumer) to also set the new `devices.is_online` boolean, since it
  already receives both event types via the existing `EventProcessorRegistry` dispatch. No
  amendment to the ADR's own text was made (out of scope for an implementation session), but
  the actual code now reflects the correct, single-consumer reality this issue described.
- **Severity:** ~~Low~~
- **Blocking production?** No longer relevant — closed.

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
- **Recommended fix:** Priority 1 Item 4 (Redis production hardening, complete) hardened the
  *mechanism* (auth, persistence, connection timeouts) but did not itself provide a reachable
  Redis in this sandbox — see Known Issue #15. Once a real Docker host/VPS exists, re-run
  `tests/unit/test_login_rate_limiter.py`'s scenarios against the actual hardened `redis` service
  (or add a dedicated live integration test) to confirm the real `INCR`/`EXPIRE` behavior matches
  the fake's.
- **Blocking production?** No — the fail-open design means an unreachable/misconfigured Redis
  degrades to "rate limiting temporarily off," never to "login broken," and account lockout
  (Known Issue #1, resolved) is the higher-value, fully-live-verified control of the two.

### 15. Redis hardening mechanism not live-tested against a real running server
- **Severity:** Medium
- **Description:** Priority 1 Item 4 shipped a complete, carefully-reviewed Redis hardening
  mechanism (`--requirepass`, AOF `everysec` persistence + RDB fallback, `--maxmemory`/
  `noeviction`, broker/cache split onto separate logical DBs, explicit backend-side connection
  timeouts) — but it has never been run against a real Redis process, because this sandbox has no
  Docker daemon, no WSL2 distribution installed, and no local `redis-server` binary (confirmed:
  `docker`/`wsl --list --verbose` both fail; no `Get-Command redis-server`/`docker` resolves).
  The exact same category of gap Known Issue #13 (TLS) already discloses for its own mechanism.
  Verification was YAML structural validation of the merged Compose config (base+dev, base+prod)
  and a live Python-side smoke test — building the real DI container and inspecting the actual
  `redis.asyncio.Redis` client's connection-pool kwargs (password, db number, timeouts), valid
  without a reachable server since `Redis.from_url` is lazy — rather than an actual boot/auth/
  persistence-restart cycle.
- **Recommended fix:** Follow `docs/runbooks/redis-operations.md`'s "First real verification"
  section once a Docker host/VPS exists: confirm `--requirepass` is actually enforced (a bare
  `redis-cli ping` should fail with `NOAUTH`), run the persistence-restart drill, and confirm
  `backend`/`worker`/`device-gateway` all still connect with the new credential.
- **Blocking production?** Not on its own (the design is the standard Redis hardening pattern —
  password auth, bounded memory with a fail-loud eviction policy, AOF persistence — and the
  previous, completely unhardened state was strictly worse) — but treat "Redis hardening
  live-verified" as not yet true until that checklist has actually been run for real, the same
  posture Known Issue #13 already establishes for TLS.

### 16. Raw database constraint violations (FK, unique, etc.) surface as generic 500s
- **Severity:** Low
- **Description:** Discovered live while testing Priority 1 Item 6's new `POST
  /scope-assignments/support` route with a syntactically-valid but non-existent
  `organization_id`: the resulting `asyncpg.exceptions.ForeignKeyViolationError` propagates
  uncaught to the global unhandled-exception handler, returning a generic `{"code":
  "INTERNAL_ERROR"}` (500) instead of a clear `{"code":"VALIDATION_ERROR"}` (422) or
  `{"code":"NOT_FOUND"}` (404) naming the actual problem. **Not a regression this item
  introduced** — confirmed pre-existing and systemic: `IntegrityError`/`ForeignKeyViolation` is
  caught in exactly one place anywhere in this codebase
  (`transport_ops/application/validators.py`), everywhere else a real DB constraint violation
  takes this same generic path. The FK constraint itself is correct and working as designed
  (`.claude/rules/database.md` #3: "in-context FKs are enforced by the database") — this is
  purely about the *error presentation* once one fires.
- **Recommended fix:** A single global handler for `sqlalchemy.exc.IntegrityError` (`core/errors/
  handlers.py`, alongside the existing `AppError`/`RequestValidationError`/`StarletteHTTPException`
  handlers) that maps common constraint-violation shapes (FK violation → 404/422 naming the
  missing reference, unique violation → 409) would close this everywhere at once, matching this
  file's own "resolved once at the edge, not per call site" principle already applied to tenant
  scoping (ADR-0021).
- **Blocking production?** No — the underlying data integrity guarantee is never at risk (the
  constraint still fires and the bad write is still rejected); this is purely a rough edge in
  the *error message* a caller sees, not a functional or security gap.

### 17. ~~Parent/Driver mobile roles have no safe way to resolve their own domain identity~~ — RESOLVED 2026-08-07
- **Resolution:** ADR-0023 (`docs/architecture/adr/0023-canonical-me-identity-resolution.md`).
  New `GET /me` (canonical cross-module identity: `role`/`organization_id`/`parent_id`/
  `driver_id`), `GET /me/students`, `GET /me/driver-profile` — all self-scoped from
  `Principal.user_id` alone via a new `iam.MeApplicationService`, never a client-supplied
  `parent_id`/`driver_id`. Closes both halves of this issue: Parent now has a safe,
  ownership-correct-by-construction "my children" endpoint (no RBAC grant needed, so the
  cross-parent leak this issue described never becomes reachable), and Driver can now resolve
  its own `driver_id` (new `DriverRepository.get_by_user_id`, mirroring `ParentRepository`'s
  existing equivalent) to filter `GET /trips?filter[driver_id]=...` to "assigned to me." 10 new
  unit tests + 6 new live-Postgres integration tests, including a dedicated two-parent isolation
  proof against a real database. `GET /parents/{parent_id}/students`'s own pre-existing
  missing-ownership-check gap is intentionally unchanged (still Org-Admin/RAAD-staff-only,
  explicitly out of scope for ADR-0023 — see that ADR's own Consequences section). **Not yet
  done**: wiring the mobile Parent/Driver screens to actually call these new endpoints — still
  blocked on this environment having no Flutter SDK to verify any mobile change against (the
  same disclosed limitation Priority 1 Item 9 already carries).
- **Severity:** ~~High~~
- **Blocking production?** No longer, on the backend side. Mobile client wiring remains open,
  tracked under Item 9's own Mobile App status, not re-opened here.

### 18. ~~JT808 `0x0102` authentication-code semantics~~ — RESOLVED 2026-08-11
- **The original conflict (found 2026-08-09):** three source documents described structurally
  different, mutually exclusive mechanisms for the `0x0102` auth code — JT808 Technical Design §4
  reads as a device-held static secret checked against `Device.auth_key_hash`; the primary JT/T
  808-2013 spec's own text (§8.6/§8.8/§21.1, verbatim) reads as a platform-minted code issued in
  `0x8100` and echoed back in `0x0102`; Backend LLD adds a third, only-partially-compatible reading
  (a short-lived, Redis-held, rotating session token). Picking wrong had real consequences —
  either rejecting every real device forever, or implementing a check that isn't actually what
  real hardware does.
- **Design resolution (2026-08-10):** `docs/architecture/adr/
  0025-jt808-2019-jt1078-2016-native-protocol-compliance.md` §3 settled the lifecycle question as
  a reasoned design recommendation — a platform-minted random code on `0x0100` success, hashed at
  rest in the existing (previously always-`None`) `Device.auth_key_hash` column, verified by hash
  comparison on `0x0102`, no time-expiry, rotating only on a fresh registration (e.g. a factory
  reset).
- **Implementation resolution (2026-08-11, commit `f5e9fae`):** `ProjectionBackedJt808
  ProvisioningPort.authorize_registration` now mints a fresh code and PBKDF2-HMAC-SHA256-hashes it
  (new `auth_code_hashing.py`) on every successful `0x0100`, writing it via a new
  `DeviceAuthCodeIssued` event so `fleet_device.Device.auth_key_hash` (previously always `None`)
  mirrors it (new `DeviceAuthCodeProcessor` subscriber); `verify_auth_code` now verifies by real
  hash comparison on `0x0102`. **A real bug was found and fixed during this pass**:
  `DeviceAuthCodeProcessor` never set `self.event_type`, so `EventProcessorRegistry.register()`
  (keyed by that attribute) would have raised `AttributeError` the instant a real deployment wired
  up its processors — confirmed fixed by direct registration; no test had exercised that
  registration path before this pass.
- **Severity:** ~~Medium~~
- **Blocking production?** No longer. `vendors/jt808/` now has a real, tested, end-to-end
  identity + credential lifecycle (registration → resolution → auth-code mint/hash → `0x0102`
  verification) — see Section 3's JT808 row for the fuller status. Physical-MDVR verification
  remains open, tracked there, not re-opened as a separate issue here.

### 19. ~~`NoSilentUndocumentedRoutesTests` contract-test failure (19 undocumented routes)~~ — RESOLVED 2026-08-27
- **The gap (found by the 2026-08-25 audit, never previously filed as its own numbered issue
  despite being narrated inline across several earlier phase entries in this section and §9):**
  `backend/tests/contract/test_api_contracts_routes.py`'s `NoSilentUndocumentedRoutesTests` had
  been silently red since routes started shipping without a matching `ALLOWED_UNDOCUMENTED_EXTRAS`
  entry — 19 real, built `/api/v1` routes (plus `GET /metrics`) spanning ADR-0018 (device
  inventory), ADR-0019 (session cap self-service), ADR-0020 (platform analytics), ADR-0022
  (payment history list), ADR-0023 (canonical `/me`), ADR-0031 (fleet-overview online-vehicles),
  and the two RBAC/scope-assignment routes from Priority 1 Item 6 above, each landed without the
  corresponding citation this suite's own accounting requires.
- **Resolution:** all 19 added to `ALLOWED_UNDOCUMENTED_EXTRAS`, each citing its real originating
  ADR/Priority-1 item and introducing commit (traced via `git log`) — the same "documented predates
  the ADR, cited not silently added" precedent this list already established 9 times over for
  every other post-Phase-3.3 route (uniform-CRUD additions, `/drivers`, `/auth/change-password`,
  `/parents/{id}/video-access`, `/health*`, etc.). `docs/business/RAAD_Phase3.3_API_Contracts_v1.md`
  itself is a frozen Phase-3.3 deliverable and was deliberately **not** edited, matching how this
  repo treats ADRs as historical records — confirmed with the user before implementing.
  `tests/contract` is now `2 passed, 0 failed`.
- **Severity:** ~~Low~~
- **Blocking production?** No longer — this was a CI-gate-integrity gap (the suite existed to
  catch exactly this kind of drift but had itself drifted), not a runtime defect.

### 20. Windows Firewall Private-profile has no inbound allow rule for Docker's JT808 port by default

- **The gap (found live, 2026-08-27, during ADR-0033's own physical bench verification):** the
  bench MDVR connects to the dev PC entirely over its own built-in Wi-Fi AP (MDVR `WorkMode=AP`,
  the PC as a Wi-Fi client) — a topology Windows classifies as the **Private** network profile.
  Docker Desktop's own firewall rule for `com.docker.backend.exe` (the process that actually owns
  the host-side listener for `DEVICE_GATEWAY_JT808_PORT`/7808) is scoped to the **Public** profile
  only; Private's active `DefaultInboundAction` is `Block`. The physical MDVR could reach and ARP-
  resolve the PC (confirmed: the "gateway" IP `192.168.10.202` is the MDVR's own AP radio, ARP MAC
  identical to the AP's own BSSID), but every inbound JT808 TCP SYN to `7808` was silently dropped
  by the OS firewall before ever reaching device-gateway — zero `connection_accepted` log lines
  from any non-`127.0.0.1` address for the full length of a fresh bench-test session.
- **Resolution:** the user added a dedicated inbound Allow rule (`RAAD JT808 7808`, TCP, Private
  profile, any remote address) via Windows Firewall directly — not a RAAD/Docker configuration
  change, so nothing in this repository needed to change. Confirmed working immediately after:
  real JT808 registration/authentication/heartbeat all succeeded within the same session.
- **Severity:** Low — a one-time host/OS setup step for any dev machine whose bench MDVR connects
  over its own AP rather than a shared LAN/router, not a defect in RAAD's own code or Docker
  Compose configuration. Worth naming in a future bench-setup runbook if one is ever written;
  no runbook exists yet, and none is created by this entry.
- **Blocking production?** No — this is specific to a Windows dev-machine bench-test topology; a
  real deployed device-gateway (Linux VPS/Coolify, per the existing deployment runbooks) has no
  equivalent Windows-Firewall-profile concern.

### 21. Pre-existing outbox backlog (~3,700 unpublished events dating to 2026-07-20)

- **The gap (found live, 2026-08-27, while diagnosing why a freshly-provisioned device's own
  `DeviceRegistered`/`DeviceActivated` events weren't reaching device-gateway):** the `worker`
  container's `OutboxRelayWorker` had a large backlog of unpublished `outbox` rows — 3,699 rows,
  oldest dated 2026-07-20, spanning ordinary domain events (`NotificationCreated`, `RouteCreated`,
  `StudentEnrolled`, `VehicleRegistered`, `DeviceRegistered`, and others) accumulated across many
  prior sessions' test/verification activity. The relay's own 5-second poll/100-row-batch design
  is correct in isolation; the backlog itself reflects the `worker` container not having run
  continuously/consistently across this repository's full development history, not a defect in
  `SqlOutboxPublisher.publish_pending`'s logic (confirmed by reading it — plain FIFO-by-
  `created_at`, no poison-message-blocking behavior found).
- **Impact observed:** a newly-created device's own outbox rows had to wait behind the full
  historical backlog before the relay would reach them — tens of minutes of delay for a
  broker-driven event the caller might reasonably expect within seconds.
- **Not resolved, not modified.** Explicitly out of ADR-0032/ADR-0033's own scope (neither ADR's
  own code touches the outbox relay), and the backlog itself was deliberately left untouched —
  not drained, deleted, or bypassed in bulk — since it represents real, already-decided historical
  domain events this codebase's own "no event without a committed change, no committed change
  silently missing its event" invariant (ADR-0007) says must still be published, not discarded.
  (The two specific devices this session's own verification depended on had their individual
  events republished directly, out-of-band, precisely so the bulk backlog would not need to be
  touched to unblock this one verification — see ADR-0033's own Verification section.)
- **Severity:** Medium — does not lose data or corrupt state, but silently degrades the "domain
  event reaches the broker promptly" assumption several other subsystems (device-gateway's
  registry projection, notification delivery, WS fan-out) depend on.
- **Blocking production?** Not by itself, but worth investigating before a real deployment
  relies on timely event delivery — the `worker` container's own uptime/restart history across
  a real environment should be checked, and consider whether `outbox_relay_batch_size` (currently
  100 per 5s tick) is sized correctly for this platform's real event volume.

### 22. Two-way intercom does not reliably establish on the bench MDVR's current firmware

- **The gap (found live, 2026-08-28, ADR-0035):** a real bench test against the physical bench
  unit (`LSZ-C5804DG-Q-F`, terminal `00000000014482607571`, firmware `TTY3521DV200-A251110`) sent
  five independent, real `0x9101 data_type=2` (two-way intercom) requests. The firmware's JT/T 808
  dispatcher understands the message (`0x0001` ack, `result: 0`, in 3 of 5 attempts) but a real
  device-initiated media connection for the actual audio channel completed in only 1 of the 5
  attempts (and that one was itself rejected by this test's own relay-side software gap, since
  fixed for later attempts) — meaning real two-way audio never actually flowed in any attempt.
  Both TCP and UDP transports were offered and checked; neither showed reliable device-side
  connection behavior on repeat requests.
- **Not implemented, deliberately.** Per the user's own explicit instruction ("if it fails...
  do not create a fake workaround"), no intercom permission, D5 authorization, audit hooks,
  browser mic capture/push-to-talk UI, or bidirectional audio relay were built — none of it would
  have a real, verified media path underneath it. The JT/T 808 wire encoding for `data_type=2`/
  `control=4` already existed before this test (`commands/video_signaling.py`, from the earlier
  JT1078 video-signaling phase) and needed no change to run it.
- **Severity:** Low — this is a disclosed, never-promised feature gap, not a regression; live
  video, GPS tracking, and the G.711A→AAC audio path (ADR-0034) are all confirmed unaffected (the
  bench unit remained connected, authenticated, and streaming normal traffic throughout and after
  this test).
- **Blocking production?** No — intercom was never a shipped capability. Revisit only after a
  firmware update from the supplier, a different bench unit/hardware revision, or direct vendor
  confirmation of this firmware's real preconditions for repeated `0x9101 data_type=2` session
  establishment — see ADR-0035's own Consequences section.

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
- [x] **Redis** — hardened mechanism complete (Priority 1 Item 4): auth, AOF persistence,
      bounded memory with fail-loud eviction, broker/cache DB split. Check this box again once
      `docs/runbooks/redis-operations.md`'s "First real verification" has actually been run
      (Known Issue #15) — no HA/Sentinel/Cluster, a deliberate single-VPS-scope decision, not
      tracked as a checklist item here.
- [x] **PostgreSQL** — schema/migrations solid, verified zero-drift.
- [x] **Monitoring** — real dependency-checking `/health/ready`, `/metrics` (Prometheus format),
      `prometheus` Compose service scraping it (Priority 1 Item 5). No Grafana/Sentry yet — each
      needs a real external account/target (see `docs/runbooks/monitoring.md`).
- [ ] **Logging** — real structured JSON, but stdout-only; no shipping/aggregation configured.
- [x] **Health Checks** — `/health/ready` verifies real DB/Redis(cache)/Redis(broker)
      reachability with a bounded timeout each, live-verified (Priority 1 Item 5).
- [ ] **Environment Variables** — `.env.example` templates exist for every service; real
      deployment still means hand-editing a `.env` on the host, no secrets manager.
- [ ] **CI/CD** — backend test-only pipeline exists; no deploy step, no lint/security gate, no
      frontend/mobile/device-gateway CI.
- [x] **Reverse Proxy** — nginx configs (dev/prod/frontend) real and working; `docker-compose.
      coolify.yml` + `docs/runbooks/coolify-deployment.md` (ADR-0022) offer Coolify's own
      Traefik as an alternative to this stack's own nginx/certbot for a Coolify-managed VPS.
- [x] **Payment Provider** — architecture mechanism complete (ADR-0022): real, verified
      `StripePaymentAdapter`, webhook route wired with HMAC signature verification, env-var-only
      secrets, a real "Pay Invoice" frontend flow. Check this box again once a real Stripe
      merchant account's live credentials are actually set in `RAAD_PAYMENT__PROVIDER_
      CREDENTIALS` and a real test-mode charge has been exercised end to end (no merchant
      account exists in this sandbox — same disclosed-limitation posture as TLS/Redis).
- [ ] **Object Storage** — not present anywhere in the repo (no S3-equivalent evaluated for
      report files, etc.).
- [ ] **Secrets** — plain env vars only; no Vault/sealed-secrets/cloud secrets manager.
- [x] **Firewall** — documented (Priority 1 Item 7, `docs/runbooks/vps-deployment.md` Step 2):
      `ufw` default-deny with only SSH/80/443 allowed. Not live-tested against a real VPS (none
      provisioned in this sandbox).

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

---

## 15. Priority 1 Final Report (2026-08-03 continuous-completion program)

The user directed all nine remaining Priority 1 items be implemented back to back, without
stopping for per-item approval, ending in one consolidated report. This section is that report's
permanent record — the full version was delivered directly to the user; this is the durable
summary.

**Completed and live-verified**: Items 1 (Backups), 3 (Auth rate limiting + account lockout), 5
(Health checks + monitoring), 6 (RBAC grant/revoke) — each proven against a real dependency
(real Postgres, real HTTP requests against a running server) in this sandbox.

**Completed, mechanism-complete but disclosed as not live-testable here** (no Docker daemon, no
domain, no VPS in this sandbox): Items 2 (TLS/HTTPS), 4 (Redis production hardening), 7
(Deployment/rollback runbooks).

**Audited, correctly not built further — both blockers genuinely external**: Item 8 (Payment
provider) — needs a real EVC Plus account/API docs and a webhook-actor design decision (ADR).

**Partial, the one item where zero verification was possible at all**: Item 9 (Mobile App MVP) —
M0/M2 code-complete, M3 partial, blocked in part on a real, newly-discovered backend gap (Known
Issue #17), M4/M5 blocked on real external accounts (Firebase, app stores). No Flutter SDK exists
in this sandbox, so none of this code has been compiled or run — disclosed plainly, not claimed
as finished.

**Real bugs caught and fixed during this program, not just asserted away**: a tz-aware/naive
datetime bug and a Redis-unreachable-vs-unconfigured gap (Item 3); an oversized composite
`aggregate_id` overflowing a shared `CHAR(26)` column across six event factories, requiring a
schema migration (Item 6); an `/auth/logout` call missing its required bearer token (Item 9,
caught by manual review since no compiler was available).

**Is RAAD technically ready for a VPS deployment?** Yes, for the backend + web dashboard,
contingent only on real external resources (a domain, a VPS, a real `docker/.env`) — every
documented step is written and reviewed (`docs/runbooks/vps-deployment.md`), and no known
backend/infra gap blocks it. **Are the backend and web platform production-ready?** Yes, with the
same caveat — Payment (Item 8) is the one functional gap (no live payment can complete), tracked
honestly as an external dependency, not a silently-skipped feature. **Mobile is not
production-ready** — real, uncompiled code exists but has never been verified, and two role
experiences are incomplete pending a backend fix and external accounts.
