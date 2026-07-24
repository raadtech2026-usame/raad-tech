"""Session registry keyed by Terminal ID (Phase 9.2; Phase 3.4 §5's `SessionManager` contract:
`resolve(terminal_id) -> {...}`). In-memory only — `.claude/rules/jt808.md` #4 names Redis as
the eventual authoritative, cross-shard-shared backing store (`session:{terminal_id}`, Phase
3.4 §14); no multi-node deployment or Redis exists at this phase (Phase 9.1's precedent:
in-memory, single-node, Redis explicitly deferred).

**Thread-safe async, unlike Phase 9.1's `SessionRegistry`.** `SessionRegistry`'s
add/get/remove are synchronous dict operations with no `await` between a check and its
matching mutation, so single-threaded asyncio's cooperative scheduling already makes them
atomic. `add_exclusive` here is different: implementing the single-active-session rule
(ADR-808-8 — "newest authenticated connection wins") requires atomically checking whether a
session already exists for a `terminal_id` *and* replacing it in one step, and the caller
(`DeviceSessionManager.create`) then `await`s closing the old connection — a real window where
two concurrent `create()` calls for the *same* `terminal_id` (e.g. a flapping device retrying
fast) could otherwise both believe they safely superseded the other. `asyncio.Lock` closes
that window.
"""

from __future__ import annotations

import asyncio

from src.session.device_session import DeviceSession


class DeviceSessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, DeviceSession] = {}
        self._lock = asyncio.Lock()

    async def add_exclusive(self, session: DeviceSession) -> DeviceSession | None:
        """Registers `session`, atomically returning whatever session previously occupied
        `session.terminal_id` (or `None` if this is the first). The caller is responsible for
        superseding/closing the returned session — this method only guarantees the registry
        itself never briefly holds two sessions for the same terminal."""
        async with self._lock:
            previous = self._sessions.get(session.terminal_id)
            self._sessions[session.terminal_id] = session
            return previous

    def get(self, terminal_id: str) -> DeviceSession | None:
        return self._sessions.get(terminal_id)

    def remove_if_current(self, terminal_id: str, session: DeviceSession) -> None:
        """Removes the registry entry for `terminal_id` only if it still *is* `session`
        (identity check) — guards a superseded session's own belated close-cleanup from
        deleting the newer session that already replaced it (the reconnect/supersede race
        this registry exists to prevent, `add_exclusive`'s docstring)."""
        current = self._sessions.get(terminal_id)
        if current is session:
            self._sessions.pop(terminal_id, None)

    def find_by_connection_id(self, connection_id: str) -> DeviceSession | None:
        for session in self._sessions.values():
            if session.connection_id == connection_id:
                return session
        return None

    def all(self) -> list[DeviceSession]:
        return list(self._sessions.values())

    def __len__(self) -> int:
        return len(self._sessions)
