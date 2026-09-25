# Frontend — RAAD Web Dashboard

Enterprise React + TypeScript single-page application serving RAAD platform staff (Founder, Regional Manager, Support Staff, Finance Staff) and Organization Administrators (School Principals & Transportation Bursars).

Source of truth: `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §8.

---

## 1. Structure

```
src/
├── app/            # App shell, routing, providers, layout, dashboard home
│   ├── dashboard/  # Dashboard composed operational sections
│   └── layout/     # AppShell, Sidebar, TopBar, navConfig
├── features/       # Feature modules mirroring backend bounded contexts
│   ├── admin/             # Users and platform access control
│   ├── billing/           # RAAD SaaS subscriptions, plans, platform finance
│   ├── fleet-devices/     # Vehicles, hardware devices, inventory
│   ├── live-monitoring/   # Real-time GPS tracking, vehicle operations HUD, map
│   ├── notifications/     # In-app notification center and alert ledger
│   ├── organizations/     # Multi-tenant organizations and regional scope
│   ├── platform-analytics/# Platform telemetry metrics and audit stream
│   ├── reports/           # Report catalog and PDF/Excel preview & exports
│   ├── school-erp/        # School tuition fee plans, parent invoices, income/expenses
│   ├── transport-ops/     # Routes, trips, stops, students, parents, drivers
│   └── video/             # JT/T 1078 multi-camera live video wall & intercom
├── shared/
│   ├── components/  # Enterprise design system component primitives
│   ├── hooks/       # Reusable React hooks (pagination, WebSockets)
│   ├── map/         # Mapbox GL JS abstraction provider and markers
│   ├── api/         # REST API client + WebSocket client
│   ├── stores/      # Zustand in-memory state (auth, subscriptions, toasts)
│   └── utils/
├── config/
└── styles/          # Design tokens (tokens.css) & global styles (global.css)
```

---

## 2. RAAD Enterprise Design System

The RAAD UI is engineered as an enterprise IoT and telematics operations platform communicating precision, safety, real-time mobility, and commercial SaaS reliability.

### Design Principles
1. **Operational Mission Control**: Real-time telemetry (GPS fixes, speed, active trips, terminal connections) takes visual precedence over decorative elements.
2. **Strict Semantic Status**:
   - `Success / Online / Active`: Emerald (`#10b981`, `#065f46`, tint `#ecfdf5`). Used for active vehicles, valid 3D GPS fixes, and completed payments.
   - `Warning / Maintenance / Caution`: Amber (`#f59e0b`, `#92400e`, tint `#fffbeb`). Used for dead reckoning/stale GPS, vehicles under maintenance, or partial invoices.
   - `Danger / Offline / Error`: Rose (`#ef4444`, `#991b1b`, tint `#fef2f2`). Used for disconnected devices, retired terminals, or critical alarms.
   - `Info / In-Transit`: Electric Blue (`#1e63ff`, `#1e40af`, tint `#eff6ff`). Used for scheduled runs, active subscriptions, and platform updates.
3. **Information-Dense Without Clutter**: High-density tabular views (`DataTable`), sticky headers with backdrop blur (`12px`), tabular numerics (`font-variant-numeric: tabular-nums`), and mono formatting for hardware identifiers (`JetBrains Mono`).
4. **Unified Slate Neutral Ramp**: 14-step cool slate scale (`--n-0` `#ffffff` to `--n-950` `#020617`) eliminating muddiness between nested cards, panels, and borders.
5. **Tactile & Sub-Pixel Depth**: Multi-layer diffuse shadows (`--shadow-xs` to `--shadow-xl`), top-edge button specular highlights, 1px press displacement (`translateY(1px)`), and glassmorphism headers.

### Typography Scale
- **Display / Headings**: *Sora* (`--font-display`), with optical negative tracking (`-0.024em`) on display sizes.
- **UI & Body**: *Manrope* (`--font-body`), optimized for high legibility at 13px–16px.
- **Telemetry & Technical**: *JetBrains Mono* (`--font-mono`), applied to ULIDs, SIM phone numbers, coordinates, timestamps, and speeds.

---

## 3. Real-Time Telematics & Video

- **Live GPS Tracking**: Real-time coordinates delivered over `/ws/tracking` using `useVehiclePosition` backed by Redis DB 1 pub/sub streams. Invalid coordinates (`gpsFixStatus === "no_fix"`) are filtered from the live vehicle pin to prevent Shenzhen factory jumping.
- **Live Video Streaming**: Multi-camera grid (`MultiCameraVideoPanel`) supporting 1x1, 2x2, and focus modes over WebSocket-FLV (`mpegts.js`), connecting to `services/jt1078/` on port 7911. Gated strictly to Org Admins and platform staff.

---

## 4. Access & Navigation Model

Two discrete operational dashboards governed by `app/router.tsx` and `app/layout/navConfig.ts`:
- **Platform Dashboard** (`/platform/*`): Founder, Regional Manager, Support Staff, Finance Staff. Manages tenants, device inventory, global vehicle fleet, platform billing, and corporate audit logs.
- **Organization Dashboard** (`/org/*`): Org Admin only. Scoped strictly to the school's own students, parents, vehicles, drivers, trips, live video feeds, and tuition fee ERP.

Parents and Drivers operate on mobile applications and have no web login.

---

## 5. Security & Invariants

- **Zero In-Browser Token Persistence**: Access and refresh tokens are stored exclusively in memory via Zustand (`useAuthStore`). Tokens are cleared on tab closure (`.claude/rules/frontend.md` #5).
- **Tenant Scope Enforcement**: The frontend passes JWTs; the backend `ScopeResolver` and repository layer enforce tenant isolation.
- **Subscription gate**: `SubscriptionGate.tsx` redirects an Org Admin whose organization has no subscription in good standing to `/org/subscription` before any dashboard page loads. It is presentation only; `interfaces/http/subscription_guard` enforces the same rule on every `/api/v1` route server-side (ADR-0039).

---

## 6. Build & Test

```bash
# Run tests
npm test

# Production build & typecheck
npm run build
```
