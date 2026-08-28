"""`SessionBroadcastHub` — fans reassembled frames out to every viewer currently watching one
session. **Each viewer gets its own `FlvMuxer` instance** (a fresh FLV header + a 0-rebased
timestamp timeline), not a shared muxer's output — a viewer joining mid-stream must start its own
FLV container from a header, not from wherever an earlier viewer's timeline happened to be
(ADR-0024 §6 point 6: "viewer connects... with the signed token" is per-viewer, independent of
whether other viewers are already watching). All viewers still consume the *same* underlying
reassembled frames from the ingest pipeline — no per-viewer re-ingestion, no per-viewer buffering
beyond what `FlvMuxer` itself needs to build one tag (ADR-0024 §4's own "small repackaging
buffer... not a growing cache").

**A viewer send failure silently drops that one viewer**, not the whole broadcast — one slow/
disconnected client must never stall or crash delivery to every other viewer of the same session.
"""

from __future__ import annotations

from src.repackager.flv_muxer import FlvMuxer
from src.viewer.websocket_server import WebSocketConnection


class SessionBroadcastHub:
    def __init__(self, session_id: str, *, has_audio: bool = False) -> None:
        """`has_audio` must reflect whether this session actually has a working audio decoder
        (`relay.py`'s own `_AUDIO_DECODERS` dispatch table, the same source of truth
        `_on_reassembled_frame` uses to decide whether to call `broadcast_audio` at all) - it
        drives the FLV file header's own `TypeFlags` byte (`FlvMuxer.start`) so a video-only
        session never falsely claims audio, the real regression this fixes (2026-08-28)."""
        self.session_id = session_id
        self._has_audio = has_audio
        self._viewers: dict[WebSocketConnection, FlvMuxer] = {}

    @property
    def viewer_count(self) -> int:
        return len(self._viewers)

    async def add_viewer(self, connection: WebSocketConnection) -> None:
        muxer = FlvMuxer()
        self._viewers[connection] = muxer
        await connection.send_binary(muxer.start(has_audio=self._has_audio))

    def remove_viewer(self, connection: WebSocketConnection) -> None:
        self._viewers.pop(connection, None)

    async def broadcast_video(
        self, *, annex_b_payload: bytes, is_keyframe: bool, timestamp_ms: int | None
    ) -> list[WebSocketConnection]:
        """Repackages once per viewer via `FlvMuxer.feed_annex_b_video` — NAL splitting/
        classification is cheap (pure byte scanning, no re-encoding), and "has *this* viewer's
        own muxer already sent a sequence header" is genuinely per-viewer state (a viewer
        joining mid-stream needs its own copy, independent of whether earlier viewers already
        got theirs — the same reasoning `add_viewer`'s own docstring already gives for the FLV
        file header itself, now extended to the codec sequence header). Returns the viewers that
        failed to receive it (the caller, `relay.py`, removes them and decrements the session's
        own viewer count)."""
        failed: list[WebSocketConnection] = []
        for connection, muxer in list(self._viewers.items()):
            chunk = muxer.feed_annex_b_video(
                annex_b_payload=annex_b_payload,
                is_keyframe=is_keyframe,
                timestamp_ms=timestamp_ms,
            )
            if not chunk:
                continue
            try:
                await connection.send_binary(chunk)
            except Exception:  # noqa: BLE001 - one bad viewer must not break the broadcast
                failed.append(connection)
        for connection in failed:
            self.remove_viewer(connection)
        return failed

    async def broadcast_audio(
        self, *, pcm_payload: bytes, sample_rate_hz: int, timestamp_ms: int | None
    ) -> list[WebSocketConnection]:
        """`pcm_payload` is already-decoded 16-bit little-endian mono PCM at exactly
        `sample_rate_hz` (`codec/g711a.py`'s `decode_g711a` + `resample_linear_pcm16`) - this
        method only fans it out per-viewer via `FlvMuxer.feed_audio_pcm`, mirroring
        `broadcast_video`'s identical per-viewer-muxer shape. **Dead as of ADR-0034** (`relay.py`
        no longer calls this - the emptied `_AUDIO_DECODERS` table never produces a PCM payload
        to broadcast) - kept, not deleted, as the Linear-PCM tag-building path stays correct and
        tested for any future case that genuinely wants raw PCM over `feed_audio_aac_frame`'s
        transcoded path."""
        failed: list[WebSocketConnection] = []
        for connection, muxer in list(self._viewers.items()):
            chunk = muxer.feed_audio_pcm(
                pcm_payload=pcm_payload,
                sample_rate_hz=sample_rate_hz,
                timestamp_ms=timestamp_ms,
            )
            try:
                await connection.send_binary(chunk)
            except Exception:  # noqa: BLE001 - one bad viewer must not break the broadcast
                failed.append(connection)
        for connection in failed:
            self.remove_viewer(connection)
        return failed

    async def broadcast_audio_aac(
        self, *, aac_payload: bytes, audio_specific_config: bytes, timestamp_ms: int | None
    ) -> list[WebSocketConnection]:
        """`aac_payload` is one already-encoded raw AAC frame (ADTS header already stripped,
        `codec/aac_transcoder.find_adts_frames`) from this session's own `AacTranscoder`
        (ADR-0034) - fans it out per-viewer via `FlvMuxer.feed_audio_aac_frame`, which handles
        sending the AAC sequence-header tag on each viewer's own first frame (or on a config
        change) before the raw frame, mirroring `broadcast_video`/`broadcast_audio`'s identical
        per-viewer-muxer shape."""
        failed: list[WebSocketConnection] = []
        for connection, muxer in list(self._viewers.items()):
            chunk = muxer.feed_audio_aac_frame(
                aac_payload=aac_payload,
                audio_specific_config=audio_specific_config,
                timestamp_ms=timestamp_ms,
            )
            try:
                await connection.send_binary(chunk)
            except Exception:  # noqa: BLE001 - one bad viewer must not break the broadcast
                failed.append(connection)
        for connection in failed:
            self.remove_viewer(connection)
        return failed
