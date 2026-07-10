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
fanned out via Redis pub/sub on the backend.

## Status

Structural scaffold only. No components, routes, or state management are implemented yet.
