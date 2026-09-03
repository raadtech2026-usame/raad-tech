"""`SessionBroadcastHub` — fans reassembled frames out to every viewer currently watching one
session. **Each viewer gets its own `FlvMuxer` instance** (a fresh FLV header + a 0-rebased
timestamp timeline), not a shared muxer's output — a viewer joining mid-stream must start its own
FLV container from a header, not from wherever an earlier viewer's timeline happened to be
(ADR-0024 §6 point 6: "viewer connects... with the signed token" is per-viewer, independent of
whether other viewers are already watching). All viewers still consume the *same* underlying
reassembled frames from the ingest pipeline — no per-viewer re-ingestion, no per-viewer buffering
beyond what `FlvMuxer` itself needs to build one tag (ADR-0024 §4's own "small repackaging
buffer... not a growing cache") plus the small, bounded per-viewer send queue below.

**A viewer send failure silently drops that one viewer**, not the whole broadcast — one slow/
disconnected client must never stall or crash delivery to every other viewer of the same session.

**Redesigned (2026-09-02) so one slow viewer's socket write can never block ingest processing.**
Previously `broadcast_video`/`broadcast_audio*` directly `await connection.send_binary(chunk)` for
each viewer, in a loop, *inside* the same coroutine `ingest/ingest_server.py`'s own per-connection
read loop calls (`_on_reassembled_frame`) — a single viewer whose TCP send buffer is backed up
(a slow network, a stalled browser tab) blocks that `await` until it either completes or times
out, which blocks every *other* viewer of that same camera from receiving the frame currently
being broadcast, and blocks the ingest loop itself from reading the device's *next* frame at all
— exactly the "relay video fan-out is sequential and can block" symptom class this fix closes.

**The fix: each viewer gets its own bounded `asyncio.Queue` + a dedicated background sender
task**, spawned in `add_viewer` (mirrors `relay.py`'s own `_spawn_background` "track it so asyncio
never garbage-collects it early" discipline, scoped per-viewer here). `broadcast_video`/
`broadcast_audio*` still build each viewer's own muxed chunk *synchronously* (cheap, pure byte
work, must stay in ingest-frame order) but only ever `queue.put_nowait` it — never an `await` on
the network. The actual `connection.send_binary` I/O happens on the viewer's own independent task,
so one slow socket write only ever delays that one viewer's own queue, never the ingest loop or
any other viewer. Queues are bounded (`DEFAULT_VIEWER_SEND_QUEUE_MAXSIZE`) and drop the *oldest*
still-queued chunk to make room for a new one when full — a genuinely slow viewer sees dropped
(stale) frames rather than an ever-growing backlog of increasingly-late ones (ADR-0024 §4's own
"not a growing cache" principle, extended to the send path). A viewer whose send fails is removed
by its own sender task (mirroring the pre-existing per-viewer failure isolation, just detected
asynchronously now instead of within the triggering `broadcast_*` call).
"""

from __future__ import annotations

import asyncio

from src.logging_setup import get_logger, log_with_fields
from src.repackager.flv_muxer import FlvMuxer
from src.viewer.websocket_server import WebSocketConnection

logger = get_logger("jt1078_relay.viewer.broadcast_hub")

#: A slow viewer may fall behind by at most this many queued-but-undelivered chunks before older
#: ones start being dropped to make room for newer ones — bounded specifically so "one slow
#: viewer" can never accumulate unlimited stale video in memory, and so its own eventual latency
#: is capped (roughly this many frames' worth of playback time, not unboundedly growing). Not
#: tuned to a byte budget (chunks vary in size) — a *count* ceiling on live H.264/AAC frames at
#: this platform's realistic frame rates (ADR-0033: ~25fps) already keeps worst-case buffered
#: duration well under a second, matching the "practical live-streaming balance" this relay
#: targets everywhere else (`enableStashBuffer: false` on the frontend player, no persisted
#: backlog).
DEFAULT_VIEWER_SEND_QUEUE_MAXSIZE = 32


class _ViewerState:
    """One viewer's own muxer + bounded send queue + its dedicated sender task — grouped so
    `SessionBroadcastHub._viewers` stays a single `dict`, not three dicts kept in lockstep."""

    __slots__ = ("muxer", "queue", "task")

    def __init__(
        self, *, muxer: FlvMuxer, queue: "asyncio.Queue[bytes]", task: asyncio.Task
    ) -> None:
        self.muxer = muxer
        self.queue = queue
        self.task = task


class SessionBroadcastHub:
    def __init__(
        self,
        session_id: str,
        *,
        has_audio: bool = False,
        send_queue_maxsize: int = DEFAULT_VIEWER_SEND_QUEUE_MAXSIZE,
    ) -> None:
        """`has_audio` must reflect whether this session actually has a working audio decoder
        (`relay.py`'s own `_AUDIO_DECODERS` dispatch table, the same source of truth
        `_on_reassembled_frame` uses to decide whether to call `broadcast_audio` at all) - it
        drives the FLV file header's own `TypeFlags` byte (`FlvMuxer.start`) so a video-only
        session never falsely claims audio, the real regression this fixes (2026-08-28)."""
        self.session_id = session_id
        self._has_audio = has_audio
        self._send_queue_maxsize = send_queue_maxsize
        self._viewers: dict[WebSocketConnection, _ViewerState] = {}

    @property
    def viewer_count(self) -> int:
        return len(self._viewers)

    async def add_viewer(self, connection: WebSocketConnection) -> None:
        """The FLV header is still sent directly, synchronously, here — not through the new
        per-viewer queue — so a viewer is guaranteed to have its header before anything else can
        ever be queued for it (`broadcast_video`/`broadcast_audio*` only ever enqueue for a
        connection already present in `self._viewers`, i.e. after this method returns)."""
        muxer = FlvMuxer()
        queue: "asyncio.Queue[bytes]" = asyncio.Queue(maxsize=self._send_queue_maxsize)
        task = asyncio.ensure_future(self._run_sender(connection, queue))
        self._viewers[connection] = _ViewerState(muxer=muxer, queue=queue, task=task)
        await connection.send_binary(muxer.start(has_audio=self._has_audio))

    def remove_viewer(self, connection: WebSocketConnection) -> None:
        state = self._viewers.pop(connection, None)
        if state is not None:
            state.task.cancel()

    async def close_all(self, *, code: int, reason: bytes) -> None:
        """Bug 1 fix (intercom/live "stuck Connecting..." regression): actively closes every
        attached viewer connection with a distinguishable close frame. Previously, the owning
        session's own removal (`relay.py._on_session_removed`) only ever dereferenced this hub
        from `_hubs` — every browser already connected and waiting on it was left holding an
        open, silent WebSocket forever, with no signal that the session it was watching had
        become terminal (FAILED/ENDED). One bad/already-gone viewer must never stop the rest
        from being closed, mirroring `broadcast_video`/`broadcast_audio`'s own per-viewer
        failure isolation. Also cancels every viewer's own sender task — nothing should keep
        trying to deliver queued frames to a session that no longer exists."""
        for connection, state in list(self._viewers.items()):
            state.task.cancel()
            try:
                await connection.send_close(code=code, reason=reason)
            except Exception:  # noqa: BLE001 - best-effort; the peer may already be gone
                pass
        self._viewers.clear()

    async def _run_sender(
        self, connection: WebSocketConnection, queue: "asyncio.Queue[bytes]"
    ) -> None:
        """One viewer's own dedicated delivery loop — the *only* place this class ever awaits a
        socket write. Blocking here (a slow/congested client) only ever delays this one viewer's
        own queue; it can never delay the ingest pipeline or any other viewer, which is the whole
        point of this redesign. Exits (and removes this viewer from the hub) the moment a send
        fails, mirroring the pre-existing per-viewer failure-isolation contract exactly — just
        detected on this task instead of inside the triggering `broadcast_*` call."""
        try:
            while True:
                chunk = await queue.get()
                try:
                    await connection.send_binary(chunk)
                except Exception as exc:  # noqa: BLE001 - one bad viewer must not break the hub
                    queue.task_done()
                    self._viewers.pop(connection, None)
                    log_with_fields(
                        logger, 20, "viewer_send_failed", session_id=self.session_id,
                        error=type(exc).__name__,
                    )
                    return
                else:
                    queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a `run_forever`-shaped loop must never let an
            # unexpected exception vanish unlogged (this codebase's own established discipline
            # for every such consumer loop, CLAUDE.md's Permanent Engineering Lessons) - this
            # task is fire-and-forget from `add_viewer`'s perspective, so nothing else would ever
            # observe or log this otherwise.
            log_with_fields(
                logger, 40, "viewer_sender_task_crashed", session_id=self.session_id,
                error=str(exc),
            )
            self._viewers.pop(connection, None)

    def _enqueue(self, state: _ViewerState, chunk: bytes) -> bool:
        """Non-blocking enqueue for one viewer's own send queue. Returns `True` if an older,
        not-yet-delivered chunk had to be dropped to make room (backpressure occurred for this
        viewer — it has fallen behind), `False` if the queue had room outright. Drop-*oldest*
        (not newest): a viewer that is behind should see the most current frame available next,
        not keep waiting on stale ones it doesn't need for a *live* view."""
        dropped = False
        while True:
            try:
                state.queue.put_nowait(chunk)
                return dropped
            except asyncio.QueueFull:
                dropped = True
                try:
                    state.queue.get_nowait()
                    state.queue.task_done()
                except asyncio.QueueEmpty:
                    continue  # raced the sender task draining it - retry the put

    async def wait_until_idle(self) -> None:
        """Test/observability helper — awaits until every viewer's currently-queued chunks have
        been handed to their own sender task's `send_binary` call (delivered, or dropped for
        backpressure). Production code never needs this (nothing here waits on network delivery
        completing, only on a frame being handed off) — it exists so tests can deterministically
        wait for the async, per-viewer fan-out below instead of guessing with `asyncio.sleep`."""
        for state in list(self._viewers.values()):
            await state.queue.join()

    async def broadcast_video(
        self, *, annex_b_payload: bytes, is_keyframe: bool, timestamp_ms: int | None
    ) -> list[WebSocketConnection]:
        """Repackages once per viewer via `FlvMuxer.feed_annex_b_video` — NAL splitting/
        classification is cheap (pure byte scanning, no re-encoding), and "has *this* viewer's
        own muxer already sent a sequence header" is genuinely per-viewer state (a viewer
        joining mid-stream needs its own copy, independent of whether earlier viewers already
        got theirs — the same reasoning `add_viewer`'s own docstring already gives for the FLV
        file header itself, now extended to the codec sequence header). Muxing stays fully
        synchronous/in-order here; only the resulting bytes' actual delivery is queued (module
        docstring). Returns the viewers whose own send queue was already full and had to drop an
        older frame to make room for this one — a backpressure signal, not a failure signal (a
        backpressured viewer is still attached and still being sent to); an already-failed viewer
        is removed by its own sender task and simply isn't iterated here again."""
        backpressured: list[WebSocketConnection] = []
        for connection, state in list(self._viewers.items()):
            chunk = state.muxer.feed_annex_b_video(
                annex_b_payload=annex_b_payload,
                is_keyframe=is_keyframe,
                timestamp_ms=timestamp_ms,
            )
            if not chunk:
                continue
            if self._enqueue(state, chunk):
                backpressured.append(connection)
        return backpressured

    async def broadcast_audio(
        self, *, pcm_payload: bytes, sample_rate_hz: int, timestamp_ms: int | None
    ) -> list[WebSocketConnection]:
        """`pcm_payload` is already-decoded 16-bit little-endian mono PCM at exactly
        `sample_rate_hz` (`codec/g711a.py`'s `decode_g711a` + `resample_linear_pcm16`) - this
        method only fans it out per-viewer via `FlvMuxer.feed_audio_pcm`, mirroring
        `broadcast_video`'s identical per-viewer-muxer-then-queue shape. **Dead as of ADR-0034**
        (`relay.py` no longer calls this - the emptied `_AUDIO_DECODERS` table never produces a
        PCM payload to broadcast) - kept, not deleted, as the Linear-PCM tag-building path stays
        correct and tested for any future case that genuinely wants raw PCM over
        `feed_audio_aac_frame`'s transcoded path."""
        backpressured: list[WebSocketConnection] = []
        for connection, state in list(self._viewers.items()):
            chunk = state.muxer.feed_audio_pcm(
                pcm_payload=pcm_payload,
                sample_rate_hz=sample_rate_hz,
                timestamp_ms=timestamp_ms,
            )
            if self._enqueue(state, chunk):
                backpressured.append(connection)
        return backpressured

    async def broadcast_audio_aac(
        self, *, aac_payload: bytes, audio_specific_config: bytes, timestamp_ms: int | None
    ) -> list[WebSocketConnection]:
        """`aac_payload` is one already-encoded raw AAC frame (ADTS header already stripped,
        `codec/aac_transcoder.find_adts_frames`) from this session's own `AacTranscoder`
        (ADR-0034) - fans it out per-viewer via `FlvMuxer.feed_audio_aac_frame`, which handles
        sending the AAC sequence-header tag on each viewer's own first frame (or on a config
        change) before the raw frame, mirroring `broadcast_video`'s identical
        per-viewer-muxer-then-queue shape."""
        backpressured: list[WebSocketConnection] = []
        for connection, state in list(self._viewers.items()):
            chunk = state.muxer.feed_audio_aac_frame(
                aac_payload=aac_payload,
                audio_specific_config=audio_specific_config,
                timestamp_ms=timestamp_ms,
            )
            if self._enqueue(state, chunk):
                backpressured.append(connection)
        return backpressured
