# Rule: Frontend

Derived from `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §8.

1. **Feature-module organization** mirrors backend bounded contexts under `frontend/src/features/`.
2. **Role-based routing and rendering.** A route guard + capability check renders only what a role
   may see. This is presentation of server-enforced scope, not a second authorization system —
   never implement a client-only permission check without a matching server-side enforcement.
3. **Real-time data goes over WebSocket** (`/ws/tracking`, `/ws/notifications`), not REST polling.
4. **This rule governs the React web dashboard specifically: live video is Org-Admin-only there,
   and only reachable from the web dashboard** — never surface a video affordance for any other
   role on the web. Parent's own narrow video exception (ADR-0026, 2026-08-12) lives entirely on
   the Flutter mobile side (`.claude/rules/flutter.md` #3) — the web dashboard gains no new video
   surface from that ADR, and still has no Parent login at all.
5. **No persistent browser storage of sensitive data** (tokens use secure, short-lived storage
   patterns).
6. **Mapping is a pluggable provider abstraction** — do not hardcode a single map vendor into feature
   code.
