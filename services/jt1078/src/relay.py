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
from src.session.session_manager import SessionManager
from src.session.session_request_server import SessionRequestServer
from src.session.video_session import VideoSession, VideoSessionKind
from src.session.viewer_token import (
    InMemorySingleUseTokenGuard,
    RedisSingleUseTokenGuard,
    SingleUseTokenGuard,
    mint_token,
)
from src.viewer.broadcast_hub import SessionBroadcastHub
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

        self._hubs: dict[str, SessionBroadcastHub] = {}
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
            on_session_created=self._on_session_created,
            on_session_removed=self._on_session_removed,
        )
        self._ingest_server = IngestServer(
            host=self._config.ingest_host,
            port=self._config.ingest_port,
            session_manager=self._session_manager,
            on_reassembled_frame=self._on_reassembled_frame,
        )
        self._viewer_server = ViewerServer(
            host=self._config.viewer_host,
            port=self._config.viewer_port,
            secret=self._config.viewer_token_secret,
            token_guard=self._token_guard,
            session_manager=self._session_manager,
            hubs=self._hubs,
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
            return RedisSessionEventPublisher(self._redis_client)
        return LoggingSessionEventPublisher()

    def _build_token_guard(self) -> SingleUseTokenGuard:
        if self._redis_client is not None:
            return RedisSingleUseTokenGuard(self._redis_client)
        return InMemorySingleUseTokenGuard()

    def _on_session_created(self, session: VideoSession) -> None:
        # Same source of truth `_on_reassembled_frame` uses to decide whether to ever call
        # `broadcast_audio_aac` for this session - the FLV header's own claim and actual tag
        # delivery must never disagree (2026-08-28 regression fix).
        has_audio = session.audio_codec in _TRANSCODABLE_AUDIO_CODECS
        self._hubs[session.session_id] = SessionBroadcastHub(
            session.session_id, has_audio=has_audio
        )
        if has_audio:
            self._spawn_background(self._start_audio_transcoder(session.session_id))

    def _on_session_removed(self, session_id: str) -> None:
        self._hubs.pop(session_id, None)
        audio_state = self._audio_transcode_sessions.pop(session_id, None)
        if audio_state is not None:
            self._spawn_background(audio_state.transcoder.stop())

    def _spawn_background(self, coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _start_audio_transcoder(self, session_id: str) -> None:
        async def _on_aac_frame(aac_payload: bytes) -> None:
            await self._on_transcoded_aac_frame(session_id, aac_payload)

        transcoder = AacTranscoder(on_aac_frame=_on_aac_frame)
        try:
            await transcoder.start()
        except Exception as exc:  # noqa: BLE001 - a missing/broken ffmpeg must be logged, never
            # silently vanish (the same "don't let a background task's exception disappear
            # unlogged" lesson this codebase already applies to every `run_forever` consumer
            # loop) - the session simply stays video-only, exactly like an unrecognized codec.
            log_with_fields(
                logger, 40, "audio_transcoder_start_failed", session_id=session_id, error=str(exc)
            )
            return
        if session_id not in self._hubs:
            # The session was torn down while ffmpeg was still spawning - don't leak the
            # process; `_on_session_removed` already ran and found nothing to stop.
            await transcoder.stop()
            return
        self._audio_transcode_sessions[session_id] = _AudioTranscodeSession(transcoder)

    async def _on_transcoded_aac_frame(self, session_id: str, aac_payload: bytes) -> None:
        hub = self._hubs.get(session_id)
        audio_state = self._audio_transcode_sessions.get(session_id)
        if hub is None or audio_state is None:
            return
        await hub.broadcast_audio_aac(
            aac_payload=aac_payload,
            audio_specific_config=AAC_LC_8KHZ_MONO_AUDIO_SPECIFIC_CONFIG,
            timestamp_ms=audio_state.next_output_timestamp_ms(),
        )

    async def _on_reassembled_frame(self, session_id: str, frame: ReassembledFrame) -> None:
        hub = self._hubs.get(session_id)
        if hub is None:
            return
        if frame.is_video:
            await hub.broadcast_video(
                annex_b_payload=frame.body,
                is_keyframe=(frame.data_type == 0),  # DATA_TYPE_I_FRAME
                timestamp_ms=frame.timestamp_ms,
            )
        elif frame.is_audio:
            session = self._session_manager.resolve(session_id)
            audio_codec = session.audio_codec if session is not None else None
            if audio_codec not in _TRANSCODABLE_AUDIO_CODECS:
                return  # no transcoder for this device's real (or unknown) codec - no audio tag
            audio_state = self._audio_transcode_sessions.get(session_id)
            if audio_state is None:
                # ffmpeg is still spawning (`_start_audio_transcoder` hasn't finished) - this
                # frame is dropped, not queued; audio resumes once the transcoder is ready,
                # video for this same frame is unaffected either way.
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
    relay = Jt1078Relay()
    await relay.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
