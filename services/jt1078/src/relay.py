"""`Jt1078Relay` — the single process entrypoint (mirrors `device-gateway`'s own `gateway.
DeviceGateway` composition-root shape). Wires `SessionManager`, `IngestServer`, `ViewerServer`,
the per-session `SessionBroadcastHub` dict, and the Redis-backed event publisher/token guard when
a broker is configured.

**`session_id -> SessionBroadcastHub` lifecycle is kept in lockstep with `SessionManager`'s own
session lifecycle** via `on_session_created`/`on_session_removed` hooks — a hub exists exactly
while its session does, never longer (ADR-0024 §4: no state survives beyond an active session).

**Session *creation* is a Redis list-based RPC (`session/session_request_server.
SessionRequestServer`, bound below whenever a broker is configured)** — the Business API's own
`Jt1078RelayAdapter` (`backend/raad/modules/video/infra/`) is that transport's real caller,
closing the gap the prior phase's own implementation report flagged ("no approved document
specifies the backend<->relay transport"). `Jt1078Relay.create_live_session`/
`create_playback_session` remain as a direct, in-process Python API too (used by this class's own
tests and any future in-process caller) — the RPC server is a thin wrapper around the identical
`SessionManager.create_session` call, not a second code path with different behavior.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable

from redis.asyncio import Redis

from src.broker_config import BrokerConfig
from src.codec.aac_transcoder import AAC_LC_8KHZ_MONO_AUDIO_SPECIFIC_CONFIG, AacTranscoder
from src.config import RelayConfig
from src.events.publisher_port import LoggingSessionEventPublisher, SessionEventPublisher
from src.events.redis_session_event_publisher import RedisSessionEventPublisher
from src.ingest.frame_reassembly import ReassembledFrame
from src.ingest.ingest_server import IngestServer
from src.logging_setup import configure_logging, get_logger, log_with_fields
from src.session.device_stream import DeviceStream
from src.session.session_manager import SessionManager
from src.session.session_request_server import SessionRequestServer
from src.session.uplink_registry import IngestConnectionRegistry
from src.session.video_session import VideoSession, VideoSessionKind
from src.session.viewer_token import (
    InMemorySingleUseTokenGuard,
    RedisSingleUseTokenGuard,
    SingleUseTokenGuard,
    mint_token,
)
from src.viewer.broadcast_hub import SessionBroadcastHub
from src.viewer.drop_tracker import ViewerDropTracker
from src.viewer.viewer_server import ViewerServer

logger = get_logger("jt1078_relay.relay")

# `input_audio_codec` (`mdvrdocs/MDVR-808-1078-spec.pdf` Table 6.21) values this relay knows how
# to get audible in a browser. Deliberately small and explicit: any codec not listed here gets
# zero audio tags for its session (`_on_reassembled_frame` below), never a guessed transcode. `6`
# (G.711A) is the only codec this relay has real evidence for - the bench MDVR's own confirmed
# live `0x1003` report (ADR-0033).
#
# ADR-0034 (2026-08-28): real-browser evidence (Chrome DevTools console, live against the
# physical bench unit) showed `MediaSource.addSourceBuffer('audio/mp4;codecs=ipcm')` throws
# `NotSupportedError` - Chrome's MSE does not accept raw Linear-PCM-in-MP4 via `mpegts.js`'s own
# remux path, and that failure was fatal to the *whole* player (video's own already-accepted
# H.264 SourceBuffer included), not just the audio track. AAC-LC is the one audio codec that
# path reliably accepts, so G.711A is now transcoded to AAC via a per-session `ffmpeg` subprocess
# (`codec/aac_transcoder.AacTranscoder`) rather than expanded to Linear PCM in Python
# (`codec/g711a.py` - kept, correct and tested, for any future non-ffmpeg need, just not called
# from this live path anymore).
_TRANSCODABLE_AUDIO_CODECS: frozenset[int] = frozenset({6})

# Bug 1 fix — app-specific WebSocket close codes (RFC 6455 §7.4.2: 4000-4999 reserved for private
# use), distinct from the pre-existing `4001 invalid_token`/`4004 session_not_active` rejection
# codes above: these signal a connection that *was* legitimately attached to a broadcasting
# session, closed because that session's own backend lifecycle just reached a terminal state, not
# because the connection itself was ever invalid. Kept as two separate codes (not one generic
# "session_terminal") specifically so `useIntercomController.ts` can render "the call failed" and
# "the call ended" as genuinely different outcomes, matching `VideoSessionFailed`/`VideoSessionEnded`
# — the same distinction those two events already carry on the backend/broker side.
_CLOSE_CODE_SESSION_FAILED = 4010
_CLOSE_CODE_SESSION_ENDED = 4011
#: This one viewer stopped consuming and was closed; the session itself is untouched and any
#: other viewer keeps watching (2026-09-22). Distinct from the two session-terminal codes above
#: so a browser (and a log reader) can tell "you fell behind" from "the session ended".
_CLOSE_CODE_VIEWER_STUCK = 4012

# AAC-LC's frame size is fixed at 1024 samples; at the fixed 8kHz this transcoder always encodes
# at (`codec/aac_transcoder.py`'s own `_SOURCE_SAMPLE_RATE_HZ`), that's exactly 128ms/frame -
# used to derive each emitted AAC frame's own FLV tag timestamp (see `_AudioTranscodeSession`
# below), deliberately not ffmpeg's own output-arrival wall-clock time (internal buffering/flush
# jitter would otherwise make tag timestamps non-monotonic or bursty).
_AAC_FRAME_DURATION_MS = 1024 * 1000 // 8000


class _AudioTranscodeSession:
    """Per-session AAC transcoding state: the live `AacTranscoder` process plus enough to derive
    each emitted AAC frame's own FLV tag timestamp. ffmpeg buffers internally and does not
    preserve a 1:1 relationship between a fed G.711A frame's own `frame.timestamp_ms` and any
    particular emitted AAC frame (`aac_transcoder.py`'s own docstring) - so output timestamps are
    derived instead from a fixed per-frame duration counted forward from the first real audio
    frame's timestamp, which stays monotonic regardless of ffmpeg's own I/O timing."""

    def __init__(self, transcoder: AacTranscoder) -> None:
        self.transcoder = transcoder
        self._next_frame_index = 0
        self._anchor_timestamp_ms: int | None = None

    def note_input_frame(self, timestamp_ms: int | None) -> None:
        if self._anchor_timestamp_ms is None:
            self._anchor_timestamp_ms = timestamp_ms or 0

    def next_output_timestamp_ms(self) -> int:
        anchor = self._anchor_timestamp_ms or 0
        timestamp_ms = anchor + self._next_frame_index * _AAC_FRAME_DURATION_MS
        self._next_frame_index += 1
        return timestamp_ms


class Jt1078Relay:
    def __init__(
        self,
        *,
        config: RelayConfig | None = None,
        broker_config: BrokerConfig | None = None,
        redis_client: Redis | None = None,
    ) -> None:
        self._config = config or RelayConfig.from_env()
        self._broker_config = broker_config or BrokerConfig.from_env()
        self._redis_client = redis_client or self._build_redis_client()

        #: session id -> its stream's hub (the viewer server admits by session token).
        self._hubs: dict[str, SessionBroadcastHub] = {}
        #: device stream id -> hub (ADR-0046: one hub per stream, shared by its sessions).
        self._stream_hubs: dict[str, SessionBroadcastHub] = {}
        self._drop_tracker = ViewerDropTracker()
        self._audio_transcode_sessions: dict[str, _AudioTranscodeSession] = {}
        # Holds references to fire-and-forget transcoder start/stop tasks spawned from the
        # synchronous `_on_session_created`/`_on_session_removed` callbacks (`SessionManager`'s
        # own `OnSessionCreated`/`OnSessionRemoved` types are sync) - without this, asyncio may
        # garbage-collect a task before it completes (see the stdlib docs' own warning on
        # `asyncio.create_task`).
        self._background_tasks: set[asyncio.Task] = set()
        self._event_publisher: SessionEventPublisher = self._build_event_publisher()
        self._token_guard: SingleUseTokenGuard = self._build_token_guard()

        self._session_manager = SessionManager(
            event_publisher=self._event_publisher,
            viewer_grace_seconds=self._config.viewer_grace_seconds,
            absolute_idle_seconds=self._config.absolute_idle_seconds,
            ingest_timeout_seconds=self._config.ingest_timeout_seconds,
            max_global_sessions=self._config.max_global_sessions,
            max_sessions_per_organization=self._config.max_sessions_per_organization,
            stream_linger_seconds=self._config.stream_linger_seconds,
            start_serialization_window_seconds=self._config.start_serialization_window_seconds,
            ingest_target=(self._config.effective_public_ingest_host, self._config.ingest_port),
            on_session_created=self._on_session_created,
            on_session_removed=self._on_session_removed,
            on_stream_created=self._on_stream_created,
            on_stream_removed=self._on_stream_removed,
            on_stream_restarting=self._on_stream_restarting,
        )
        #: ADR-0036 — shared between `IngestServer` (registers a device's own live ingest socket
        #: the moment it's correlated) and `ViewerServer` (forwards a browser's uplink audio to
        #: it). One instance, this composition root's own object, mirroring `self._hubs`'s
        #: identical "shared between the two transport servers" shape.
        self._uplink_registry = IngestConnectionRegistry()
        self._ingest_server = IngestServer(
            host=self._config.ingest_host,
            port=self._config.ingest_port,
            session_manager=self._session_manager,
            on_reassembled_frame=self._on_reassembled_frame,
            uplink_registry=self._uplink_registry,
        )
        self._viewer_server = ViewerServer(
            host=self._config.viewer_host,
            port=self._config.viewer_port,
            secret=self._config.viewer_token_secret,
            token_guard=self._token_guard,
            session_manager=self._session_manager,
            hubs=self._hubs,
            uplink_registry=self._uplink_registry,
        )
        self._session_request_server: SessionRequestServer | None = None
        if self._redis_client is not None:
            self._session_request_server = SessionRequestServer(
                self._redis_client,
                session_manager=self._session_manager,
                viewer_token_secret=self._config.viewer_token_secret,
                public_ingest_host=self._config.effective_public_ingest_host,
                ingest_port=self._config.ingest_port,
            )
        self._session_request_task: asyncio.Task | None = None
        self._idle_sweep_task: asyncio.Task | None = None

    def _build_redis_client(self) -> Redis | None:
        if not self._broker_config.url:
            return None
        return Redis.from_url(self._broker_config.url, decode_responses=True)

    def _build_event_publisher(self) -> SessionEventPublisher:
        if self._redis_client is not None:
            return RedisSessionEventPublisher(
                self._redis_client, max_length=self._broker_config.stream_max_length
            )
        return LoggingSessionEventPublisher()

    def _build_token_guard(self) -> SingleUseTokenGuard:
        if self._redis_client is not None:
            return RedisSingleUseTokenGuard(self._redis_client)
        return InMemorySingleUseTokenGuard()

    def _on_stream_created(self, stream: DeviceStream) -> None:
        """ADR-0046: one hub (and, when the terminal's audio is transcodable, one AAC transcoder)
        per device stream, shared by every session watching it."""
        has_audio = stream.audio_codec in _TRANSCODABLE_AUDIO_CODECS
        stuck_timeout = self._config.viewer_stuck_timeout_seconds
        is_intercom = stream.kind == VideoSessionKind.INTERCOM
        self._stream_hubs[stream.stream_id] = SessionBroadcastHub(
            stream.stream_id,
            has_audio=has_audio,
            expects_video=not is_intercom,
            # Intercom opts out: its downlink queue holds seconds of audio, and a browser not
            # playing it must never lose the operator's talk path.
            stuck_timeout_seconds=(None if is_intercom or stuck_timeout <= 0 else stuck_timeout),
        )
        if has_audio:
            self._spawn_background(self._start_audio_transcoder(stream.stream_id))

    def _on_session_created(self, session: VideoSession) -> None:
        """Maps the session's viewer token to its stream's shared hub."""
        hub = self._stream_hubs.get(session.stream_id or "")
        if hub is not None:
            self._hubs[session.session_id] = hub

    def _on_session_removed(self, session_id: str, outcome: str, reason: str) -> None:
        """Closes only this session's viewers (and intercom uplink), with a close code that says
        why; the device stream and its other sessions are unaffected (ADR-0046). Whether the
        device is told to stop is the stream's decision, not the session's."""
        code = _CLOSE_CODE_SESSION_FAILED if outcome == "failed" else _CLOSE_CODE_SESSION_ENDED
        reason_bytes = reason.encode("utf-8")[:123]
        log_with_fields(
            logger, 20, "session_removed", session_id=session_id, outcome=outcome, reason=reason
        )
        hub = self._hubs.pop(session_id, None)
        self._spawn_background(
            self._viewer_server.close_session(
                session_id, hub=hub, code=code, reason=reason_bytes
            )
        )

    def _on_stream_restarting(self, stream: DeviceStream) -> None:
        """Stream-type change: the old generation's connections close, viewers stay attached and
        resynchronise on the new generation's first keyframe."""
        closed = self._ingest_server.close_stream_connections(stream.stream_id)
        hub = self._stream_hubs.get(stream.stream_id)
        if hub is not None:
            hub.begin_new_generation()
        log_with_fields(
            logger,
            20,
            "stream_restart_connections_closed",
            stream_id=stream.stream_id,
            generation=stream.generation,
            device_connections_closed=closed,
        )

    def _on_stream_removed(self, stream_id: str, reason: str) -> None:
        device_connections_closed = self._ingest_server.close_stream_connections(stream_id)
        log_with_fields(
            logger,
            20,
            "stream_removed",
            stream_id=stream_id,
            reason=reason,
            viewer_chunks_dropped=self._drop_tracker.pop_total(stream_id),
            device_connections_closed=device_connections_closed,
        )
        hub = self._stream_hubs.pop(stream_id, None)
        if hub is not None and hub.viewer_count:
            code = _CLOSE_CODE_SESSION_ENDED
            self._spawn_background(hub.close_all(code=code, reason=reason.encode("utf-8")[:123]))
        audio_state = self._audio_transcode_sessions.pop(stream_id, None)
        if audio_state is not None:
            self._spawn_background(audio_state.transcoder.stop())

    async def _close_stuck_viewers(self, stream_id: str, hub: SessionBroadcastHub) -> None:
        """Closes viewers the hub flagged as delivering nothing for
        `viewer_stuck_timeout_seconds` while data waited (2026-09-22; ADR-0046 §5 redefines
        "stuck" so a slow-but-draining viewer is resynchronised instead). Closing the viewer ends
        its session after `viewer_grace_seconds`; the stream stops only if no other session is
        watching it."""
        for connection in hub.take_stuck_viewers():
            log_with_fields(
                logger,
                30,
                "viewer_closed_stuck",
                session_id=stream_id,
                stuck_timeout_seconds=self._config.viewer_stuck_timeout_seconds,
                **(hub.viewer_stats(connection) or {}),
            )
            await self._viewer_server.close_viewer(
                connection, code=_CLOSE_CODE_VIEWER_STUCK, reason=b"viewer_stuck"
            )

    def _spawn_background(self, coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _start_audio_transcoder(self, stream_id: str) -> None:
        async def _on_aac_frame(aac_payload: bytes) -> None:
            await self._on_transcoded_aac_frame(stream_id, aac_payload)

        transcoder = AacTranscoder(on_aac_frame=_on_aac_frame)
        try:
            await transcoder.start()
        except Exception as exc:  # noqa: BLE001 - a missing/broken ffmpeg must be logged, never
            # crash the relay or the stream's video
            log_with_fields(
                logger, 40, "audio_transcoder_start_failed", session_id=stream_id, error=str(exc)
            )
            return
        if stream_id not in self._stream_hubs:
            await transcoder.stop()
            return
        self._audio_transcode_sessions[stream_id] = _AudioTranscodeSession(transcoder)

    async def _on_transcoded_aac_frame(self, stream_id: str, aac_payload: bytes) -> None:
        hub = self._stream_hubs.get(stream_id)
        audio_state = self._audio_transcode_sessions.get(stream_id)
        if hub is None or audio_state is None:
            return
        backpressured = await hub.broadcast_audio_aac(
            aac_payload=aac_payload,
            audio_specific_config=AAC_LC_8KHZ_MONO_AUDIO_SPECIFIC_CONFIG,
            timestamp_ms=audio_state.next_output_timestamp_ms(),
        )
        self._drop_tracker.record(stream_id, dropped=len(backpressured), kind="audio")
        await self._close_stuck_viewers(stream_id, hub)

    async def _on_reassembled_frame(self, stream_id: str, frame: ReassembledFrame) -> None:
        hub = self._stream_hubs.get(stream_id)
        if hub is None:
            return
        if frame.is_video:
            # JT/T 1078 Table 6.3 data type 0000 = I frame: the keyframe signal the hub's
            # keyframe-aware delivery keys on (ADR-0046 §5).
            is_keyframe = frame.data_type == 0
            if is_keyframe:
                log_with_fields(
                    logger, 20, "keyframe_received", session_id=stream_id,
                    last_i_frame_interval_ms=frame.last_i_frame_interval_ms,
                    timestamp_ms=frame.timestamp_ms,
                )
            backpressured = await hub.broadcast_video(
                annex_b_payload=frame.body,
                is_keyframe=is_keyframe,
                timestamp_ms=frame.timestamp_ms,
            )
            self._drop_tracker.record(stream_id, dropped=len(backpressured), kind="video")
            await self._close_stuck_viewers(stream_id, hub)
        elif frame.is_audio:
            stream = self._session_manager.resolve_stream(stream_id)
            audio_codec = stream.audio_codec if stream is not None else None
            if audio_codec not in _TRANSCODABLE_AUDIO_CODECS:
                return  # no transcoder for this device's real (or unknown) codec - no audio tag
            audio_state = self._audio_transcode_sessions.get(stream_id)
            if audio_state is None:
                return
            audio_state.note_input_frame(frame.timestamp_ms)
            await audio_state.transcoder.feed(frame.body)

    def create_live_session(
        self,
        *,
        terminal_id: str,
        correlation_id: str,
        logical_channel: int,
        device_id: str | None = None,
        vehicle_id: str | None = None,
        organization_id: str | None = None,
    ) -> tuple[VideoSession, str]:
        """Creates a `REQUESTED` session + hub and mints its one signed viewer token. Returns
        `(session, viewer_token)` — the caller (a future Business API adapter, or a test/admin
        script) still owns signaling the device via `device-gateway`'s own
        `RedisVideoSignalingConsumer` (`0x9101`, carrying *this relay's* own `ingest_host`/
        `ingest_port` as the target) - this method does not do that itself, since it has no
        broker-publishing responsibility of its own for *starting* a session (only for stopping
        one, ADR-0024 §5 point 4)."""
        session = self._session_manager.create_session(
            terminal_id=terminal_id,
            kind=VideoSessionKind.LIVE,
            correlation_id=correlation_id,
            logical_channel=logical_channel,
            device_id=device_id,
            vehicle_id=vehicle_id,
            organization_id=organization_id,
        )
        token = mint_token(session_id=session.session_id, secret=self._config.viewer_token_secret)
        return session, token

    def create_playback_session(
        self,
        *,
        terminal_id: str,
        correlation_id: str,
        logical_channel: int,
        device_id: str | None = None,
        vehicle_id: str | None = None,
        organization_id: str | None = None,
    ) -> tuple[VideoSession, str]:
        session = self._session_manager.create_session(
            terminal_id=terminal_id,
            kind=VideoSessionKind.PLAYBACK,
            correlation_id=correlation_id,
            logical_channel=logical_channel,
            device_id=device_id,
            vehicle_id=vehicle_id,
            organization_id=organization_id,
        )
        token = mint_token(session_id=session.session_id, secret=self._config.viewer_token_secret)
        return session, token

    @property
    def session_manager(self) -> SessionManager:
        return self._session_manager

    @property
    def ingest_server(self) -> IngestServer:
        return self._ingest_server

    @property
    def viewer_server(self) -> ViewerServer:
        return self._viewer_server

    @property
    def session_request_server(self) -> SessionRequestServer | None:
        """`None` unless a broker is configured — see class docstring."""
        return self._session_request_server

    async def _idle_sweep_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._config.idle_sweep_interval_seconds)
                await self._session_manager.sweep_idle_sessions()
        except asyncio.CancelledError:
            raise

    async def start(self) -> None:
        await self._ingest_server.start()
        await self._viewer_server.start()
        self._idle_sweep_task = asyncio.create_task(self._idle_sweep_loop())
        if self._session_request_server is not None:
            self._session_request_task = asyncio.create_task(
                self._session_request_server.run_forever()
            )
        log_with_fields(
            logger,
            20,
            "relay_started",
            ingest_port=self._ingest_server.bound_port,
            viewer_port=self._viewer_server.bound_port,
            session_request_server_active=self._session_request_server is not None,
        )

    async def stop(self) -> None:
        if self._session_request_task is not None:
            self._session_request_task.cancel()
            try:
                await self._session_request_task
            except asyncio.CancelledError:
                pass
            self._session_request_task = None
        if self._idle_sweep_task is not None:
            self._idle_sweep_task.cancel()
            try:
                await self._idle_sweep_task
            except asyncio.CancelledError:
                pass
            self._idle_sweep_task = None
        for audio_state in list(self._audio_transcode_sessions.values()):
            await audio_state.transcoder.stop()
        self._audio_transcode_sessions.clear()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        await self._ingest_server.stop()
        await self._viewer_server.stop()
        log_with_fields(logger, 20, "relay_stopped")

    async def serve_forever(self) -> None:
        await self.start()
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _handle_signal() -> None:
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except NotImplementedError:
                pass  # Windows: add_signal_handler isn't supported for these signals

        await stop_event.wait()
        await self.stop()


async def main() -> None:
    configure_logging(level=logging.INFO)
    config = RelayConfig.from_env()
    config.validate_on_startup()
    relay = Jt1078Relay(config=config)
    await relay.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
