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

**Attribution is to a device stream, not a viewer's session (ADR-0046 §2).** A connection is
matched once, on its first frame, to the relay-owned stream of that terminal, channel and kind
(`SessionManager.resolve_ingest_stream`); every session watching that stream shares it. The
connection remembers the stream generation it was matched in: when the stream restarts or ends,
frames still arriving on the old connection close it instead of feeding the new generation's
viewers. A newer connection for the same running stream supersedes (closes) the older one, since a
terminal that reconnects after a radio blip leaves the old socket half-dead on this side.

**One `ExtendedRtpStreamDemuxer` + `FrameReassembler` pair per connection** — a fresh instance for
every accepted TCP connection, discarded when that connection closes (ADR-0024 §4: no state
survives beyond an active session's own connection).

**A device connection never outlives its session (2026-09-19).** Ending a session closed the
browser's sockets but never the device's ingest connection, and this handler kept reading from it
and discarding every frame — so a device that keeps streaming after its stop command had nothing
on the relay's side to make it stop. Production on 2026-09-19: the MDVR acknowledged `0x9102`
(result 0) for three channel-1 sessions yet kept streaming for 17+ minutes, 0.4–2.8 Mbps of SIM
data going nowhere, apparently when live video and two-way intercom overlapped on channel 1. Now
`close_session_connections` closes every device connection correlated to a session when the relay
removes it, and a connection that delivers a frame after its session is gone is closed on the
spot (`ingest_connection_closed_session_ended`). A device that then reconnects with no session
to match is rejected by the existing unsolicited-connection path.
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
        #: ADR-0036. `None` keeps callers without an intercom path unchanged.
        self._uplink_registry = uplink_registry
        self._server: asyncio.base_events.Server | None = None
        self._connections: set[asyncio.StreamWriter] = set()
        #: Device connections attributed to each stream.
        self._stream_connections: dict[str, set[asyncio.StreamWriter]] = {}

    @property
    def bound_port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("IngestServer is not started.")
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_connection, self._host, self._port)

    def close_stream_connections(self, stream_id: str) -> int:
        """Closes every device connection attributed to `stream_id` (the stream ended or is
        restarting). Returns how many were still open."""
        writers = self._stream_connections.pop(stream_id, set())
        closed = 0
        for writer in writers:
            if not writer.is_closing():
                writer.close()
                closed += 1
        return closed

    # Pre-ADR-0046 name; connections are keyed by stream, no longer by session.
    close_session_connections = close_stream_connections

    def open_connection_count(self, stream_id: str) -> int:
        return len(self._stream_connections.get(stream_id, ()))

    async def stop(self) -> None:
        for writer in list(self._connections):
            writer.close()
        self._connections.clear()
        self._stream_connections.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._connections.add(writer)
        # A bare connect is logged so "the device never dialed" and "dialed but sent nothing
        # valid" stay distinguishable after the fact.
        peer = writer.get_extra_info("peername")
        log_with_fields(logger, 20, "ingest_connection_accepted", peer_address=str(peer))
        demuxer = ExtendedRtpStreamDemuxer()
        reassembler = FrameReassembler()
        stream_id: str | None = None
        generation: int | None = None
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
                    if stream_id is None:
                        stream = self._session_manager.resolve_ingest_stream(
                            frame.sim_card_number, frame.logical_channel, is_audio=frame.is_audio
                        )
                        if stream is None:
                            log_with_fields(
                                logger,
                                30,
                                "unsolicited_ingest_connection_rejected",
                                sim_card_number=frame.sim_card_number,
                                logical_channel=frame.logical_channel,
                                is_audio=frame.is_audio,
                            )
                            return
                        stream_id, generation = stream.stream_id, stream.generation
                        superseded = self._attach(stream_id, writer)
                        log_with_fields(
                            logger,
                            20,
                            "ingest_connection_correlated",
                            stream_id=stream_id,
                            generation=generation,
                            kind=stream.kind.value,
                            logical_channel=frame.logical_channel,
                            is_audio=frame.is_audio,
                            superseded_connections=superseded,
                        )
                        self._session_manager.note_ingest_connected(stream_id)
                        await self._session_manager.mark_stream_active(stream_id)
                        if self._uplink_registry is not None:
                            self._uplink_registry.register(
                                stream_id,
                                writer=writer,
                                sim_card_number=frame.sim_card_number,
                                logical_channel=frame.logical_channel,
                            )
                    else:
                        current = self._session_manager.resolve_stream(stream_id)
                        if current is None or current.generation != generation:
                            # The stream ended or restarted, but the device is still sending on
                            # this connection: stop accepting the orphaned media.
                            log_with_fields(
                                logger,
                                30,
                                "ingest_connection_closed_session_ended",
                                stream_id=stream_id,
                                generation=generation,
                                peer_address=str(peer),
                                logical_channel=frame.logical_channel,
                            )
                            return
                        self._session_manager.touch_stream(stream_id)
                    reassembled = reassembler.feed(frame)
                    if reassembled is not None:
                        await self._on_reassembled_frame(stream_id, reassembled)
        finally:
            self._connections.discard(writer)
            if stream_id is not None:
                remaining = self._detach(stream_id, writer)
                if self._uplink_registry is not None:
                    self._uplink_registry.unregister(stream_id, writer=writer)
                # The device's own close ends the stream at once rather than ~60 s later on the
                # idle sweep (packet-verified 2026-09-02). A no-op when the relay closed this
                # connection itself, or when a newer connection or generation carries the stream.
                await self._session_manager.handle_ingest_disconnected(
                    stream_id, generation=generation, remaining_connections=remaining
                )
            if not writer.is_closing():
                writer.close()

    def _attach(self, stream_id: str, writer: asyncio.StreamWriter) -> int:
        """Registers `writer` for `stream_id`, closing any older connection of that stream.
        Returns how many were superseded."""
        writers = self._stream_connections.setdefault(stream_id, set())
        superseded = 0
        for older in list(writers):
            writers.discard(older)
            if not older.is_closing():
                older.close()
                superseded += 1
        writers.add(writer)
        return superseded

    def _detach(self, stream_id: str, writer: asyncio.StreamWriter) -> int:
        writers = self._stream_connections.get(stream_id)
        if writers is None:
            return 0
        writers.discard(writer)
        if not writers:
            del self._stream_connections[stream_id]
            return 0
        return len(writers)
