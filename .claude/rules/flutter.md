# Rule: Flutter

Derived from `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §9.

1. **One codebase, two role experiences** (Parent, Driver) via RBAC — no admin features on mobile.
2. **The Driver app does not stream the phone's GPS as the tracking source.** Location comes from
   the bus MDVR/GPS terminal via the backend; the Driver app is a control/UI client (start/end trip,
   view assignments).
3. **No live video anywhere in the mobile app for Driver, unconditionally.** For Parent, video is
   off by default and reachable only when that parent's own organization admin has explicitly
   granted `video_live_access`/`video_playback_access` (ADR-0026, 2026-08-12, narrowly amending
   this rule — see that ADR for the full reasoning, including why this reverses, rather than
   contradicts, the platform's own original `Project_Brief_v1.md` §4.8 requirement). The mobile
   UI affordance (`features/video/`) is presentation only — showing/hiding it is never the real
   authorization; the Business API independently re-verifies the grant and ownership on every
   request (`.claude/rules/backend.md` #7). No frontend or Flutter work gives Driver a video
   affordance under any circumstance.
4. **Parent live GPS is active-trip-only.** Outside active trips, show history and transport-payment
   status only — never a stale/misleading "live" indicator.
5. **Clean architecture layering:** presentation (screens + state management) → domain (use-cases,
   entities) → data (repositories, REST/WebSocket clients, local cache). Tokens live in secure
   storage; other state may use local cache for offline resilience.
6. **Offline/safety UI never fails silently.** Degrade visibly with clear "last updated / stale"
   indicators when connectivity drops.
