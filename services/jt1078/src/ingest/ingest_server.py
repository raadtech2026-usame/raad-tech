"""`IngestServer` — the TCP listener a device connects to directly once `0x9101`/`0x9201`
signaling has told it this relay's ingest host:port (ADR-0024 §1/§6/§7). One shared, well-known
port for every session (not one port per session) — a new inbound connection is correlated to a
pending/active `VideoSession` by the extended-RTP frame's own SIM card number *and*
`logical_channel` (`ExtendedRtpFrame.sim_card_number`/`.logical_channel`, matched against
`VideoSession.terminal_id`/`.logical_channel`), per ADR-0024 §1's own "the relay's own
correctness anchor for that socket remains identity/session correlation... never by trusting the
connection's source IP alone." **`logical_channel` is required in the match, not just identity**
(`session/session_manager.py`'s own module docstring has the full real-bug history) — a device
with several of its own cameras all live-requested at once has several concurrently-`REQUESTED`
sessions sharing one `terminal_id`, and a terminal-id-only match cannot tell their independent
ingest connections apart.

**Unsolicited connections are rejected and audited** (ADR-0024 §1/§15, mirroring `jt808.md` #5):
if the *first* frame's identity doesn't correlate to any `REQUESTED`/`ACTIVE` session on that
exact channel, the connection is closed immediately — no frames from an unrecognized device (or
a channel with no pending session) are ever fed to the reassembler/repackager/viewer pipeline.

**One `ExtendedRtpStreamDemuxer` + `FrameReassembler` pair per connection** — a fresh instance for
every accepted TCP connection, discarded when that connection closes (ADR-0024 §4: no state
survives beyond an active session's own connection).
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from src.ingest.extended_rtp import ExtendedRtpStreamDemuxer, MalformedExtendedRtpFrameError
from src.ingest.frame_reassembly import FrameReassembler, ReassembledFrame
from src.logging_setup import get_logger, log_with_fields
from src.session.session_manager import SessionManager
from src.session.uplink_registry import IngestConnectionRegistry

logger = get_logger("jt1078_relay.ingest.server")

OnReassembledFrame = Callable[[str, ReassembledFrame], Awaitable[None]]

_READ_CHUNK_SIZE = 4096


class IngestServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        session_manager: SessionManager,
        on_reassembled_frame: OnReassembledFrame,
        uplink_registry: IngestConnectionRegistry | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._session_manager = session_manager
        self._on_reassembled_frame = on_reassembled_frame
        #: ADR-0036. `None` (default) keeps every pre-existing caller/test unchanged — no uplink
        #: bridging happens unless a real registry is wired in (`relay.py`'s composition root).
        self._uplink_registry = uplink_registry
        self._server: asyncio.base_events.Server | None = None
        self._connections: set[asyncio.StreamWriter] = set()

    @property
    def bound_port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("IngestServer is not started.")
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_connection, self._host, self._port)

    async def stop(self) -> None:
        for writer in list(self._connections):
            writer.close()
        self._connections.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._connections.add(writer)
        # Bug 2 observability fix: previously this class logged nothing at all on a bare TCP
        # connect — the only log lines were `malformed_ingest_frame` (a parse failure) and
        # `unsolicited_ingest_connection_rejected` (a *decoded* frame with no matching session).
        # A device that never connects at all and a device that connects but never sends a single
        # valid frame were therefore indistinguishable after the fact - exactly the ambiguity that
        # left session `01M1EQZE1D1831D74MHXCTDGQP`'s failure unprovable from logs alone. This one
        # line closes that gap without changing any behavior.
        peer = writer.get_extra_info("peername")
        log_with_fields(logger, 20, "ingest_connection_accepted", peer_address=str(peer))
        demuxer = ExtendedRtpStreamDemuxer()
        reassembler = FrameReassembler()
        session_id: str | None = None
        try:
            while True:
                chunk = await reader.read(_READ_CHUNK_SIZE)
                if not chunk:
                    break
                try:
                    frames = demuxer.feed(chunk)
                except MalformedExtendedRtpFrameError as exc:
                    log_with_fields(logger, 30, "malformed_ingest_frame", error=str(exc))
                    break

                for frame in frames:
                    if session_id is None:
                        # Bug 2 fix: `is_audio` lets `resolve_ingest_by_terminal_id` prefer an
                        # INTERCOM session over a same-channel LIVE/PLAYBACK session (or vice
                        # versa) when both are pending for this device — see that method's own
                        # docstring for the full reasoning and the real scenario this closes.
                        session = self._session_manager.resolve_ingest_by_terminal_id(
                            frame.sim_card_number, frame.logical_channel, is_audio=frame.is_audio
                        )
                        if session is None:
                            log_with_fields(
                                logger,
                                30,
                                "unsolicited_ingest_connection_rejected",
                                sim_card_number=frame.sim_card_number,
                                logical_channel=frame.logical_channel,
                                is_audio=frame.is_audio,
                            )
                            return
                        session_id = session.session_id
                        # Bug 2 observability fix: the success path previously logged nothing at
                        # all - a silent correlation is indistinguishable from "no frame ever
                        # arrived" once the connection later closes. `kind` is the one field that
                        # would have made the LIVE-vs-INTERCOM ambiguity this fix resolves visible
                        # in production logs, not just provable by reading the code.
                        log_with_fields(
                            logger,
                            20,
                            "ingest_connection_correlated",
                            session_id=session_id,
                            kind=session.kind.value,
                            logical_channel=frame.logical_channel,
                            is_audio=frame.is_audio,
                        )
                        await self._session_manager.mark_ingest_active(session_id)
                        if self._uplink_registry is not None:
                            self._uplink_registry.register(
                                session_id,
                                writer=writer,
                                sim_card_number=frame.sim_card_number,
                                logical_channel=frame.logical_channel,
                            )
                    else:
                        self._session_manager.touch_ingest(session_id)

                    reassembled = reassembler.feed(frame)
                    if reassembled is not None:
                        await self._on_reassembled_frame(session_id, reassembled)
        finally:
            self._connections.discard(writer)
            if session_id is not None:
                if self._uplink_registry is not None:
                    self._uplink_registry.unregister(session_id)
                # 2026-09-02: act on the device's own close immediately instead of letting the
                # idle sweep infer it ~60s later. Packet-verified against the physical bench
                # unit: after a radio-link outage the MDVR sends FIN on every JT/T 1078
                # connection rather than resuming, and that FIN lands here. A no-op when the
                # session is already gone (i.e. *we* closed this connection during a normal
                # teardown) — see `SessionManager.handle_ingest_disconnected`'s own docstring.
                await self._session_manager.handle_ingest_disconnected(session_id)
            if not writer.is_closing():
                writer.close()
