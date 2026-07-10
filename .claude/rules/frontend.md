# Rule: Frontend

Derived from `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §8.

1. **Feature-module organization** mirrors backend bounded contexts under `frontend/src/features/`.
2. **Role-based routing and rendering.** A route guard + capability check renders only what a role
   may see. This is presentation of server-enforced scope, not a second authorization system —
   never implement a client-only permission check without a matching server-side enforcement.
3. **Real-time data goes over WebSocket** (`/ws/tracking`, `/ws/notifications`), not REST polling.
4. **Live video is Org-Admin-only, and only reachable from the web dashboard** — never surface a
   video affordance for any other role.
5. **No persistent browser storage of sensitive data** (tokens use secure, short-lived storage
   patterns).
6. **Mapping is a pluggable provider abstraction** — do not hardcode a single map vendor into feature
   code.
