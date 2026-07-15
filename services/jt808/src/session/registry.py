"""In-memory session registry (Phase 9.1 — Transport Layer only).

`.claude/rules/jt808.md` #4 names Redis as this state's eventual backing store, keyed
`device_id -> {node, vehicle_id, org_id, last_seen, auth_state}` once device identity exists
post-auth. This phase has no device identity and no Redis (explicitly out of scope) — a plain
in-process dict keyed by `connection_id`, discarded on process restart, is the honest state of
the world until a later phase adds both.
"""

from __future__ import annotations

from src.session.session import ConnectionSession


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, ConnectionSession] = {}

    def add(self, session: ConnectionSession) -> None:
        self._sessions[session.connection_id] = session

    def remove(self, connection_id: str) -> None:
        self._sessions.pop(connection_id, None)

    def get(self, connection_id: str) -> ConnectionSession | None:
        return self._sessions.get(connection_id)

    def all(self) -> list[ConnectionSession]:
        return list(self._sessions.values())

    def __len__(self) -> int:
        return len(self._sessions)
