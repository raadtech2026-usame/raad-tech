"""G.711A -> AAC-LC transcode via an `ffmpeg` subprocess, one per audio-capable session
(ADR-0034). Exists because browsers' MediaSource Extensions have no reliable path for either raw
G.711A or its lossless Linear-PCM expansion (`codec/g711a.py`, confirmed live: `MediaSource.
addSourceBuffer('audio/mp4;codecs=ipcm')` throws `NotSupportedError`) - AAC is the one audio
codec `mpegts.js`'s own FLV->fMP4 remux path reliably produces browser-playable output for.

ffmpeg's own native `alaw` demuxer decodes the G.711A input directly - `codec/g711a.py`'s
hand-rolled decode table is not used by this path (kept, correct and tested, for any future
non-ffmpeg need). This module owns only: spawning/feeding/tearing down the subprocess, and
splitting its ADTS-framed stdout back into individual raw AAC payloads (ADTS's own headers are
stripped before handing a frame to the caller - FLV's own `AACPacketType=1` "raw" convention
carries bare AAC data blocks, not ADTS-wrapped ones, since the sequence header conveys
configuration out-of-band instead, per `flv_muxer.build_aac_sequence_header_tag`).

**A per-input-frame relationship is never assumed.** ffmpeg buffers internally; a `feed()` call
does not synchronously return the AAC frame(s) it produced (if any) - `on_aac_frame` fires
asynchronously, from this module's own background reader task, whenever a complete ADTS frame
is available, independent of the exact `feed()` call timing that produced it."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

# AAC-LC (audioObjectType=2), 8000Hz (samplingFrequencyIndex=11 per ISO/IEC 14496-3 Table 1.16),
# mono (channelConfiguration=1) - the exact, fixed `AudioSpecificConfig` for the ffmpeg invocation
# below. Computed directly from known encode parameters, not parsed back out of ADTS - this
# relay controls every ffmpeg argument, so the config is already known, never guessed.
AAC_LC_8KHZ_MONO_AUDIO_SPECIFIC_CONFIG = bytes([0x15, 0x88])

_SOURCE_SAMPLE_RATE_HZ = 8000  # G.711 is only ever standardized at 8kHz - see relay.py's own note
_ADTS_SYNC_WORD_MASK = 0xFFF0  # top 12 bits of a 2-byte big-endian read must be all 1s


def find_adts_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Splits as many complete ADTS frames as `buffer` currently holds into their own raw AAC
    payloads (ADTS header stripped), returning `(frames, leftover_unparsed_tail)`. A malformed
    or de-synced buffer (no valid sync word found) is treated as unparseable and returned whole
    as the leftover - never raises, since ffmpeg's own stdout is a trusted-format but still
    external byte stream this module must not crash on."""
    frames: list[bytes] = []
    pos = 0
    while pos + 7 <= len(buffer):
        header = int.from_bytes(buffer[pos : pos + 2], "big")
        if header & _ADTS_SYNC_WORD_MASK != _ADTS_SYNC_WORD_MASK:
            pos += 1  # not a sync word at this position - resync byte-by-byte
            continue
        protection_absent = buffer[pos + 1] & 0b1
        # aac_frame_length: 13 bits, spanning byte[3] low 2 bits .. byte[5] top 3 bits.
        frame_length = (
            ((buffer[pos + 3] & 0b11) << 11)
            | (buffer[pos + 4] << 3)
            | ((buffer[pos + 5] >> 5) & 0b111)
        )
        if frame_length < 7 or pos + frame_length > len(buffer):
            break  # frame not fully buffered yet - wait for more bytes
        header_length = 7 if protection_absent else 9
        frames.append(buffer[pos + header_length : pos + frame_length])
        pos += frame_length
    return frames, buffer[pos:]


class AacTranscoder:
    def __init__(self, *, on_aac_frame: Callable[[bytes], Awaitable[None]]) -> None:
        self._on_aac_frame = on_aac_frame
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._started = False

    async def start(self) -> None:
        self._process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "alaw",
            "-ar",
            str(_SOURCE_SAMPLE_RATE_HZ),
            "-ac",
            "1",
            "-i",
            "pipe:0",
            "-c:a",
            "aac",
            "-b:a",
            "32k",
            "-f",
            "adts",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        self._started = True

    async def feed(self, g711a_payload: bytes) -> None:
        """A no-op, not an error, before `start()` completes or after the process has died -
        this session's audio simply stays silent rather than raising into the caller's own
        ingest-frame handling loop (video for the same session must never be affected)."""
        if self._process is None or self._process.stdin is None:
            return
        try:
            self._process.stdin.write(g711a_payload)
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, RuntimeError):
            pass

    async def _read_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        buffer = b""
        try:
            while True:
                chunk = await self._process.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk
                frames, buffer = find_adts_frames(buffer)
                for frame in frames:
                    await self._on_aac_frame(frame)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a dead/killed ffmpeg process must not propagate here
            pass

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reader_task = None
        if self._process is not None:
            try:
                if self._process.stdin is not None:
                    self._process.stdin.close()
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass
            self._process = None
