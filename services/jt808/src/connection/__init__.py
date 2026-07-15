"""TCP connection acceptance and lifecycle management (Phase 9.1 — Transport Layer only;
Phase 2 §5.1, Phase 3.4 §2/§20).

`Connection` owns one accepted socket's async read/write loops and frame boundary detection;
`ConnectionManager` owns the set of all connections, the session registry, and the periodic
idle-timeout sweep. Neither imports anything from `backend.raad` or any business module
(`.claude/rules/architecture.md`: "no direct calls to Tracking, Fleet Device, or
Organization") — frames are handed to an injected callback, never interpreted here.
"""
