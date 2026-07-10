# Mobile — RAAD Flutter App

Single Flutter codebase (Android + iOS) rendering two role experiences via RBAC: **Parent** and
**Driver**. No admin features and no live video on mobile (video is Org Admin-only, web dashboard
only).

Source of truth: `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §9.

## Structure

```
lib/
├── main.dart
├── app/          # app entrypoint, role-based shell/navigation
├── core/         # cross-cutting: auth, networking, secure storage, theming
├── features/
│   ├── parent/    # assigned children, live GPS during active trips, trip history,
│   │              # transport-payment status, notifications
│   └── driver/    # assigned vehicle/route/students/stops, start/end trip controls
├── shared/        # shared widgets/utilities across both role experiences
└── data/          # repositories, REST client, WebSocket client, local cache
```

## Important clarification

Live location originates from the **bus MDVR/GPS terminal**, not the phone. The Driver app is a
control/UI client (start/end trips, view assignments) — it does not stream the phone's GPS as the
tracking source.

## Layering

Clean architecture: presentation (screens + state management) → domain (use-cases/entities) → data
(repositories, REST/WebSocket clients, local cache).

## Status

Structural scaffold only. No screens, state management, or platform configuration are implemented
yet.
