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

## Status

**Foundational app shell implemented**: build tooling, routing, the `RouteGuard` role-based guard,
login flow (`POST /auth/login` end-to-end), the REST client (typed error envelope, auth-header
injection, 401-refresh-retry), and the generic WebSocket hook. No feature module
(`features/*`) has real UI yet — each lands as its own phase. 16 tests passing
(`npm run test`); `npm run build` produces a working production bundle.
