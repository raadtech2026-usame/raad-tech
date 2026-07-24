"""JT808 TCP transport service (Phase 9.1 — Transport Layer only).

Independent deployable — never imports from `backend.raad` and is never imported by it
(`.claude/rules/architecture.md` #2). Scope this phase: TCP accept, connection lifecycle,
frame boundary detection, session registry, idle-timeout infrastructure. No packet parsing,
message handlers, auth, GPS/alarm processing, Redis, or business-module calls — see each
submodule's docstring for the exact line each one stops at.
"""
