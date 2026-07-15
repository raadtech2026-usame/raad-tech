"""A single accepted TCP connection (Phase 9.1 — Transport Layer only; Phase 3.4 §2/§20).

Owns the async read loop (bytes -> `FrameBuffer` -> raw frames -> `on_frame` callback) and a
queued async write loop (`send()` enqueues; a dedicated task drains the queue onto the
socket), so a future command-downlink phase can call `send()` without touching the read path.

**Protocol-agnostic by construction**: `on_frame` is an injected callback — this class knows
nothing about message IDs, handlers, or business logic (`.claude/rules/architecture.md`: "no
direct calls to Tracking, Fleet Device, or Organization"). The composition root (`server.py`,
via `ConnectionManager`) wires a log-only callback for this phase; a later phase's Packet
Dispatcher plugs in here without changing this class. `on_activity` and `on_close` are
likewise injected so lifecycle bookkeeping lives in `session/`/`connection/manager.py`, not
duplicated here.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from src.logging_setup import get_logger, log_with_fields
from src.protocol.framing import FrameBuffer, FrameTooLargeError

logger = get_logger("jt808.connection")

FrameHandler = Callable[[str, bytes], Awaitable[None]]


class Connection:
    def __init__(
        self,
        *,
        connection_id: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        read_chunk_size: int,
        max_frame_size: int,
        on_frame: FrameHandler,
        on_activity: Callable[[], None],
        on_close: Callable[[str], None],
    ) -> None:
        self.connection_id = connection_id
        self._remote_address = writer.get_extra_info("peername")
        self._reader = reader
        self._writer = writer
        self._read_chunk_size = read_chunk_size
        self._frame_buffer = FrameBuffer(max_frame_size=max_frame_size)
        self._on_frame = on_frame
        self._on_activity = on_activity
        self._on_close = on_close

        self._write_queue: "asyncio.Queue[bytes | None]" = asyncio.Queue()
        self._closing = False
        self._read_task: asyncio.Task | None = None
        self._write_task: asyncio.Task | None = None

    @property
    def remote_address(self) -> str:
        return str(self._remote_address)

    def start(self) -> None:
        """Launches the read and write loops as background tasks. Separate from `__init__` so
        a caller (`ConnectionManager`) can register the connection/session *before* the read
        loop can possibly race ahead and call `on_close`."""
        self._read_task = asyncio.create_task(self._read_loop())
        self._write_task = asyncio.create_task(self._write_loop())
        log_with_fields(
            logger,
            20,
            "connection_accepted",
            connection_id=self.connection_id,
            remote_address=self.remote_address,
        )

    async def send(self, data: bytes) -> None:
        """Enqueues bytes for the write loop — never writes to the socket directly, so
        callers never need to coordinate with the read loop or hold a lock."""
        if self._closing:
            return
        await self._write_queue.put(data)

    async def close(self, *, reason: str) -> None:
        """Graceful, idempotent shutdown: drains and stops the write loop, flushes+closes the
        socket, cancels the read loop if it isn't the caller itself, and notifies the owner
        exactly once. Safe to call from within the read loop (self-close on disconnect) or
        externally (manager timeout sweep / server shutdown) — checked via
        `asyncio.current_task()` so neither path cancels/awaits itself."""
        if self._closing:
            return
        self._closing = True
        log_with_fields(
            logger,
            20,
            "connection_closing",
            connection_id=self.connection_id,
            reason=reason,
        )

        await self._write_queue.put(None)  # sentinel: let the write loop drain and exit
        current = asyncio.current_task()
        if self._write_task is not None and self._write_task is not current:
            await self._write_task

        try:
            self._writer.close()
            await self._writer.wait_closed()
        except (ConnectionError, OSError):
            pass  # peer already gone — closing is still successful from our side

        if (
            self._read_task is not None
            and self._read_task is not current
            and not self._read_task.done()
        ):
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        log_with_fields(
            logger,
            20,
            "connection_closed",
            connection_id=self.connection_id,
            reason=reason,
        )
        self._on_close(self.connection_id)

    async def _read_loop(self) -> None:
        try:
            while True:
                data = await self._reader.read(self._read_chunk_size)
                if not data:
                    await self.close(reason="peer_disconnected")
                    return
                self._on_activity()
                try:
                    frames = self._frame_buffer.feed(data)
                except FrameTooLargeError:
                    log_with_fields(
                        logger, 30, "frame_too_large", connection_id=self.connection_id
                    )
                    await self.close(reason="frame_too_large")
                    return
                for frame in frames:
                    log_with_fields(
                        logger,
                        10,
                        "frame_received",
                        connection_id=self.connection_id,
                        frame_length=len(frame),
                    )
                    await self._on_frame(self.connection_id, frame)
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError) as exc:
            log_with_fields(
                logger,
                30,
                "read_loop_error",
                connection_id=self.connection_id,
                error=str(exc),
            )
            await self.close(reason="read_error")

    async def _write_loop(self) -> None:
        try:
            while True:
                item = await self._write_queue.get()
                if item is None:
                    return  # sentinel from close(): drain complete, exit cleanly
                try:
                    self._writer.write(item)
                    await self._writer.drain()
                except (ConnectionError, OSError) as exc:
                    log_with_fields(
                        logger,
                        30,
                        "write_loop_error",
                        connection_id=self.connection_id,
                        error=str(exc),
                    )
                    return
        except asyncio.CancelledError:
            raise
