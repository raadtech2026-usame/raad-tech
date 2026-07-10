# RAAD Platform

RAAD is a cloud-based School Bus Tracking and Student Transportation Management Platform. It gives
schools, transport operators, drivers, and parents real-time visibility and control over school bus
operations, built on the JT808 (GPS/telematics) and JT1078 (live video) open telematics protocols.

This repository is currently in **Phase 4.1 — Project Structure Initialization**. It contains the
approved repository scaffold (folders, placeholder files, and configuration templates) only. No
business logic, API endpoints, database models, or UI have been implemented yet.

## Source of Truth

Do not implement features by guessing. All structure and future implementation must trace back to:

- `CLAUDE.md` — product scope, domain vocabulary, and durable engineering guardrails.
- `docs/business/` — the approved business and architecture documentation (Project Brief, Enterprise
  Architecture, Backend LLD, Database Design, API Contracts, JT808 Technical Design, JT1078 Technical
  Design).
- `docs/architecture/` — architecture decision records (ADRs) and diagrams (seeded, to be populated
  as architectural decisions are formally recorded going forward).

## Repository Layout

| Path | Purpose |
|---|---|
| `backend/` | FastAPI modular-monolith Business API (`raad_business_api`). |
| `frontend/` | React + TypeScript web dashboard (RAAD staff + Organization Admins). |
| `mobile/` | Flutter mobile app (Parent + Driver roles, single codebase). |
| `services/jt808/` | JT808 TCP server — GPS/telematics device connectivity plane. |
| `services/jt1078/` | JT1078 video server — live/playback media relay (Org Admin only). |
| `shared/` | Cross-service shared contracts (event schemas, API contracts, shared constants). |
| `infrastructure/` | NGINX, Redis, MySQL, monitoring, logging, deployment, and backup configuration. |
| `docker/` | Dockerfiles and Docker Compose orchestration for local/dev/prod environments. |
| `ci-cd/` | CI/CD pipeline definitions per deployable. |
| `scripts/` | Developer and operational scripts (DB migration/seed, bootstrap, CI helpers). |
| `testing/` | Cross-service testing: end-to-end, load, and shared fixtures. |
| `docs/` | Business documentation, architecture records, generated API docs, runbooks. |
| `.claude/` | Claude Code development environment: agents, rules, skills, commands, templates. |

## Engineering Guardrails

- RAAD is **not** a school ERP. See `CLAUDE.md` for explicit out-of-scope domains.
- JT808 and JT1078 are first-class architectural concerns, not implementation details.
- Every module in `backend/raad/modules/` follows an identical internal shape
  (`api/ domain/ application/ infra/ events/`) — see `.claude/rules/backend.md`.
- No cross-module database reads; modules communicate via application services or domain events.

## Status

Greenfield structural scaffold. Tech stack, build tooling, and conventions are recorded in
`docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md` and related Phase 3 documents. This file will be
updated as implementation begins.
