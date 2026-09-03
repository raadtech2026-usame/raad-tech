"""`IngestConnectionRegistry` — ADR-0036's new uplink bridge: `session_id -> the device's own
live ingest TCP connection`, so a browser's operator-mic audio (received over a *separate*
"uplink"-role WebSocket, `viewer/viewer_server.py`) can be written back down the *same* socket
the device is already streaming its own mic audio from. This relay had no uplink (browser ->
device) path of any kind before this ADR — `ingest/ingest_server.py` only ever read from a
device's connection.

**Populated by `IngestServer` the moment a connection's `session_id` is resolved** (the same
moment `SessionManager.mark_ingest_active` is called) — not before, since no ingest connection
exists to write to until then. **Removed the instant that connection closes** — writing to a
dead/closing `StreamWriter` must never be attempted; `send_audio` checks `is_closing()` and is a
silent no-op if so (mirrors `.claude/rules/jt808.md` #2's "never crash the connection" discipline,
applied here to a write instead of a parse failure).

**Only ever populated for a genuine ingest connection** — a session with no device connection yet
(still `REQUESTED`) or a non-audio (video-only) session simply has no entry; `send_audio` on an
unregistered `session_id` is a no-op, not an error (a browser opening the uplink WS slightly
before the device's own ingest connection lands is a normal, expected race — frames sent in that
window are dropped, not queued or errored, the same "drop, don't queue" posture `relay.py`'s own
audio-transcoder-not-ready-yet branch already establishes for the downlink direction).
"""

from __future__ import annotations

import asyncio

from src.ingest.extended_rtp import (
    PAYLOAD_TYPE_G711A,
    MalformedExtendedRtpFrameError,
    encode_audio_frame,
)
from src.logging_setup import get_logger, log_with_fields

logger = get_logger("jt1078_relay.session.uplink_registry")


def _alaw_magnitude(a: int) -> int:
    """Absolute linear magnitude of one A-law byte — the standard ITU-T G.711 expansion, the
    exact inverse of `shared/audio/g711a.ts`'s own encoder. Used only for the telemetry level
    above, never for decoding audio (this relay forwards the uplink bytes verbatim)."""
    a ^= 0x55
    segment = (a & 0x70) >> 4
    mantissa = a & 0x0F
    if segment == 0:
        return (mantissa << 4) + 8
    return ((mantissa << 4) + 0x108) << (segment - 1)


class IngestConnection:
    """One device's own live ingest socket, plus the identity fields needed to address an
    outbound frame correctly (its own reported SIM card number/channel — reusing the device's
    own values, never invented) and a monotonic per-connection sequence counter (the extended-RTP
    header's own `packet_sequence` field, `+1` per frame sent, mirroring the device's own
    behavior on frames it sends)."""

    def __init__(
        self,
        *,
        writer: asyncio.StreamWriter,
        sim_card_number: str,
        logical_channel: int,
        payload_type: int = PAYLOAD_TYPE_G711A,
    ) -> None:
        self._writer = writer
        self._sim_card_number = sim_card_number
        self._logical_channel = logical_channel
        #: The Table 6.21 codec id stamped into every outbound frame's PT field. Defaults to
        #: G.711A because that is unconditionally what the browser encodes
        #: (`shared/audio/g711a.encodeFloat32ToALaw`) — the uplink codec is a property of *this*
        #: relay's own encoder, not of whatever the device happens to report for its own input.
        self._payload_type = payload_type
        self._next_sequence = 0
        #: Uplink telemetry (2026-09-03). Success was previously completely silent: a live
        #: 10-second Hold-to-Talk press forwarded 712 perfectly-formed frames whose payload was
        #: 99.6% A-law zero, and nothing in any log could distinguish that from "no audio was
        #: ever sent". Only a packet capture revealed it. These counters plus the mean amplitude
        #: below make a silent microphone visible from the logs alone.
        self._frames_sent = 0
        self._bytes_sent = 0
        self._amplitude_sum = 0
        self._amplitude_samples = 0

    async def send_audio(self, body: bytes) -> bool:
        """Wraps `body` (raw G.711A bytes, already encoded client-side) in one atomic audio
        extended-RTP frame and writes it to the device's own connection. Returns `False` (no-op,
        not raised) if the connection is already closing — a send racing a device disconnect
        must never crash the caller (`viewer/viewer_server.py`'s own uplink read loop).

        **Defense-in-depth (2026-09-02):** the browser-side chunker (`shared/audio/g711a.
        pushAndDrainFrames`) is now the primary guarantee that `body` never exceeds the 950-byte
        extended-RTP ceiling — this was, in fact, the exact bug that used to close this
        connection outright (a 2048-byte WS message reaching `encode_audio_frame`, which raises
        `MalformedExtendedRtpFrameError` for an oversized body). That primary fix does not make
        this relay trust the browser: a WebSocket client is not a JT/T 808-authenticated device,
        and a future frontend bug or a non-standard client could still send an oversized or
        otherwise malformed payload. Catching it here — logging and dropping just this one frame,
        `False`, mirroring the `ConnectionError`/`OSError` branch's own posture — means one bad
        uplink message can never again take down an otherwise-healthy talk session, the same
        "never crash the connection" discipline this codebase already holds itself to for
        JT/T 808 parse failures (`.claude/rules/jt808.md` #2)."""
        if self._writer.is_closing():
            return False
        try:
            frame = encode_audio_frame(
                sim_card_number=self._sim_card_number,
                logical_channel=self._logical_channel,
                packet_sequence=self._next_sequence,
                body=body,
                payload_type=self._payload_type,
            )
        except MalformedExtendedRtpFrameError as exc:
            log_with_fields(
                logger, 30, "uplink_audio_frame_rejected", error=str(exc), body_length=len(body)
            )
            return False
        self._next_sequence += 1
        try:
            self._writer.write(frame)
            await self._writer.drain()
        except (ConnectionError, OSError) as exc:
            log_with_fields(
                logger, 30, "uplink_audio_write_failed", error=str(exc)
            )
            return False
        self._note_sent(body)
        return True

    #: **First report after only 25 frames (~1s of talking), then every 250 (~10s).** The
    #: original flat 250-frame threshold was measured too coarse against a real bench press:
    #: an operator held Talk and spoke, 135 frames went out, and *nothing* was logged - the very
    #: diagnostic meant to reveal a silent microphone stayed silent itself. A short press must
    #: still report, while a long call must not flood the log.
    _TELEMETRY_FIRST_FRAMES = 25
    _TELEMETRY_EVERY_FRAMES = 250

    def _note_sent(self, body: bytes) -> None:
        self._frames_sent += 1
        self._bytes_sent += len(body)
        self._amplitude_sum += sum(_alaw_magnitude(b) for b in body)
        self._amplitude_samples += len(body)
        if (
            self._frames_sent == self._TELEMETRY_FIRST_FRAMES
            or self._frames_sent % self._TELEMETRY_EVERY_FRAMES == 0
        ):
            self._log_level("uplink_audio_forwarded")

    def _log_level(self, message: str) -> None:
        mean = self._amplitude_sum // max(1, self._amplitude_samples)
        log_with_fields(
            logger,
            20,
            message,
            frames=self._frames_sent,
            bytes=self._bytes_sent,
            payload_type=self._payload_type,
            mean_amplitude=mean,
            # A-law full scale is 32768. A live microphone sits in the hundreds-to-thousands;
            # a mean in the single digits means the browser is capturing silence, which is
            # exactly the defect this field exists to make obvious without a packet capture.
            # Live-confirmed 2026-09-03: a virtual "Voice Changer" input device selected in the
            # browser produced exact zeros, encoded as 0xD5/0x55, decoding to a mean of 8.
            silent=mean < 32,
        )

    def log_session_summary(self) -> None:
        """One authoritative line per talk session, emitted when the device's ingest connection
        goes away (`IngestConnectionRegistry.unregister`). Unlike the periodic reports above this
        fires exactly once and always, so even a press too short to reach the first threshold
        leaves a record of how much audio was forwarded and at what level."""
        if self._frames_sent == 0:
            return
        self._log_level("uplink_audio_session_summary")


class IngestConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[str, IngestConnection] = {}

    def register(
        self, session_id: str, *, writer: asyncio.StreamWriter, sim_card_number: str,
        logical_channel: int, payload_type: int = PAYLOAD_TYPE_G711A,
    ) -> None:
        self._connections[session_id] = IngestConnection(
            writer=writer, sim_card_number=sim_card_number, logical_channel=logical_channel,
            payload_type=payload_type,
        )

    def unregister(self, session_id: str) -> None:
        connection = self._connections.pop(session_id, None)
        if connection is not None:
            connection.log_session_summary()

    async def send_audio(self, session_id: str, body: bytes) -> bool:
        connection = self._connections.get(session_id)
        if connection is None:
            return False
        return await connection.send_audio(body)
