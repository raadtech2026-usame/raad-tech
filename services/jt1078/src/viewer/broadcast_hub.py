"""`SessionBroadcastHub` — fans one device stream's reassembled frames out to every viewer watching
it (ADR-0046: one hub per device stream, shared by all of that stream's sessions).

**Each viewer gets its own `FlvMuxer`** (its own FLV header and 0-rebased timestamp timeline) and
its own bounded send queue drained by its own task, so one slow socket can never block the ingest
loop or another viewer (the 2026-09-02 redesign, unchanged in intent).

**Keyframe-aware delivery (ADR-0046 §5).** H.264 inter frames are useless without the keyframe
they reference, so:

- a viewer starts *awaiting a keyframe*. It receives the FLV header, then the hub's cached current
  GOP (the last keyframe and the frames since, bounded), then live frames. It is never handed a
  P-frame that has no preceding keyframe on its own timeline;
- a viewer's queue is bounded by chunk count, bytes and age. When it overflows the whole queue is
  discarded and the viewer resynchronises on the next keyframe. Dropping single chunks (the previous
  drop-oldest policy) corrupted the picture until the next keyframe and, in production on
  2026-09-25, discarded 614 chunks of a main stream in two minutes;
- a stream restart (stream-type change) calls `begin_new_generation`, which resynchronises every
  viewer on the new generation's first keyframe.

**Stuck viewers (93ded1b, redefined).** A viewer is flagged when it has had data waiting and has
completed no delivery for `stuck_timeout_seconds`. A slow viewer that still drains is resynchronised
instead, never flagged. `None` disables detection (intercom opts out).

**Ownership.** Every viewer belongs to the session whose token admitted it (`owner`), so ending one
session closes only that session's viewers (`close_owner`) while the stream and its other viewers
carry on.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable

from src.logging_setup import get_logger, log_with_fields
from src.repackager.flv_muxer import FlvMuxer, extract_sps_pps, split_annex_b_nalus
from src.viewer.websocket_server import WebSocketConnection

logger = get_logger("jt1078_relay.viewer.broadcast_hub")

#: Upper bound on queued chunks per viewer (one chunk is roughly one frame).
DEFAULT_VIEWER_SEND_QUEUE_MAXSIZE = 64
#: ~5 s of a 2.3 Mbps main stream; a viewer this far behind is resynchronised instead.
DEFAULT_MAX_QUEUE_BYTES = 1_500_000
#: A viewer whose oldest undelivered chunk is older than this is behind live by at least this much.
DEFAULT_MAX_QUEUE_AGE_SECONDS = 2.0
#: One GOP of main stream at this terminal's 1 s keyframe interval is ~300 KB.
DEFAULT_GOP_CACHE_MAX_BYTES = 1_000_000


class _ViewerState:
    """One viewer's muxer, queue, sender task and delivery counters (the counters exist for
    diagnosis, eeba07f: they tell a viewer that never drained apart from one that stalled)."""

    __slots__ = (
        "muxer",
        "owner",
        "chunks",
        "queued_bytes",
        "wake",
        "idle",
        "task",
        "awaiting_keyframe",
        "in_flight",
        "pending_since",
        "connected_at",
        "last_delivery_at",
        "delivered_chunks",
        "delivered_bytes",
        "dropped_chunks",
        "resyncs",
        "skipped_frames",
    )

    def __init__(self, *, muxer: FlvMuxer, owner: str | None, connected_at: float) -> None:
        self.muxer = muxer
        self.owner = owner
        self.chunks: deque[tuple[bytes, float]] = deque()
        self.queued_bytes = 0
        self.wake = asyncio.Event()
        self.idle = asyncio.Event()
        self.idle.set()
        self.task: asyncio.Task | None = None
        self.awaiting_keyframe = True
        self.in_flight = False
        #: When data started waiting with no delivery since; reset only by an actual delivery,
        #: never by a queue flush (a flush is not progress).
        self.pending_since: float | None = None
        self.connected_at = connected_at
        self.last_delivery_at: float | None = None
        self.delivered_chunks = 0
        self.delivered_bytes = 0
        self.dropped_chunks = 0
        self.resyncs = 0
        self.skipped_frames = 0

    def clear_queue(self) -> int:
        dropped = len(self.chunks)
        self.chunks.clear()
        self.queued_bytes = 0
        if not self.in_flight:
            # Nothing is waiting any more. A send still in flight, though, is a socket that has
            # not accepted a write: that keeps counting towards "stuck".
            self.pending_since = None
            self.idle.set()
        return dropped


class SessionBroadcastHub:
    def __init__(
        self,
        stream_id: str,
        *,
        has_audio: bool = False,
        expects_video: bool = True,
        send_queue_maxsize: int = DEFAULT_VIEWER_SEND_QUEUE_MAXSIZE,
        max_queue_bytes: int = DEFAULT_MAX_QUEUE_BYTES,
        max_queue_age_seconds: float = DEFAULT_MAX_QUEUE_AGE_SECONDS,
        gop_cache_max_bytes: int = DEFAULT_GOP_CACHE_MAX_BYTES,
        stuck_timeout_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`has_audio` must reflect whether this stream actually has a working audio transcoder -
        it drives the FLV header's `TypeFlags` (2026-08-28 regression)."""
        self.session_id = stream_id  # historical name, kept for log fields
        self.stream_id = stream_id
        self._has_audio = has_audio
        #: `False` for an audio-only stream (the intercom downlink): nothing is gated on a
        #: keyframe that will never come.
        self._expects_video = expects_video
        self._send_queue_maxsize = send_queue_maxsize
        self._max_queue_bytes = max_queue_bytes
        self._max_queue_age_seconds = max_queue_age_seconds
        self._gop_cache_max_bytes = gop_cache_max_bytes
        self._stuck_timeout_seconds = stuck_timeout_seconds
        self._clock = clock
        self._viewers: dict[WebSocketConnection, _ViewerState] = {}
        self._stuck: dict[WebSocketConnection, None] = {}
        #: The current GOP: (annex-b payload, is_keyframe, timestamp). Empty until a keyframe.
        self._gop: list[tuple[bytes, bool, int | None]] = []
        self._gop_bytes = 0
        self._latest_sps: list[bytes] = []
        self._latest_pps: list[bytes] = []

    @property
    def viewer_count(self) -> int:
        return len(self._viewers)

    @property
    def stuck_timeout_seconds(self) -> float | None:
        return self._stuck_timeout_seconds

    def viewers_of(self, owner: str) -> list[WebSocketConnection]:
        return [c for c, s in self._viewers.items() if s.owner == owner]

    def take_stuck_viewers(self) -> list[WebSocketConnection]:
        """Viewers flagged since the last call - returned once, then forgotten."""
        stuck = list(self._stuck)
        self._stuck.clear()
        return stuck

    def viewer_stats(self, connection: WebSocketConnection) -> dict[str, object] | None:
        state = self._viewers.get(connection)
        if state is None:
            return None
        now = self._clock()
        return {
            "connected_seconds": round(now - state.connected_at, 1),
            "seconds_since_last_delivery": (
                None if state.last_delivery_at is None else round(now - state.last_delivery_at, 1)
            ),
            "delivered_chunks": state.delivered_chunks,
            "delivered_bytes": state.delivered_bytes,
            "dropped_chunks": state.dropped_chunks,
            "resyncs": state.resyncs,
            "skipped_frames": state.skipped_frames,
            "queued_chunks": len(state.chunks),
            "queued_bytes": state.queued_bytes,
            "transport_buffer_bytes": getattr(connection, "pending_write_bytes", None),
        }

    # ------------------------------------------------------------------ membership

    async def add_viewer(self, connection: WebSocketConnection, owner: str | None = None) -> None:
        """Sends the FLV header directly (so nothing can precede it), then queues the cached GOP
        so the viewer's first picture is a decodable keyframe without waiting for the next one."""
        muxer = FlvMuxer()
        state = _ViewerState(muxer=muxer, owner=owner, connected_at=self._clock())
        state.task = asyncio.ensure_future(self._run_sender(connection, state))
        self._viewers[connection] = state
        await connection.send_binary(muxer.start(has_audio=self._has_audio))
        if self._latest_sps:
            muxer.seed_parameter_sets(sps_list=self._latest_sps, pps_list=self._latest_pps)
        for payload, is_keyframe, timestamp_ms in list(self._gop):
            self._deliver_video(connection, state, payload, is_keyframe, timestamp_ms)

    def remove_viewer(self, connection: WebSocketConnection) -> None:
        state = self._viewers.pop(connection, None)
        self._stuck.pop(connection, None)
        if state is not None and state.task is not None:
            state.task.cancel()

    async def close_owner(self, owner: str, *, code: int, reason: bytes) -> None:
        """Closes the viewers admitted by one session only; the stream's other viewers stay."""
        for connection in self.viewers_of(owner):
            state = self._viewers.pop(connection, None)
            self._stuck.pop(connection, None)
            if state is not None and state.task is not None:
                state.task.cancel()
            try:
                await connection.send_close(code=code, reason=reason)
            except Exception:  # noqa: BLE001 - best-effort; the peer may already be gone
                pass

    async def close_all(self, *, code: int, reason: bytes) -> None:
        """Closes every attached viewer (the stream itself ended)."""
        for connection, state in list(self._viewers.items()):
            if state.task is not None:
                state.task.cancel()
            try:
                await connection.send_close(code=code, reason=reason)
            except Exception:  # noqa: BLE001 - best-effort; the peer may already be gone
                pass
        self._viewers.clear()
        self._stuck.clear()

    def begin_new_generation(self) -> None:
        """The device stream restarted (new start command, new connection, possibly a different
        resolution). Frames already queued stay valid to play; everything after waits for the new
        generation's first keyframe, with a fresh sequence header."""
        self._gop.clear()
        self._gop_bytes = 0
        for state in self._viewers.values():
            state.awaiting_keyframe = True
            state.muxer.resync()

    # ------------------------------------------------------------------ delivery

    async def _run_sender(self, connection: WebSocketConnection, state: _ViewerState) -> None:
        """The only place a viewer's socket is written. Exits, removing the viewer, on the first
        failed send."""
        try:
            while True:
                while not state.chunks:
                    state.idle.set()
                    state.wake.clear()
                    await state.wake.wait()
                chunk, _queued_at = state.chunks.popleft()
                state.queued_bytes -= len(chunk)
                state.in_flight = True
                try:
                    await connection.send_binary(chunk)
                except Exception as exc:  # noqa: BLE001 - one bad viewer must not break the hub
                    state.in_flight = False
                    self._viewers.pop(connection, None)
                    state.idle.set()
                    log_with_fields(
                        logger, 20, "viewer_send_failed", session_id=self.stream_id,
                        error=type(exc).__name__,
                    )
                    return
                state.in_flight = False
                state.delivered_chunks += 1
                state.delivered_bytes += len(chunk)
                state.last_delivery_at = self._clock()
                state.pending_since = state.last_delivery_at if state.chunks else None
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - never let a fire-and-forget task die silently
            log_with_fields(
                logger, 40, "viewer_sender_task_crashed", session_id=self.stream_id,
                error=str(exc),
            )
            self._viewers.pop(connection, None)
            state.idle.set()

    def _enqueue(
        self, connection: WebSocketConnection, state: _ViewerState, chunk: bytes, *, is_keyframe: bool
    ) -> bool:
        """Queues one chunk. Returns `True` if the viewer had fallen behind and was resynchronised
        (its queue discarded). A keyframe chunk that arrives on an overflow is kept: it is exactly
        where the viewer can restart from."""
        now = self._clock()
        overflow = bool(state.chunks) and (
            len(state.chunks) >= self._send_queue_maxsize
            or state.queued_bytes + len(chunk) > self._max_queue_bytes
            or now - state.chunks[0][1] > self._max_queue_age_seconds
        )
        if overflow:
            state.dropped_chunks += state.clear_queue()
            state.resyncs += 1
            state.muxer.resync()
            self._check_stuck(connection, state, now)
            if not is_keyframe:
                state.awaiting_keyframe = True
                return True
        if state.pending_since is None:
            state.pending_since = now
        state.chunks.append((chunk, now))
        state.queued_bytes += len(chunk)
        state.idle.clear()
        state.wake.set()
        self._check_stuck(connection, state, now)
        return overflow

    def _check_stuck(self, connection: WebSocketConnection, state: _ViewerState, now: float) -> None:
        if self._stuck_timeout_seconds is None:
            return
        # Stuck = data has been waiting this long with no delivery completing in between.
        if state.pending_since is None:
            return
        if now - state.pending_since < self._stuck_timeout_seconds:
            return
        if connection not in self._stuck:
            self._stuck[connection] = None
            # Re-detection needs another full timeout if the close takes a moment to land.
            state.pending_since = now

    def _deliver_video(
        self,
        connection: WebSocketConnection,
        state: _ViewerState,
        payload: bytes,
        is_keyframe: bool,
        timestamp_ms: int | None,
    ) -> bool:
        if state.awaiting_keyframe:
            if not is_keyframe:
                state.skipped_frames += 1
                self._check_stuck(connection, state, self._clock())
                return False
            state.awaiting_keyframe = False
        chunk = state.muxer.feed_annex_b_video(
            annex_b_payload=payload, is_keyframe=is_keyframe, timestamp_ms=timestamp_ms
        )
        if not chunk:
            return False
        return self._enqueue(connection, state, chunk, is_keyframe=is_keyframe)

    def _remember(self, payload: bytes, is_keyframe: bool, timestamp_ms: int | None) -> None:
        if is_keyframe:
            sps_list, pps_list = extract_sps_pps(split_annex_b_nalus(payload))
            if sps_list:
                self._latest_sps = sps_list
            if pps_list:
                self._latest_pps = pps_list
            self._gop = [(payload, True, timestamp_ms)]
            self._gop_bytes = len(payload)
            return
        if not self._gop:
            return
        if self._gop_bytes + len(payload) > self._gop_cache_max_bytes:
            # Too long to replay usefully; a joining viewer waits for the next keyframe instead.
            self._gop.clear()
            self._gop_bytes = 0
            return
        self._gop.append((payload, False, timestamp_ms))
        self._gop_bytes += len(payload)

    async def wait_until_idle(self) -> None:
        """Test helper: waits until every viewer's queue has been handed to its socket."""
        for state in list(self._viewers.values()):
            await state.idle.wait()

    async def broadcast_video(
        self, *, annex_b_payload: bytes, is_keyframe: bool, timestamp_ms: int | None
    ) -> list[WebSocketConnection]:
        """Returns the viewers that had to be resynchronised for this frame (a backpressure
        signal, not a failure: they stay attached)."""
        self._remember(annex_b_payload, is_keyframe, timestamp_ms)
        backpressured: list[WebSocketConnection] = []
        for connection, state in list(self._viewers.items()):
            if self._deliver_video(connection, state, annex_b_payload, is_keyframe, timestamp_ms):
                backpressured.append(connection)
        return backpressured

    async def broadcast_audio(
        self, *, pcm_payload: bytes, sample_rate_hz: int, timestamp_ms: int | None
    ) -> list[WebSocketConnection]:
        """Linear-PCM path, unused since ADR-0034 but kept tested. Audio waits with video: a
        viewer awaiting a keyframe receives no audio, so the two never start out of step."""
        backpressured: list[WebSocketConnection] = []
        for connection, state in list(self._viewers.items()):
            if self._audio_blocked(state):
                continue
            chunk = state.muxer.feed_audio_pcm(
                pcm_payload=pcm_payload, sample_rate_hz=sample_rate_hz, timestamp_ms=timestamp_ms
            )
            if self._enqueue(connection, state, chunk, is_keyframe=False):
                backpressured.append(connection)
        return backpressured

    async def broadcast_audio_aac(
        self, *, aac_payload: bytes, audio_specific_config: bytes, timestamp_ms: int | None
    ) -> list[WebSocketConnection]:
        """One transcoded AAC frame (ADR-0034). Viewers awaiting a keyframe are skipped, as above,
        except on an audio-only stream (intercom downlink), which has no keyframes at all."""
        backpressured: list[WebSocketConnection] = []
        for connection, state in list(self._viewers.items()):
            if self._audio_blocked(state):
                continue
            chunk = state.muxer.feed_audio_aac_frame(
                aac_payload=aac_payload,
                audio_specific_config=audio_specific_config,
                timestamp_ms=timestamp_ms,
            )
            if self._enqueue(connection, state, chunk, is_keyframe=False):
                backpressured.append(connection)
        return backpressured

    def _audio_blocked(self, state: _ViewerState) -> bool:
        return self._expects_video and state.awaiting_keyframe
