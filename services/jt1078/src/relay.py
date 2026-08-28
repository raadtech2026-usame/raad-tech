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
from typing import Callable

from redis.asyncio import Redis

from src.broker_config import BrokerConfig
from src.codec.g711a import decode_g711a, resample_linear_pcm16
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

# `input_audio_codec` (`mdvrdocs/MDVR-808-1078-spec.pdf` Table 6.21) -> a
# `(payload: bytes) -> (pcm16le_bytes, sample_rate_hz)` decoder. Deliberately small and explicit:
# any codec not listed here gets zero audio tags for its session (`_on_reassembled_frame` below),
# never a guessed decode. `6` (G.711A) is the only codec this relay has real evidence for - the
# bench MDVR's own confirmed live `0x1003` report (ADR-0033).
_G711A_TARGET_SAMPLE_RATE_HZ = 11025  # nearest of FLV's 4 legacy SoundRate values to 8000Hz


def _decode_g711a_to_pcm(payload: bytes) -> tuple[bytes, int]:
    # G.711 is an ITU-T-standardized 8kHz codec (not a value this relay is guessing or assuming
    # per-device - it's what "G.711" *is*); Table 6.1's own generic `input_audio_sample_rate`
    # field is not threaded through this relay today, since G.711A's rate is fixed by definition.
    pcm = decode_g711a(payload)
    resampled = resample_linear_pcm16(pcm, from_hz=8000, to_hz=_G711A_TARGET_SAMPLE_RATE_HZ)
    return resampled, _G711A_TARGET_SAMPLE_RATE_HZ


_AUDIO_DECODERS: dict[int, Callable[[bytes], tuple[bytes, int]]] = {
    6: _decode_g711a_to_pcm,  # G.711A
}


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
        # `broadcast_audio` for this session - the FLV header's own claim and actual tag
        # delivery must never disagree (2026-08-28 regression fix).
        has_audio = session.audio_codec in _AUDIO_DECODERS
        self._hubs[session.session_id] = SessionBroadcastHub(
            session.session_id, has_audio=has_audio
        )

    def _on_session_removed(self, session_id: str) -> None:
        self._hubs.pop(session_id, None)

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
            decoder = _AUDIO_DECODERS.get(audio_codec) if audio_codec is not None else None
            if decoder is None:
                return  # no decoder for this device's real (or unknown) codec - no audio tag
            pcm_payload, sample_rate_hz = decoder(frame.body)
            await hub.broadcast_audio(
                pcm_payload=pcm_payload,
                sample_rate_hz=sample_rate_hz,
                timestamp_ms=frame.timestamp_ms,
            )

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
