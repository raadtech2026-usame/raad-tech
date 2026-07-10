# Rule: Flutter

Derived from `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §9.

1. **One codebase, two role experiences** (Parent, Driver) via RBAC — no admin features on mobile.
2. **The Driver app does not stream the phone's GPS as the tracking source.** Location comes from
   the bus MDVR/GPS terminal via the backend; the Driver app is a control/UI client (start/end trip,
   view assignments).
3. **No live video anywhere in the mobile app**, for either role.
4. **Parent live GPS is active-trip-only.** Outside active trips, show history and transport-payment
   status only — never a stale/misleading "live" indicator.
5. **Clean architecture layering:** presentation (screens + state management) → domain (use-cases,
   entities) → data (repositories, REST/WebSocket clients, local cache). Tokens live in secure
   storage; other state may use local cache for offline resilience.
6. **Offline/safety UI never fails silently.** Degrade visibly with clear "last updated / stale"
   indicators when connectivity drops.
