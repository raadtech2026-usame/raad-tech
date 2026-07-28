# ADR-0020: Platform Analytics Read-Model

## Status
Accepted (direct user decision — RAAD business model realignment, 2026-07-28).

## Context
The new RAAD business model requires a Super Admin (Platform Dashboard) view showing
platform-wide KPIs: Total/Active/Suspended Organizations, Total/Online/Offline Devices, Total
Vehicles, Live Vehicle Locations, Active Drivers, New Organizations Today, New Users Today, MAU,
Subscription/Billing Status, Expiring Organizations, Revenue, System Health.

No aggregate/count/stats capability exists anywhere in this backend today — confirmed by
searching every module's `api/routers.py` for stats/summary/kpi/dashboard endpoints (none found).
`DashboardHomePage.tsx` (frontend) deliberately shows a static placeholder today for exactly this
reason (CLAUDE.md: "no aggregate summary endpoint exists on the backend to back them, and
fabricating numbers here would break this project's own 'fail loudly, don't fake it' posture").

`.claude/rules/backend.md` #3 forbids cross-module DB reads — any stats capability must compose
each owning module's own read query methods, not reach into another module's tables directly.
This is exactly the shape `interfaces/http/policy_guards.py` already established for CR-1/D5
enforcement (orchestrating multiple modules' *application services*), just applied here to
read-only aggregation instead of authorization.

One specific requested KPI — **Online/Offline Devices** — cannot be honestly answered today:
`devices.last_seen_at` is never populated. `DeviceOnline`/`DeviceOffline` events are published by
the device-gateway (ADR-0010's `RedisEventPublisher`) but this backend has no consumer for them —
a previously-flagged, known gap (`docs/architecture/device-onboarding-readiness-audit.md`).

## Decision

### 1. Ownership: `platform_audit` (C10)
The existing home for cross-cutting, read-only, platform-level admin views (`AuditEntry`,
`SystemSetting`). A new `PlatformStatsApplicationService` there composes the response by calling
each owning module's own, new, additive, read-only query methods:
- `organization`: count by status, count created today, count expiring soon (subscription tie-in
  via `billing`).
- `iam`: count active users (optionally scoped by organization), count with `last_login_at`
  within a trailing 30-day window (MAU), count created today.
- `fleet_device`: count devices (by online/offline once §3 below lands), count vehicles.
- `billing`: revenue summary (sum of paid invoices in a period), subscription status breakdown,
  count of subscriptions expiring within N days.

`platform_audit` never queries another module's tables directly — every number is composed from
a call to that module's own public application-service surface, preserving
`.claude/rules/backend.md` #1/#3 exactly, the same guarantee `policy_guards.py` already
demonstrates is achievable for cross-module orchestration in this codebase.

### 2. Route
`GET /admin/platform-stats` (under the existing `/admin` → `platform_audit` mapping,
`.claude/rules/api.md` #2), gated by the same permission-holder set as `GET /admin/audit`
(Founder/Regional Manager/Support Staff/Finance Staff per current `/admin` access) plus a new
dedicated permission if the existing grant proves too coarse at implementation time.

### 3. Closing the Online/Offline Devices gap: a new `DeviceOnline`/`DeviceOffline` consumer
A new broker consumer, mirroring the existing `BrokerFanOutWorker`/Notification Worker shape
(`core.workers.base.Worker` lifecycle, one failure logged and isolated, never crashing the
surrounding loop), subscribing to `DeviceOnline`/`DeviceOffline` events and updating
`devices.last_seen_at` (already a column) plus a new `devices.is_online` boolean flag. This is an
explicit scope addition to this milestone, flagged rather than silently assumed: without it, an
"Online/Offline Devices" KPI would have to be fabricated or omitted, and this project's own
"fail loudly, don't fake it" posture (already invoked twice in this exact spot — the F7 Live
Monitoring phase and the device-onboarding-readiness-audit) rules out faking it.

### 4. "System Health" — best-effort, not a new observability platform
Scoped conservatively: database reachability, whether the broker (`RAAD_BROKER__URL`) is bound,
and background-worker heartbeat status (reusing whatever minimal healthcheck already exists from
ADR-0013's platform dockerization work). Explicitly not a new metrics/tracing/alerting system —
that would be scope creep beyond what any document asks for.

## Consequences
- New, additive read/count query methods land in four existing modules' application layers — no
  existing method's behavior changes.
- One new table column (`devices.is_online`), one new broker consumer process/thread.
- `DashboardHomePage.tsx`'s static Platform Dashboard placeholder is replaced with a real KPI
  grid — the Organization Dashboard home is unaffected (the requested KPI list is entirely
  platform-level; no org-scoped stats were requested for `/org`).
- Every number shown is either a real, freshly-queried count, or (Online/Offline Devices) backed
  by a now-real event consumer — none are fabricated placeholders.

## Verification
- Unit: each new count/aggregate query method, independently.
- Integration: the `DeviceOnline`/`DeviceOffline` consumer actually flips `is_online`/
  `last_seen_at` on a real published event (extends the existing `verify_redis_e2e.py`-style
  live-Redis verification already used for ADR-0012).
- `tests/architecture/` gate suite re-run — confirms `platform_audit`'s new composition still
  performs zero cross-module DB reads.

## References
- `docs/architecture/device-onboarding-readiness-audit.md` (the Online/Offline gap this ADR
  closes)
- `.claude/rules/backend.md` #1, #3
- `.claude/rules/api.md` #2 (`/admin` → `platform_audit`)
- `docs/architecture/adr/0010-device-gateway-multi-vendor-architecture.md` (`DeviceOnline`/
  `DeviceOffline` event source)
- `raad/interfaces/http/policy_guards.py` (the cross-module orchestration precedent reused here)
- `raad/modules/platform_audit/`, `raad/interfaces/workers/notification_worker.py` (the
  `BrokerFanOutWorker`/Worker shape the new consumer mirrors)
