"""`SessionManager` — the relay's Video Session Manager (ADR-0024 §5), reworked around device
stream ownership (ADR-0046).

Two levels, deliberately separate:

- a **session** is one Business API `VideoSession`: one viewer token, one audit trail, one
  requested stream type. Ending it (explicit stop, viewer idle) only detaches it;
- a **device stream** (`device_stream.DeviceStream`) is what the terminal is actually transmitting.
  It is the only thing that ever sends `0x9101`/`0x9102`/`0x9201`/`0x9202`, it is shared by every
  session watching the same `(terminal, channel, kind)`, and it stops only when its last session
  has been gone for `stream_linger_seconds`, or when the device stops delivering.

**Why (production, 2026-09-18 → 09-25).** One session per viewer used to own the channel. The
second viewer of a channel never got its own connection, failed on `ingest_timeout`, and its
`0x9102` - which names only the channel - closed the stream under the first viewer. And because the
Business API sent starts while this relay sent stops, a focus change delivered the old stop *after*
the new start. See ADR-0046's Context for the evidence.

**Ordering.** Every device command and every lifecycle event goes through one FIFO outbox drained by
one task (`flush`). A stop is queued at the moment the relay decides it, so it always precedes any
later start on the broker stream, which `device-gateway` forwards in order on the terminal's single
JT/T 808 connection. Each start increments the stream's `generation`; a stop always names the
generation it ends.

**Start slot per channel.** While one stream of a `(terminal, channel)` is waiting for its media
connection, another stream's start on that channel is held (up to
`start_serialization_window_seconds`). The media connection itself carries only SIM, channel and a
frame type, so this is what makes the next unattributed connection belong to exactly one stream.

**Identity.** An ingest frame carries a `BCD[6]` SIM card number while `terminal_id` is the
`BCD[10]` JT/T 808-2019 terminal phone; they are matched by suffix, not equality (a live-found bug,
2026-08-19, `_terminal_id_matches_sim_card_number`).

**Live video and intercom on one channel (ADR-0046 §4).** `0x9102` control 0 with close type 0
closes *all* audio and video of the channel, intercom included (supplier spec Table 6.4; closed a
running intercom in production on 2026-09-25 18:11:56). While an intercom stream is open on the
channel, a live stop uses close type 2 ("video only, keep audio").
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from src.events.publisher_port import SessionEventPublisher
from src.events.session_events import VideoSessionActivated, VideoSessionEnded, VideoSessionFailed
from src.logging_setup import get_logger, log_with_fields
from src.session.device_stream import (
    DeviceStream,
    DeviceStreamState,
    StreamKey,
    new_stream_id,
)
from src.session.video_session import (
    StreamType,
    VideoSession,
    VideoSessionKind,
    VideoSessionState,
    new_session_id,
)

logger = get_logger("jt1078_relay.session.manager")

DEFAULT_VIEWER_GRACE_SECONDS = 15.0
DEFAULT_ABSOLUTE_IDLE_SECONDS = 60.0
DEFAULT_INGEST_TIMEOUT_SECONDS = 30.0
#: ADR-0026 §8, citing Phase 2 §13.1's "e.g., start 50 global". No per-org number is documented,
#: so that ceiling defaults to unconfigured.
DEFAULT_MAX_GLOBAL_SESSIONS = 50
#: `0` keeps the pre-ADR-0046 behaviour (stop the moment the last session leaves); the relay's own
#: configuration uses 5 s so a focus swap or a reconnect reuses the running stream.
DEFAULT_STREAM_LINGER_SECONDS = 0.0
DEFAULT_START_SERIALIZATION_WINDOW_SECONDS = 10.0

#: `0x9102` control values, supplier spec Table 6.4.
_CONTROL_CLOSE_AV = 0
_CONTROL_CLOSE_INTERCOM = 4
#: `0x9102` close types, Table 6.4.
_CLOSE_ALL = 0
_CLOSE_VIDEO_ONLY = 2
#: `0x9202` control 2 = end playback, Table 6.11.
_PLAYBACK_CONTROL_STOP = 2
#: `0x9101` data types, Table 6.2.
_DATA_TYPE_AV = 0
_DATA_TYPE_INTERCOM = 2

OnSessionCreated = Callable[[VideoSession], None]
#: `(session_id, outcome, reason)`; outcome is `"ended"` or `"failed"`.
OnSessionRemoved = Callable[[str, str, str], None]
OnStreamCreated = Callable[[DeviceStream], None]
#: `(stream_id, reason)`.
OnStreamRemoved = Callable[[str, str], None]
#: A running stream is being restarted (stream-type change): its connections must close and its
#: viewers resynchronise on the next generation's first keyframe.
OnStreamRestarting = Callable[[DeviceStream], None]


class SessionCapacityExceededError(Exception):
    """Raised by `create_session` when a ceiling is exceeded (ADR-0026 §8)."""


def _noop(*_: object) -> None:
    return None


def _terminal_id_matches_sim_card_number(terminal_id: str, sim_card_number: str) -> bool:
    """`BCD[6]` SIM card number vs `BCD[10]` terminal phone: the same number, right-justified and
    zero-padded to the wider field (confirmed live, 2026-08-19)."""
    return (
        len(terminal_id) >= len(sim_card_number)
        and terminal_id[-len(sim_card_number) :] == sim_card_number
    )


class SessionManager:
    def __init__(
        self,
        *,
        event_publisher: SessionEventPublisher,
        viewer_grace_seconds: float = DEFAULT_VIEWER_GRACE_SECONDS,
        absolute_idle_seconds: float = DEFAULT_ABSOLUTE_IDLE_SECONDS,
        ingest_timeout_seconds: float = DEFAULT_INGEST_TIMEOUT_SECONDS,
        max_global_sessions: int | None = DEFAULT_MAX_GLOBAL_SESSIONS,
        max_sessions_per_organization: int | None = None,
        stream_linger_seconds: float = DEFAULT_STREAM_LINGER_SECONDS,
        start_serialization_window_seconds: float = DEFAULT_START_SERIALIZATION_WINDOW_SECONDS,
        ingest_target: tuple[str, int] | None = None,
        on_session_created: OnSessionCreated | None = None,
        on_session_removed: OnSessionRemoved | None = None,
        on_stream_created: OnStreamCreated | None = None,
        on_stream_removed: OnStreamRemoved | None = None,
        on_stream_restarting: OnStreamRestarting | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`max_global_sessions`/`max_sessions_per_organization`: `None` or `<= 0` means no
        ceiling. `ingest_target` is the `(public host, port)` a start command tells the terminal
        to dial; without it the relay cannot start streams itself."""
        self._event_publisher = event_publisher
        self._viewer_grace_seconds = viewer_grace_seconds
        self._absolute_idle_seconds = absolute_idle_seconds
        self._ingest_timeout_seconds = ingest_timeout_seconds
        self._max_global_sessions = max_global_sessions
        self._max_sessions_per_organization = max_sessions_per_organization
        self._stream_linger_seconds = stream_linger_seconds
        self._start_window_seconds = start_serialization_window_seconds
        self._ingest_target = ingest_target
        self._on_session_created = on_session_created or _noop
        self._on_session_removed = on_session_removed or _noop
        self._on_stream_created = on_stream_created or _noop
        self._on_stream_removed = on_stream_removed or _noop
        self._on_stream_restarting = on_stream_restarting or _noop
        self._clock = clock
        self._sessions: dict[str, VideoSession] = {}
        self._streams: dict[str, DeviceStream] = {}
        self._stream_by_key: dict[StreamKey, str] = {}
        self._outbox: list[Callable[[], Awaitable[None]]] = []
        self._flush_lock = asyncio.Lock()
        self._flush_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ sessions

    def create_session(
        self,
        *,
        terminal_id: str,
        kind: VideoSessionKind,
        correlation_id: str,
        logical_channel: int,
        device_id: str | None = None,
        vehicle_id: str | None = None,
        organization_id: str | None = None,
        session_id: str | None = None,
        audio_codec: int | None = None,
        stream_type: StreamType = StreamType.MAIN,
        relay_signals_device: bool = False,
        window_start: str | None = None,
        window_end: str | None = None,
    ) -> VideoSession:
        """Creates a session and attaches it to its device stream, creating and starting the
        stream if none is running. Raises `SessionCapacityExceededError` before allocating
        anything if a ceiling is reached, or if the terminal already has an open intercom
        (talking to a bus is exclusive, ADR-0036)."""
        if (
            self._max_global_sessions is not None
            and self._max_global_sessions > 0
            and self.active_session_count >= self._max_global_sessions
        ):
            raise SessionCapacityExceededError(
                f"Global concurrent-session ceiling reached ({self._max_global_sessions})."
            )
        if (
            organization_id is not None
            and self._max_sessions_per_organization is not None
            and self._max_sessions_per_organization > 0
            and self._count_for_organization(organization_id)
            >= self._max_sessions_per_organization
        ):
            raise SessionCapacityExceededError(
                f"Organization {organization_id!r} concurrent-session ceiling reached "
                f"({self._max_sessions_per_organization})."
            )
        if kind == VideoSessionKind.INTERCOM and any(
            existing.terminal_id == terminal_id and existing.kind == VideoSessionKind.INTERCOM
            for existing in self._sessions.values()
        ):
            raise SessionCapacityExceededError(
                f"Terminal {terminal_id!r} already has an open intercom session."
            )

        session = VideoSession(
            session_id=session_id or new_session_id(),
            terminal_id=terminal_id,
            kind=kind,
            device_id=device_id,
            vehicle_id=vehicle_id,
            organization_id=organization_id,
            correlation_id=correlation_id,
            logical_channel=logical_channel,
            audio_codec=audio_codec,
            # Only live video has two encoder streams; intercom and playback always use main.
            stream_type=stream_type if kind == VideoSessionKind.LIVE else StreamType.MAIN,
        )
        stream = self._stream_for_new_session(
            session,
            relay_signals_device=relay_signals_device,
            window_start=window_start,
            window_end=window_end,
        )
        session.stream_id = stream.stream_id
        stream.session_ids.add(session.session_id)
        self._sessions[session.session_id] = session
        self._on_session_created(session)
        if stream.state == DeviceStreamState.ACTIVE:
            # Joining a stream that is already delivering: this session has media right away.
            self._activate_session(session)
        self._reconcile(stream)
        self._schedule_flush()
        log_with_fields(
            logger,
            20,
            "session_attached",
            session_id=session.session_id,
            stream_id=stream.stream_id,
            kind=kind.value,
            logical_channel=logical_channel,
            requested_stream_type=session.stream_type.value,
            stream_sessions=len(stream.session_ids),
        )
        return session

    def _stream_for_new_session(
        self,
        session: VideoSession,
        *,
        relay_signals_device: bool,
        window_start: str | None,
        window_end: str | None,
    ) -> DeviceStream:
        key = StreamKey(
            terminal_id=session.terminal_id,
            logical_channel=session.logical_channel,
            kind=session.kind,
            exclusive_to=session.session_id if session.kind == VideoSessionKind.PLAYBACK else None,
        )
        existing_id = self._stream_by_key.get(key)
        if existing_id is not None:
            return self._streams[existing_id]
        stream = DeviceStream(
            stream_id=new_stream_id(),
            key=key,
            stream_type=session.stream_type,
            relay_signals_device=relay_signals_device,
            device_id=session.device_id,
            vehicle_id=session.vehicle_id,
            organization_id=session.organization_id,
            audio_codec=session.audio_codec,
            window_start=window_start,
            window_end=window_end,
            created_at=self._clock(),
        )
        if not relay_signals_device:
            # The caller signals the device itself: from the relay's point of view the stream is
            # started the moment it exists (generation 1), exactly as before ADR-0046.
            stream.generation = 1
            stream.start_requested_at = self._clock()
        self._streams[stream.stream_id] = stream
        self._stream_by_key[key] = stream.stream_id
        self._on_stream_created(stream)
        return stream

    def _count_for_organization(self, organization_id: str) -> int:
        return sum(1 for s in self._sessions.values() if s.organization_id == organization_id)

    def resolve(self, session_id: str) -> VideoSession | None:
        return self._sessions.get(session_id)

    def resolve_stream(self, stream_id: str) -> DeviceStream | None:
        return self._streams.get(stream_id)

    def stream_for_session(self, session_id: str) -> DeviceStream | None:
        session = self._sessions.get(session_id)
        if session is None or session.stream_id is None:
            return None
        return self._streams.get(session.stream_id)

    def sessions_of_stream(self, stream_id: str) -> list[VideoSession]:
        stream = self._streams.get(stream_id)
        if stream is None:
            return []
        return [self._sessions[s] for s in stream.session_ids if s in self._sessions]

    def add_viewer(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.add_viewer()

    def remove_viewer(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.remove_viewer()

    async def end_session(self, session_id: str, *, reason: str) -> None:
        """Ends one session (explicit stop, viewer idle). Only detaches it from its stream: the
        stream keeps running for its other sessions and stops only once none is left."""
        self._remove_session(session_id, outcome="ended", reason=reason)
        await self.flush()

    async def fail_session(self, session_id: str, *, reason: str) -> None:
        self._remove_session(session_id, outcome="failed", reason=reason)
        await self.flush()

    def _remove_session(
        self, session_id: str, *, outcome: str, reason: str, reconcile: bool = True
    ) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        self._on_session_removed(session_id, outcome, reason)
        event_type = VideoSessionEnded if outcome == "ended" else VideoSessionFailed
        event = event_type(
            session_id=session.session_id,
            terminal_id=session.terminal_id,
            organization_id=session.organization_id,
            vehicle_id=session.vehicle_id,
            device_id=session.device_id,
            correlation_id=session.correlation_id,
            reason=reason,
            event_time=datetime.now(timezone.utc),
        )
        self._enqueue(lambda: self._event_publisher.publish(event))
        stream = self._streams.get(session.stream_id or "")
        if stream is not None:
            stream.session_ids.discard(session_id)
            if reconcile:
                self._reconcile(stream)

    def _activate_session(self, session: VideoSession) -> None:
        if session.state != VideoSessionState.REQUESTED:
            return
        session.activate()
        event = VideoSessionActivated(
            session_id=session.session_id,
            terminal_id=session.terminal_id,
            organization_id=session.organization_id,
            vehicle_id=session.vehicle_id,
            device_id=session.device_id,
            correlation_id=session.correlation_id,
            event_time=datetime.now(timezone.utc),
        )
        self._enqueue(lambda: self._event_publisher.publish(event))

    # ------------------------------------------------------------------ streams

    def _reconcile(self, stream: DeviceStream) -> None:
        """Brings one stream in line with its sessions. Only ever *queues* device commands."""
        if stream.stream_id not in self._streams:
            return
        now = self._clock()
        if not stream.session_ids:
            if stream.released_at is None:
                stream.released_at = now
            if now - stream.released_at >= self._stream_linger_seconds:
                self._stop_stream(stream, reason="stream_released")
            return
        stream.released_at = None
        if not stream.relay_signals_device:
            return
        target = self._target_stream_type(stream)
        if stream.generation == 0:
            stream.stream_type = target
            if not stream.start_pending:
                self._request_start(stream)
            return
        if target == stream.stream_type:
            stream.downgrade_requested_at = None
            return
        if target == StreamType.MAIN:
            self._restart(stream, target)
            return
        # A downgrade waits out the linger so a focus swap (main released, then re-requested a
        # moment later) never restarts the stream twice.
        if stream.downgrade_requested_at is None:
            stream.downgrade_requested_at = now
        if now - stream.downgrade_requested_at >= self._stream_linger_seconds:
            self._restart(stream, target)

    def _target_stream_type(self, stream: DeviceStream) -> StreamType:
        if stream.kind != VideoSessionKind.LIVE:
            return StreamType.MAIN
        wants_main = any(
            self._sessions[s].stream_type == StreamType.MAIN
            for s in stream.session_ids
            if s in self._sessions
        )
        return StreamType.MAIN if wants_main else StreamType.SUB

    def _channel_start_slot_busy(self, stream: DeviceStream) -> bool:
        now = self._clock()
        for other in self._streams.values():
            if other is stream or other.key.channel != stream.key.channel:
                continue
            if (
                other.generation > 0
                and other.awaiting_connection
                and other.start_requested_at is not None
                and now - other.start_requested_at < self._start_window_seconds
            ):
                return True
        return False

    def _request_start(self, stream: DeviceStream) -> None:
        if self._channel_start_slot_busy(stream):
            if not stream.start_pending:
                stream.start_pending = True
                log_with_fields(
                    logger,
                    20,
                    "stream_start_deferred",
                    stream_id=stream.stream_id,
                    kind=stream.kind.value,
                    logical_channel=stream.logical_channel,
                )
            return
        stream.start_pending = False
        self._issue_start(stream)

    def _issue_start(self, stream: DeviceStream) -> None:
        stream.generation += 1
        stream.state = DeviceStreamState.STARTING
        stream.awaiting_connection = True
        stream.start_requested_at = self._clock()
        stream.downgrade_requested_at = None
        command, fields = self._start_command(stream)
        correlation_id = stream.command_correlation_id()
        terminal_id = stream.terminal_id
        log_with_fields(
            logger,
            20,
            "stream_start_requested",
            stream_id=stream.stream_id,
            generation=stream.generation,
            kind=stream.kind.value,
            logical_channel=stream.logical_channel,
            stream_type=stream.stream_type.value,
        )
        self._enqueue_command(terminal_id, correlation_id, command, fields)

    def _start_command(self, stream: DeviceStream) -> tuple[str, dict[str, object]]:
        if self._ingest_target is None:
            raise RuntimeError("The relay cannot start a device stream without an ingest target.")
        host, port = self._ingest_target
        target = {"server_ip": host, "tcp_port": port, "udp_port": 0}
        if stream.kind == VideoSessionKind.PLAYBACK:
            return "playback_request", {
                **target,
                "logical_channel": stream.logical_channel,
                "av_type": 0,  # 0 = A/V, Table 6.10
                "stream_type": 0,
                "storage_type": 0,
                "playback_mode": 0,  # normal playback
                "start_time": stream.window_start,
                "end_time": stream.window_end,
            }
        data_type = _DATA_TYPE_INTERCOM if stream.kind == VideoSessionKind.INTERCOM else _DATA_TYPE_AV
        return "live_video_request", {
            **target,
            "logical_channel": stream.logical_channel,
            "data_type": data_type,
            "stream_type": stream.stream_type.wire_value,
        }

    def _stop_command(self, stream: DeviceStream) -> tuple[str, dict[str, object]]:
        if stream.kind == VideoSessionKind.PLAYBACK:
            return "playback_control", {
                "av_channel": stream.logical_channel,
                "control": _PLAYBACK_CONTROL_STOP,
            }
        if stream.kind == VideoSessionKind.INTERCOM:
            return "live_video_control", {
                "logical_channel": stream.logical_channel,
                "control": _CONTROL_CLOSE_INTERCOM,
            }
        intercom_open = any(
            other.key.channel == stream.key.channel and other.kind == VideoSessionKind.INTERCOM
            for other in self._streams.values()
            if other is not stream
        )
        return "live_video_control", {
            "logical_channel": stream.logical_channel,
            "control": _CONTROL_CLOSE_AV,
            "close_av_type": _CLOSE_VIDEO_ONLY if intercom_open else _CLOSE_ALL,
        }

    def _queue_stop(self, stream: DeviceStream) -> None:
        if stream.generation == 0:
            return  # never started - nothing on the terminal to stop
        command, fields = self._stop_command(stream)
        correlation_id = stream.command_correlation_id(suffix="-stop")
        terminal_id = stream.terminal_id
        self._enqueue_command(terminal_id, correlation_id, command, fields)

    def _restart(self, stream: DeviceStream, target: StreamType) -> None:
        log_with_fields(
            logger,
            20,
            "stream_restarting",
            stream_id=stream.stream_id,
            generation=stream.generation,
            from_stream_type=stream.stream_type.value,
            to_stream_type=target.value,
        )
        self._queue_stop(stream)
        self._on_stream_restarting(stream)
        stream.open_connections = 0
        stream.stream_type = target
        stream.state = DeviceStreamState.STARTING
        stream.awaiting_connection = True
        stream.downgrade_requested_at = None
        # Respects the channel's start slot like any start: another stream of this channel still
        # waiting for its connection (e.g. an intercom just requested) must not become ambiguous.
        self._request_start(stream)

    def _stop_stream(self, stream: DeviceStream, *, reason: str) -> None:
        if self._streams.pop(stream.stream_id, None) is None:
            return
        self._stream_by_key.pop(stream.key, None)
        self._queue_stop(stream)
        self._on_stream_removed(stream.stream_id, reason)
        log_with_fields(
            logger,
            20,
            "stream_stopped",
            stream_id=stream.stream_id,
            generation=stream.generation,
            kind=stream.kind.value,
            logical_channel=stream.logical_channel,
            reason=reason,
        )
        self._release_channel_slot(stream.key.channel)

    def _terminate_stream(self, stream: DeviceStream, *, reason: str) -> None:
        """The device stopped delivering (never connected, stalled, or closed the connection):
        every session on the stream ends with that reason, then the stream stops."""
        for session_id in list(stream.session_ids):
            session = self._sessions.get(session_id)
            if session is None:
                continue
            outcome = "failed" if session.state == VideoSessionState.REQUESTED else "ended"
            self._remove_session(session_id, outcome=outcome, reason=reason, reconcile=False)
        self._stop_stream(stream, reason=reason)

    def _release_channel_slot(self, channel: tuple[str, int]) -> None:
        for other in list(self._streams.values()):
            if other.key.channel == channel and other.start_pending:
                self._request_start(other)
                if other.start_pending:
                    break  # the slot is taken again

    # ------------------------------------------------------------------ ingest

    def resolve_ingest_stream(
        self, sim_card_number: str, logical_channel: int, *, is_audio: bool | None = None
    ) -> DeviceStream | None:
        """The stream a newly connected media socket belongs to. The socket carries only SIM,
        channel and frame type, so: the channel's stream still waiting for its connection first
        (at most one, thanks to the start slot), then the preferred kind - audio prefers
        intercom, video prefers live or playback - then one with no open connection.
        Never "the first session that matches"."""
        candidates = [
            stream
            for stream in self._streams.values()
            if stream.logical_channel == logical_channel
            and stream.generation > 0
            and _terminal_id_matches_sim_card_number(stream.terminal_id, sim_card_number)
        ]
        if not candidates:
            return None

        def rank(stream: DeviceStream) -> tuple[int, int, int, float]:
            preferred = (
                (stream.kind == VideoSessionKind.INTERCOM) == is_audio
                if is_audio is not None
                else True
            )
            return (
                0 if stream.awaiting_connection else 1,
                0 if preferred else 1,
                0 if stream.open_connections == 0 else 1,
                stream.created_at,
            )

        return min(candidates, key=rank)

    # Kept for callers that still use the pre-ADR-0046 name.
    resolve_ingest_by_terminal_id = resolve_ingest_stream

    def note_ingest_connected(self, stream_id: str) -> None:
        stream = self._streams.get(stream_id)
        if stream is None:
            return
        stream.open_connections += 1
        if stream.awaiting_connection:
            stream.awaiting_connection = False
            self._release_channel_slot(stream.key.channel)
            self._schedule_flush()

    async def mark_stream_active(self, stream_id: str) -> None:
        """The current generation's first frame arrived."""
        stream = self._streams.get(stream_id)
        if stream is None:
            return
        stream.last_frame_at = self._clock()
        if stream.state != DeviceStreamState.ACTIVE:
            stream.state = DeviceStreamState.ACTIVE
            for session in self.sessions_of_stream(stream_id):
                self._activate_session(session)
        await self.flush()

    def touch_stream(self, stream_id: str) -> None:
        stream = self._streams.get(stream_id)
        if stream is not None:
            stream.last_frame_at = self._clock()

    async def handle_ingest_disconnected(
        self, stream_id: str, *, generation: int | None = None, remaining_connections: int = 0
    ) -> None:
        """A media connection closed. The device closing the *current* generation's last
        connection means the transmission is over (packet-verified 2026-09-02: after a radio
        outage the MDVR sends FIN on every JT/T 1078 connection rather than resuming). A
        connection of an older generation, or one superseded by a newer connection, closing is
        not news about the stream."""
        stream = self._streams.get(stream_id)
        if stream is None:
            return
        stream.open_connections = remaining_connections
        if generation is not None and generation != stream.generation:
            return
        if remaining_connections > 0:
            return
        self._terminate_stream(stream, reason="ingest_disconnected")
        await self.flush()

    # ------------------------------------------------------------------ sweep

    async def sweep_idle_sessions(self) -> list[str]:
        """Periodic housekeeping. Returns the ids of sessions it ended (test observability).

        - a session whose viewers left `viewer_grace_seconds` ago ends (`viewer_idle_timeout`);
        - a session whose viewer never connected at all ends after twice that
          (`viewer_never_connected`) - without it, an abandoned request would keep a shared
          stream running indefinitely;
        - a stream whose current generation never connected fails its sessions (`ingest_timeout`);
        - a running stream silent for `absolute_idle_seconds` ends them (`ingest_stalled_timeout`);
        - released streams past their linger stop, deferred starts and downgrades are retried.
        """
        acted_on: list[str] = []
        now = self._clock()
        for session_id, session in list(self._sessions.items()):
            if session_id not in self._sessions:
                continue
            reason = None
            if (
                session.viewer_count == 0
                and session.last_viewer_disconnected_at is not None
                and time.monotonic() - session.last_viewer_disconnected_at
                > self._viewer_grace_seconds
            ):
                reason = "viewer_idle_timeout"
            elif (
                not session.has_had_viewer
                and time.monotonic() - session.created_at > 2 * self._viewer_grace_seconds
            ):
                reason = "viewer_never_connected"
            if reason is not None:
                self._remove_session(session_id, outcome="ended", reason=reason)
                acted_on.append(session_id)

        for stream in list(self._streams.values()):
            if stream.stream_id not in self._streams:
                continue
            session_ids = list(stream.session_ids)
            if (
                stream.state == DeviceStreamState.STARTING
                and stream.awaiting_connection
                and stream.start_requested_at is not None
                and not stream.start_pending
                and now - stream.start_requested_at > self._ingest_timeout_seconds
            ):
                self._terminate_stream(stream, reason="ingest_timeout")
                acted_on.extend(session_ids)
                continue
            if (
                stream.state == DeviceStreamState.ACTIVE
                and stream.last_frame_at is not None
                and now - stream.last_frame_at > self._absolute_idle_seconds
            ):
                self._terminate_stream(stream, reason="ingest_stalled_timeout")
                acted_on.extend(session_ids)
                continue
            if stream.start_pending:
                self._request_start(stream)
            self._reconcile(stream)
        await self.flush()
        return acted_on

    # ------------------------------------------------------------------ outbox

    def _enqueue(self, action: Callable[[], Awaitable[None]]) -> None:
        self._outbox.append(action)

    def _enqueue_command(
        self, terminal_id: str, correlation_id: str, command: str, fields: dict[str, object]
    ) -> None:
        # `publish_device_command` is the general name; a publisher that only implements the
        # older `publish_stop_command` (same envelope) is used through that.
        publish = getattr(self._event_publisher, "publish_device_command", None) or (
            self._event_publisher.publish_stop_command
        )
        self._enqueue(
            lambda: publish(
                terminal_id=terminal_id,
                correlation_id=correlation_id,
                command=command,
                fields=fields,
            )
        )

    def _schedule_flush(self) -> None:
        if not self._outbox:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop (synchronous caller): the next awaited call flushes in order
        task = loop.create_task(self.flush())
        self._flush_tasks.add(task)
        task.add_done_callback(self._flush_tasks.discard)

    async def flush(self) -> None:
        """Publishes queued commands and events strictly in the order they were decided."""
        async with self._flush_lock:
            while self._outbox:
                action = self._outbox.pop(0)
                try:
                    await action()
                except Exception as exc:  # noqa: BLE001 - one failed publish must not block the rest
                    log_with_fields(logger, 40, "session_outbox_publish_failed", error=str(exc))

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)

    @property
    def active_stream_count(self) -> int:
        return len(self._streams)
