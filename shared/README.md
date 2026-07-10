# Shared Libraries

Cross-service contracts and constants consumed by more than one deployable (backend, JT808 server,
JT1078 server, frontend, mobile). Nothing here should contain business logic — only contract
definitions and stable shared values.

## Structure

- `event-contracts/` — canonical schemas for domain events crossing the event bus
  (e.g. `DevicePositionReported`, `TripStarted`, `NotificationRequested`). Mirrors
  `backend/raad/shared_contracts/events/` as the cross-service-visible copy.
- `api-contracts/` — versioned OpenAPI/AsyncAPI specs generated at build time from the Business API
  (`/api/v1`). Consumed by frontend/mobile client generation and by external integrators.
- `constants/` — shared enums and constants that must stay identical across services (e.g. role
  names, permission keys, JT808/JT1078 message IDs used at integration boundaries).

## Rule

Event and API contracts are the single source of truth for cross-service data shapes. A breaking
change here requires a version bump (`/api/v1` → `/api/v2`, or an event schema version field) per
`.claude/rules/api.md`.

## Status

Structural scaffold only. No schemas or generated contracts exist yet.
