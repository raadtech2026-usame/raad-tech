# RAAD Platform — Phase 3.3: API Contracts (LLD)

**Prepared by:** Senior Enterprise Software Architect
**Phase:** 3.3 — API Contracts (design documentation only; **no implementation code**)
**Traceability:** Phase-2 Architecture, Backend LLD (§14 errors, §16 routers, §10 events), Database Design (Phase 3.2), decisions **D1–D6**, **CR-1**.

> **Notation.** Endpoints are given as **method + path + auth + purpose** tables; models as **field tables + example JSON**. Example JSON is illustrative *data*, not code. Full OpenAPI is generated at build time from these contracts.

---

## 1. Conventions & Base

- **Base URL:** `https://api.raad.example/api/v1` (versioned — §9).
- **Transport:** HTTPS only (Phase-2 §12.4). JSON request/response (`application/json`).
- **Auth:** `Authorization: Bearer <access_jwt>` on all routes except `/auth/login`, `/auth/refresh`, `/auth/password/*`, and health.
- **Standard request headers:** `Authorization`, `Idempotency-Key` (required on payment POSTs — §12), `X-Request-Id` (optional; echoed as `correlation_id`).
- **Standard response headers:** `X-Request-Id`, `X-RateLimit-*`.
- **Timestamps:** ISO-8601 UTC (`2026-07-10T08:30:00.000Z`).
- **IDs:** opaque ULID strings.
- **Tenant/scope:** derived from the JWT (never from a query param) — a client cannot request another tenant's data by changing an id (returns `404`, §5, Phase-2 §12.3).

---

## 2. Authentication

### 2.1 Endpoints
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/auth/login` | public | Exchange credentials → access + refresh tokens |
| POST | `/auth/refresh` | refresh token | Rotate access token |
| POST | `/auth/logout` | bearer | Revoke refresh token |
| POST | `/auth/password/forgot` | public | Begin password reset (LLD §12.1) |
| POST | `/auth/password/reset` | reset token | Complete reset |
| GET | `/auth/me` | bearer | Current principal + role + scope |

### 2.2 Models

**Login request**
```json
{ "identifier": "admin@school.edu", "password": "••••••••" }
```
`identifier` = email or phone (E.164).

**Token response**
```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_token": "def50200...",
  "principal": { "user_id": "01J...", "role": "org_admin", "organization_id": "01J...", "region_ids": [] }
}
```

- **Access token** = short-lived JWT (e.g., 15 min); **refresh token** = long-lived, rotated on use, revocable (LLD §17).
- **JWT claims:** `sub` (user_id), `role`, `org_id?`, `scope` (region/org for RAAD staff), `jti`, `exp`, `iat`.
- **MFA (recommended for privileged roles):** if enabled, `/auth/login` returns `mfa_required` and a challenge id; a `/auth/mfa/verify` step completes login.

---

## 3. Authorization Model

### 3.1 Layers (all enforced server-side; UI hints are advisory)
1. **Authentication** — valid access token.
2. **RBAC** — role→permission matrix per endpoint (Backend LLD §17; roles from Ch. 4).
3. **Tenant/region scope** — `organization_id` (tenant users) and `effective_org_scope` (RAAD staff, Phase-2 §17) intersect every query.
4. **Domain policies** — `SubscriptionAccessPolicy` (**CR-1**, parent access) and `VideoAccessPolicy` (**D5**, video), enforced in application/domain, not the router (so no entry point bypasses them).

### 3.2 Role → capability (summary)
| Capability | Founder | Reg. Mgr | Support | Finance | Org Admin | Driver | Parent |
|-----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Platform admin | ✅ | – | – | – | – | – | – |
| Manage orgs (in scope) | ✅ | ✅(region) | ✅(assigned) | – | self-org | – | – |
| Ops monitoring (live GPS) | ✅ | ✅(region, r/o) | ✅(assigned, r/o) | ❌ | ✅ 24/7 | own trip | active-trip only |
| Live video / playback | ✅* | ✅*(permitted) | ✅*(permitted) | ❌ | ✅ own org | ❌ | ❌ **(D5)** |
| Billing/invoices | ✅ | – | – | ✅ | own org | – | own (parent-pays) |
| Start/End trip | – | – | – | – | – | ✅ own | – |

`*` platform/RAAD-staff video access is governed and **audited**; parents are excluded by construction (D5).

### 3.3 Parent access guard (CR-1)
Every **Parent-scoped** route runs the `SubscriptionAccessPolicy` guard. On DENY it returns `403` with a body describing the reason and required action (§5.4), **except** the subscription/payment routes (so a Parent-Pays parent can still renew).

```json
{ "error": { "code": "PARENT_ACCESS_DENIED", "reason": "SUBSCRIPTION_EXPIRED",
  "required_action": "REDIRECT_TO_PAYMENT", "correlation_id": "01J..." } }
```
`reason ∈ {SUBSCRIPTION_EXPIRED, ASSIGNMENT_INACTIVE}`; `required_action ∈ {REDIRECT_TO_PAYMENT, NONE}`.

---

## 4. Resource Endpoints (representative)

> CRUD follows a uniform pattern per resource: `GET /x` (list), `POST /x` (create), `GET /x/{id}`, `PATCH /x/{id}`, `DELETE /x/{id}` (soft delete). Only notable/behavioral routes are expanded.

### 4.1 Organizations, Regions, Users (C1/C2)
| Method | Path | Role | Notes |
|--------|------|------|-------|
| GET/POST | `/organizations` | Founder, Reg.Mgr(region), Support(assigned) | scope-filtered |
| GET/PATCH | `/organizations/{id}` | in-scope | `billing_model` here (CR-1 input) |
| GET/POST | `/regions` | Founder | |
| POST | `/regions/{id}/assignments` | Founder | assign Regional Manager |
| GET/POST | `/users` | in-scope admin | role-restricted creation |
| POST | `/users/{id}/disable` | in-scope admin | |

### 4.2 Fleet & Device (C3)
| Method | Path | Role | Notes |
|--------|------|------|-------|
| GET/POST | `/vehicles` | Org Admin (+RAAD in scope) | |
| GET/POST | `/devices` | Org Admin / Support | lifecycle state |
| POST | `/devices/{id}/activate` | Support/Org Admin | Registered→Activated |
| POST | `/devices/{id}/assign` | Org Admin | body `{vehicle_id}` → creates active `device_assignment` |
| POST | `/devices/{id}/reassign` | Org Admin | closes prior, opens new (Phase-2 §19) |
| POST | `/devices/{id}/unassign` | Org Admin | |
| GET | `/devices/{id}/status` | Org Admin | connectivity (online/offline) |

> **Change driver ≠ device op.** Driver changes go through trip/assignment routes (§4.3); there is **no** device endpoint involved (Phase-2 §19.1).

### 4.3 Transport Operations (C4)
| Method | Path | Role | Notes |
|--------|------|------|-------|
| GET/POST | `/students` | Org Admin | |
| POST | `/students/{id}/status` | Org Admin | body `{status}` → disable/graduate/transfer → **emits CR-1 revocation** |
| GET/POST | `/parents` | Org Admin | |
| GET/POST | `/routes` | Org Admin | |
| GET/POST | `/routes/{id}/stops` | Org Admin | ordered stops |
| GET/POST | `/student-assignments` | Org Admin | the CR-1 gate record |
| POST | `/student-assignments/{id}/end` | Org Admin | status→removed/transferred/… → **CR-1 revocation event** |
| GET/POST | `/trips` | Org Admin | scheduled trips |
| POST | `/trips/{id}/start` | **Driver** (own) | → `TripStarted` (Phase-2 §6.2) |
| POST | `/trips/{id}/end` | **Driver** (own) | → `TripEnded` |
| PATCH | `/trips/{id}/driver` | Org Admin | change driver — **no device change** |

**Trip start response**
```json
{ "id":"01J...","status":"in_progress","trip_type":"morning",
  "vehicle_id":"01J...","driver_id":"01J...","route_id":"01J...","started_at":"2026-07-10T05:30:00Z" }
```

### 4.4 Tracking (C5)
| Method | Path | Role | Notes |
|--------|------|------|-------|
| GET | `/tracking/vehicles/{id}/latest` | Org Admin 24/7; Parent active-trip+granted | latest position (from Redis) |
| GET | `/tracking/trips/{id}/positions` | Org Admin; Parent (own child, granted) | history (partitioned store); paginated |
| WS | `/ws/tracking` | see §11 | live stream |

Parent tracking routes pass through both the **active-trip** gate (Phase-2 §23) and the **CR-1** guard.

### 4.5 Video (C6) — **Org Admin only (D5)**
| Method | Path | Role | Notes |
|--------|------|------|-------|
| POST | `/video/live` | **Org Admin** (+permitted RAAD) | body `{device_id, camera_id}` → returns media session token/URL |
| POST | `/video/playback` | Org Admin | body `{device_id, camera_id, window_start, window_end}` |
| POST | `/video/sessions/{id}/stop` | Org Admin | teardown |

Parent role has **no** video route (returns `403`, audited). Camera `position=in_cabin` never streamed to non-admins (D5).

### 4.6 Notifications (C7)
| Method | Path | Role | Notes |
|--------|------|------|-------|
| GET | `/notifications` | any authenticated | own in-app notifications (paginated) |
| POST | `/notifications/{id}/read` | recipient | mark read |
| POST | `/notifications/tokens` | Parent/Driver | register FCM token |
| DELETE | `/notifications/tokens/{id}` | owner | revoke token |
| WS | `/ws/notifications` | see §11 | live in-app push mirror |

### 4.7 Billing (C8)
| Method | Path | Role | Notes |
|--------|------|------|-------|
| GET | `/billing/plans` | in-scope | |
| GET | `/billing/subscriptions` | Org Admin/Finance; Parent(own) | |
| GET | `/billing/invoices` | Org Admin/Finance; Parent(own) | |
| POST | `/billing/payments` | Org Admin/Finance; **Parent(own, allowed even when access-denied)** | **requires `Idempotency-Key`**; EVC Plus (Phase-2 §20) |
| POST | `/billing/payments/callback` | provider (signed) | verified webhook (§12) |

**Payment request**
```json
{ "invoice_id":"01J...","method":"evcplus","msisdn":"+2526••••••","amount":10.00,"currency":"USD" }
```
**Payment response**
```json
{ "payment_id":"01J...","status":"processing","required_action":"AWAIT_PHONE_CONFIRMATION" }
```

### 4.8 Reports (C9) & Admin/Audit (C10)
| Method | Path | Role | Notes |
|--------|------|------|-------|
| POST | `/reports/runs` | Org Admin/Finance | async render → `report_run` |
| GET | `/reports/runs/{id}` | requester | status + artifact url |
| GET | `/admin/audit` | Founder / in-scope admin | audit log (scoped, read-only) |
| GET/PATCH | `/admin/settings` | Founder / Org Admin | system/org settings |

---

## 5. Error Model

### 5.1 Envelope (uniform — Backend LLD §14)
```json
{ "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable, safe summary.",
    "correlation_id": "01J...",
    "details": [ { "field": "msisdn", "issue": "invalid E.164 format" } ]
} }
```

### 5.2 Code catalogue & HTTP mapping
| HTTP | `code` | When |
|------|--------|------|
| 400 | `BAD_REQUEST` | malformed request |
| 401 | `UNAUTHENTICATED` | missing/invalid/expired token |
| 403 | `FORBIDDEN` | RBAC/scope denies |
| 403 | `PARENT_ACCESS_DENIED` | **CR-1** guard (carries `reason` + `required_action`) |
| 403 | `VIDEO_FORBIDDEN` | **D5** — non-admin video attempt (audited) |
| 404 | `NOT_FOUND` | not found **or out-of-scope** (no tenant probing, Phase-2 §12.3) |
| 409 | `CONFLICT` | invariant violation (e.g., vehicle already has an active trip) |
| 409 | `RULE_VIOLATION` | illegal state transition (e.g., start an already-in-progress trip) |
| 422 | `VALIDATION_ERROR` | field-level validation |
| 402/502 | `PAYMENT_ERROR` | provider failure/declined (Phase-2 §20) |
| 429 | `RATE_LIMITED` | throttle |
| 500 | `INTERNAL_ERROR` | opaque; `correlation_id` for tracing |

- **Never leak** stack traces, SQL, or internal ids in `message`.
- **404-over-403** for cross-tenant misses to prevent resource enumeration.

---

## 6. Request / Response Model Conventions

- **Requests:** validated in three layers (transport/application/domain, LLD §15). Unknown fields rejected. Enums are lowercase snake strings matching the DB value sets (Phase 3.2).
- **Resource responses** include: `id`, all business fields, `created_at`, `updated_at`. Soft-deleted resources are omitted from lists by default (LLD §7). Timestamps UTC ISO-8601.
- **Write responses** return the full resource (or `202 Accepted` + a job handle for async, e.g., reports/payments).
- **Partial updates** use `PATCH` with only the changed fields; concurrency via `If-Match: <row_version>` where optimistic locking applies (returns `409` on stale write).

**Example resource (student assignment — CR-1 gate)**
```json
{ "id":"01J...","organization_id":"01J...","student_id":"01J...","route_id":"01J...",
  "pickup_stop_id":"01J...","dropoff_stop_id":"01J...","vehicle_id":"01J...",
  "status":"active","assigned_at":"2026-07-01T00:00:00Z","ended_at":null,
  "created_at":"...","updated_at":"..." }
```

---

## 7. Pagination

- **Default: cursor-based** (stable under inserts, efficient on time-ordered data like positions/notifications).
- **Query params:** `?limit=50&cursor=<opaque>`. `limit` default 25, max 100.
- **Offset pagination** (`?page=1&page_size=25`) offered for admin tables where total counts matter.

**List envelope**
```json
{ "data": [ /* items */ ],
  "page": { "limit": 50, "next_cursor": "eyJ...", "has_more": true } }
```
Offset variant adds `"total": 1234, "page": 1, "page_size": 25`.

---

## 8. Filtering & Sorting

- **Filtering:** `?filter[<field>]=<value>` with typed operators via suffix: `filter[status]=active`, `filter[created_at][gte]=2026-07-01`, `filter[trip_type][in]=morning,afternoon`. Allowed fields are whitelisted per resource (no arbitrary column filtering).
- **Full-text/search:** `?q=<term>` on search-enabled resources (e.g., students, vehicles).
- **Sorting:** `?sort=field` (asc) or `?sort=-field` (desc); multiple: `?sort=-scheduled_date,trip_type`. Sortable fields whitelisted and indexed (Phase 3.2 §11.2).
- **Scope is implicit and non-overridable:** filters can never widen tenant/region scope — they only narrow within it.

---

## 9. Versioning

- **URI versioning:** `/api/v1`. Breaking changes → `/api/v2`; additive changes stay in `v1`.
- **Deprecation policy:** a superseded version is announced via `Deprecation` + `Sunset` response headers and supported for a defined window before removal.
- **Payload/event versioning:** event contracts carry their own `version` (§13); DTOs evolve additively within a REST version.

---

## 10. (reserved — see §11 WebSocket, §12 Payments, §13 Events)

---

## 11. WebSocket Contracts

Two channels, both authenticated and scope-enforced (Backend LLD §7.3, §16.2).

### 11.1 Connection & auth
- **Connect:** `wss://api.raad.example/ws/tracking` (and `/ws/notifications`).
- **Auth:** access token passed at connection (subprotocol or first `auth` frame); the same RBAC + scope + policies as REST apply. Unauthorized/denied → close with a policy code.
- **Heartbeat:** ping/pong; idle timeout closes the socket.

### 11.2 `/ws/tracking`
**Client → server (subscribe)**
```json
{ "type":"subscribe", "channel":"vehicle", "vehicle_id":"01J..." }
```
Authorization at subscribe time:
- **Org Admin** — any in-org vehicle, 24/7.
- **Parent** — only a vehicle on an **active trip** carrying the parent's child **and** a **granted `SubscriptionAccessPolicy`** decision (**CR-1**). Otherwise the subscribe is rejected.

**Server → client (position update)**
```json
{ "type":"position","vehicle_id":"01J...","trip_id":"01J...",
  "lat":2.0469,"lng":45.3182,"speed_kph":34,"heading_deg":120,"event_time":"2026-07-10T05:41:02Z" }
```

**Server → client (lifecycle / revocation)**
```json
{ "type":"subscription_closed","vehicle_id":"01J...","reason":"trip_ended" }
```
`reason ∈ {trip_ended, access_revoked, assignment_inactive, subscription_expired}` — the socket is **closed server-side immediately** on a CR-1 revoking event (Phase-2 §23.2, LLD §5.4).

### 11.3 `/ws/notifications`
- **Subscribe:** implicit to the authenticated user's own stream.
- **Server → client:**
```json
{ "type":"notification","id":"01J...","category":"trip_started",
  "title":"Morning trip started","body":"...", "trip_id":"01J...","created_at":"..." }
```
- Mirrors the FCM push + in-app store (D2). For parents, delivery is subject to the CR-1 access decision (denied parents receive no transport notifications — LLD §11).

---

## 12. Payment Callback & Idempotency Contract (EVC Plus — Phase-2 §20)

- **Initiation:** `POST /billing/payments` **requires** `Idempotency-Key`; a repeat with the same key returns the original result (no double charge).
- **Async confirmation:** `POST /billing/payments/callback` is the provider webhook — **signature/secret verified**; unverified callbacks rejected + audited (treated as untrusted input). Body is provider-shaped and normalized by the adapter.
- **Reconciliation:** a scheduled job re-queries `pending/processing` payments lacking a terminal callback (lost-webhook handling).
- **Safety note (CR-1):** payment endpoints remain reachable by a Parent-Pays parent **even while access-denied**, so they can renew; success flips the subscription to `active`, which lifts the CR-1 denial.

---

## 13. Event Contracts (domain events — Backend LLD §10, Phase-2 §6)

### 13.1 Envelope (all events)
```json
{ "event_id":"01J...", "event_type":"trip.started", "version":1,
  "occurred_at":"2026-07-10T05:30:00Z", "organization_id":"01J...",
  "correlation_id":"01J...", "aggregate":{"type":"trip","id":"01J..."},
  "payload": { /* type-specific */ } }
```
- **At-least-once delivery; consumers idempotent by `event_id`** (LLD §10.3).
- **Versioned** per type; breaking payload change → new `version`.
- Published via the **transactional outbox** after commit.

### 13.2 Catalogue (MVP)
| `event_type` | Producer | Key payload | Primary consumers |
|--------------|----------|-------------|-------------------|
| `device.position_reported` | JT808 plane | vehicle_id, lat, lng, speed, heading, event_time, is_backfill | Tracking (geofence), live fan-out |
| `device.online` / `device.offline` | JT808 plane | device_id, at | Device monitoring, alarms |
| `trip.started` / `trip.ended` | Transport-Ops | trip_id, vehicle_id, route_id, at | Tracking, Notifications |
| `trip.interrupted` | Transport-Ops/Tracking | trip_id, reason | Notifications, monitoring |
| `geofence.approaching_stop` | Tracking | trip_id, stop_id | Notifications (parents at that stop) |
| `geofence.arrived_org` | Tracking | trip_id | Notifications |
| `video.session_started` / `video.session_ended` | Video | session_id, device_id, camera_id, actor | Audit |
| `subscription.expired` / `subscription.renewed` | Billing | subscription_id, subscriber | **CR-1 access re-eval**, Notifications |
| `student.assignment_changed` | Transport-Ops | student_id, assignment_id, new_status | **CR-1 access re-eval** (revocation), Notifications |
| `payment.confirmed` / `payment.failed` | Billing | payment_id, invoice_id, status | Subscription, Notifications, Audit |

> `student.assignment_changed` with `new_status ∈ {removed,transferred,graduated,disabled}` and `subscription.expired` are the two events that **immediately revoke** parent access and trigger live-socket teardown (CR-1, §11.2).

### 13.3 Notification catalogue (delivered to clients — D1/D2)
`trip_started`, `approaching_stop`, `arrived_org`, `trip_completed` (transport, geofence/lifecycle — D1); plus `subscription`/`system` (billing/system class). No student-level boarding events (D1).

---

## 14. Design Rationale Summary

| ID | Decision | Rationale | Trace |
|----|----------|-----------|-------|
| API-1 | URI versioning `/v1`; additive within, `/v2` for breaking | Predictable evolution for web + Flutter clients | Phase-2 §1.1 |
| API-2 | Uniform error envelope + code catalogue; 404-over-403 | Consistent clients; no tenant enumeration | LLD §14, Phase-2 §12.3 |
| API-3 | Scope derived from JWT, never from params; filters only narrow | Tenant/region isolation cannot be widened by a client | Phase-2 §12.3, §17 |
| API-4 | `SubscriptionAccessPolicy` guard on all parent routes; payment routes exempt | Encodes CR-1; parents can always renew | **CR-1** |
| API-5 | Video routes Org-Admin-only; no parent path; audited | Encodes D5 | **D5** |
| API-6 | Cursor pagination default; offset for admin tables | Stable, efficient on time-ordered data | Phase 3.2 §11 |
| API-7 | Whitelisted filter/sort fields, indexed | Safe, performant querying | Phase 3.2 §11.2 |
| API-8 | Idempotency-Key required on payments; signed callbacks | No double charge; untrusted-callback safety | Phase-2 §20.4 |
| API-9 | WS subscribe re-checks active-trip + CR-1; server-side teardown on revocation | "Immediately loses access" honored on live channel | Phase-2 §23, CR-1 |
| API-10 | Versioned, idempotent events via outbox | Reliable, evolvable event backbone | LLD §10 |

---

*End of Phase 3.3 — API Contracts. Documentation only; no implementation code. Full OpenAPI/AsyncAPI specs are generated from these contracts at build time.*

