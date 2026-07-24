"""DeviceSessionManager (Phase 9.2; Phase 3.4 §5's `SessionManager` contract, minus the parts
that need infrastructure this phase doesn't have — see below). Owns `DeviceSession` lifecycle:
creation after authentication, duplicate-terminal supersession (ADR-808-8), liveness
(`touch`), expiration, and the bridge from a dropped transport connection to closing whatever
device session was bound to it.

**Resolved documentation conflict (Phase 3.4 §21.1 vs §3/Phase 2 §21.1), confirmed with the
user before implementing:** §21.1's sequence diagram shows `device.online` emitted immediately
after the `0x8001` auth response, before any heartbeat. Both state-machine diagrams (Phase 3.4
§3, Phase 2 §21.1) and the Device Plane draft's restatement instead show a distinct
`Authenticated -> Online` edge labeled "heartbeat + location reporting" / "first heartbeat/
location". This module implements the state-machine reading: `create()` produces a session in
`AUTHENTICATED` state; the *first* `touch()` call promotes it to `ONLINE` and fires
`on_device_online`. The sequence diagram is treated as an illustrative simplification, not a
literal ordering — consistent with the draft's "`DeviceOnline`/`DeviceOffline` are emitted
*only* on debounced transitions" note, which implies more than bare auth-success alone.

**What Phase 3.4 §5's contract asks for that this phase deliberately does not build:**
- `resolve(terminal_id) -> {..., node_id, ...}` and `bind_command_route` — cross-shard command
  routing assumes a multi-node deployment; nothing in this phase's scope introduces one, and
  no node identity concept exists yet. `resolve()` here (this class's `get`) returns the
  `DeviceSession` itself, which already carries every field except `node_id`.
- Redis as the backing store (`.claude/rules/jt808.md` #4) — `DeviceSessionRegistry` is
  in-memory, matching Phase 9.1's identical, already-accepted stance.
- Actually emitting `DeviceOnline`/`DeviceOffline` **domain events** (over an outbox/broker) —
  that needs `src/events/` (not built) and is arguably business-adjacent publishing this
  phase's "no business logic" boundary excludes. `on_device_online`/`on_device_offline`/
  `on_session_superseded` are injected callbacks, defaulting to log-only, exactly mirroring
  `connection/manager.py`'s `_default_on_frame` pattern — a later phase wires a real event
  publisher here without changing this class.
- Credential/token verification (`.claude/rules/jt808.md` #5's "unauthenticated devices
  rejected") — `create()` assumes the caller (a future `AuthHandler`) already verified the
  auth token; this class does zero verification of its own, per the task's explicit split
  between "bind after successful authentication" (this phase) and "authentication packet
  handling" (not this phase).
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from src.logging_setup import get_logger, log_with_fields
from src.session.device_session import DeviceConnectivityState, DeviceSession
from src.session.device_session_registry import DeviceSessionRegistry

logger = get_logger("jt808.device_session_manager")

OnDeviceOnline = Callable[[DeviceSession], None]
OnDeviceOffline = Callable[[DeviceSession, str], None]
OnSessionSuperseded = Callable[[DeviceSession, DeviceSession], None]
CloseConnection = Callable[[str, str], Awaitable[None]]


def _default_on_device_online(session: DeviceSession) -> None:
    log_with_fields(logger, 20, "device_online", terminal_id=session.terminal_id)


def _default_on_device_offline(session: DeviceSession, reason: str) -> None:
    log_with_fields(
        logger, 20, "device_offline", terminal_id=session.terminal_id, reason=reason
    )


def _default_on_session_superseded(old: DeviceSession, new: DeviceSession) -> None:
    log_with_fields(
        logger,
        30,
        "session_superseded",
        terminal_id=old.terminal_id,
        old_connection_id=old.connection_id,
        new_connection_id=new.connection_id,
    )


class DeviceSessionManager:
    def __init__(
        self,
        *,
        registry: DeviceSessionRegistry,
        close_connection: CloseConnection,
        on_device_online: OnDeviceOnline | None = None,
        on_device_offline: OnDeviceOffline | None = None,
        on_session_superseded: OnSessionSuperseded | None = None,
    ) -> None:
        self._registry = registry
        self._close_connection = close_connection
        self._on_device_online = on_device_online or _default_on_device_online
        self._on_device_offline = on_device_offline or _default_on_device_offline
        self._on_session_superseded = (
            on_session_superseded or _default_on_session_superseded
        )
        self._sweep_task: asyncio.Task | None = None

    async def create(
        self,
        *,
        connection_id: str,
        terminal_id: str,
        device_id: str | None = None,
        vehicle_id: str | None = None,
        organization_id: str | None = None,
    ) -> DeviceSession:
        """Phase 3.4 §5's `create(terminal_id, connection_ref) -> Session # after auth`,
        verbatim naming. Called only *after* the caller has already verified credentials —
        see module docstring. Duplicate-terminal handling (ADR-808-8, Phase 3.4 §17): if a
        session already exists for `terminal_id` on a *different* connection, that connection
        is closed and its session superseded; re-authenticating on the *same* connection is
        not a supersede."""
        session = DeviceSession(
            terminal_id=terminal_id,
            connection_id=connection_id,
            device_id=device_id,
            vehicle_id=vehicle_id,
            organization_id=organization_id,
        )
        previous = await self._registry.add_exclusive(session)

        log_with_fields(
            logger,
            20,
            "device_authenticated",
            terminal_id=terminal_id,
            connection_id=connection_id,
        )

        if previous is not None and previous.connection_id != connection_id:
            self._on_session_superseded(previous, session)
            await self._close_connection(previous.connection_id, "superseded")

        return session

    def touch(self, terminal_id: str) -> None:
        """Phase 3.4 §5's `touch(terminal_id, at)` — "heartbeat/location updates last_seen".
        No message parsing happens here (Phase 9.2 scope); a future heartbeat/location
        handler calls this once it exists. The first call after `create()` promotes
        `AUTHENTICATED -> ONLINE` — see module docstring's resolved conflict."""
        session = self._registry.get(terminal_id)
        if session is None:
            return
        session.touch()
        if session.state == DeviceConnectivityState.AUTHENTICATED:
            session.mark_online()
            self._on_device_online(session)

    def resolve(self, terminal_id: str) -> DeviceSession | None:
        """Phase 3.4 §5's `resolve(terminal_id) -> {...}` — returns the `DeviceSession`
        itself rather than a separate dict (see module docstring re: `node_id`/`auth_state`).
        """
        return self._registry.get(terminal_id)

    async def close(self, terminal_id: str, *, reason: str) -> None:
        """Phase 3.4 §5's `close(terminal_id, reason)` — "emits device.offline" (here: fires
        `on_device_offline`, module docstring). Idempotent: closing an already-gone session is
        a no-op."""
        session = self._registry.get(terminal_id)
        if session is None:
            return
        session.mark_offline()
        self._registry.remove_if_current(terminal_id, session)
        self._on_device_offline(session, reason)

    async def handle_connection_closed(self, connection_id: str) -> None:
        """Bridges a dropped transport connection (`connection/manager.py`'s
        `on_connection_closed` hook, Phase 9.2 addition) to closing whatever `DeviceSession`
        was bound to it — socket drop, peer disconnect, or idle-timeout at the transport layer
        all funnel through here. A no-op if no `DeviceSession` was ever bound to this
        connection (e.g. it disconnected before authenticating)."""
        session = self._registry.find_by_connection_id(connection_id)
        if session is None:
            return
        await self.close(session.terminal_id, reason="connection_closed")

    def start_sweep(self, *, timeout_seconds: float, interval_seconds: float) -> None:
        self._sweep_task = asyncio.create_task(
            self._sweep_loop(
                timeout_seconds=timeout_seconds, interval_seconds=interval_seconds
            )
        )

    async def stop_sweep(self) -> None:
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass
            self._sweep_task = None

    async def _sweep_loop(
        self, *, timeout_seconds: float, interval_seconds: float
    ) -> None:
        try:
            while True:
                await asyncio.sleep(interval_seconds)
                await self._sweep_once(timeout_seconds=timeout_seconds)
        except asyncio.CancelledError:
            raise

    async def _sweep_once(self, *, timeout_seconds: float) -> None:
        """Session expiration (Phase 3.4 §9's watchdog / the Device Plane draft's "Session
        Expired": no approved numeric heartbeat-interval/miss-factor exists anywhere —
        `timeout_seconds` is caller-configured, the same "don't invent a protocol constant"
        stance Phase 9.1's `idle_timeout_seconds` already takes."""
        now = time.monotonic()
        expired = [
            session.terminal_id
            for session in self._registry.all()
            if now - session.last_seen_at > timeout_seconds
        ]
        for terminal_id in expired:
            await self.close(terminal_id, reason="session_expired")

    async def shutdown(self) -> None:
        """Graceful shutdown: stop the sweep, close every remaining device session."""
        await self.stop_sweep()
        for session in list(self._registry.all()):
            await self.close(session.terminal_id, reason="server_shutdown")

    @property
    def session_count(self) -> int:
        return len(self._registry)
