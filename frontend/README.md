# Frontend — RAAD Web Dashboard

React + TypeScript single-page application serving RAAD staff (Founder, Regional Manager, Support,
Finance) and Organization Administrators. This is the only client surface where live video is
reachable (Org Admin only — parents never see in-cabin video).

Source of truth: `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §8.

## Structure

```
src/
├── app/            # app shell, routing, providers
├── features/       # feature modules mirroring backend bounded contexts
│   ├── organizations/
│   ├── fleet-devices/
│   ├── transport-ops/
│   ├── live-monitoring/
│   ├── video/
│   ├── notifications/
│   ├── billing/
│   ├── reports/
│   └── admin/
├── shared/
│   ├── components/  # design-system components
│   ├── hooks/
│   ├── api/         # REST client + WebSocket client
│   ├── stores/       # UI/session state
│   └── utils/
├── config/
└── assets/
```

## Access model

Role-based routing and rendering: a route guard + capability check renders only what a role may see
(Founder = platform-wide, Regional Manager = region-scoped, Org Admin = single-tenant). See
`.claude/rules/frontend.md` and `.claude/rules/security.md`.

## Real-time

Live map and live notifications are delivered over WebSocket (`/ws/tracking`, `/ws/notifications`),
fanned out via the backend's Redis Streams broker (`backend/raad/interfaces/http/realtime.py`).
`shared/hooks/useWebSocket.ts` implements the documented connect/first-auth-frame protocol
(API Contracts §11.1) generically; each feature sends its own subscribe frames via the hook's
`send`.

## Tech stack

Vite + TypeScript, React Router (routing), TanStack Query (REST server state), Zustand (UI/session
state), Vitest + React Testing Library (tests). See `package.json`.

## Auth

`shared/stores/authStore.ts` holds the `Principal` and access/refresh tokens **in memory only** —
never `localStorage`/`sessionStorage`/a cookie (`.claude/rules/frontend.md` #5). A hard page reload
loses the session by design; `shared/api/client.ts` auto-retries once after a token refresh on a
401 before giving up.

## Design system

The approved visual design (`docs/architecture/RAAD Console (Standalone).html` +
`docs/architecture/logo-raad.png`) has been extracted into `src/styles/tokens.css` (colors,
typography, spacing, radii, shadows) and a reusable component library in `shared/components/`
(`Button`, `Badge`, `Card`, `Avatar`, `DataTable`, `DetailDrawer`, `Toast`, etc.) — not a 1:1 HTML
port. See CLAUDE.md's "Frontend Implementation Status" section for the full extraction
methodology and the specific, flagged departures from the raw mockup (accessibility fixes,
loading/empty states the mockup never depicted, a rationalized spacing/type scale).

## Two dashboards

RAAD ships a **Platform Dashboard** (`/platform/*` — Founder, Regional Manager, Support Staff,
Finance Staff; manages every organization, including provisioning new ones) and an **Organization
Dashboard** (`/org/*` — Org Admin only; scoped to their own organization). Driver and Parent have
no web dashboard at all (mobile-only roles) — see `shared/auth/dashboard.ts` and
`app/layout/navConfig.ts`.

## Status

**Phase F0 (design system + app shell) complete**: build tooling, routing (including the
two-dashboard redirect-by-role flow above), the `RouteGuard` role-based guard, login flow
(`POST /auth/login` end-to-end, now branded), the REST client (typed error envelope, auth-header
injection, 401-refresh-retry), the generic WebSocket hook, and the full design-system component
library + app shell (`Sidebar`/`TopBar`/`AppShell`). No feature module (`features/*`) has real
data-fetching UI yet — every nav item routes to a real page: the built feature, or an honest
`PlaceholderPage` until its own roadmap phase lands (see
`docs/architecture/frontend-flutter-master-roadmap.md`). 42 tests passing (`npm run test`);
`npm run build` produces a working production bundle.
