"""G.711 A-law -> 16-bit linear PCM decode, and simple linear-interpolation resampling.

Exists because the bench MDVR's own confirmed `0x1003` audio-capability report
(`mdvrdocs/MDVR-808-1078-spec.pdf` Table 6.21, `input_audio_codec=6`) names **G.711A**, not AAC —
`repackager/flv_muxer.py`'s pre-existing `feed_audio_aac` always assumed AAC regardless of what a
device actually reports. FLV has no native container support for arbitrary codecs; G.711A must be
expanded to Linear PCM (FLV `SoundFormat=3`, which `mpegts.js` already decodes) before it can reach
a browser at all. This is a lossless expansion (G.711 A-law's own companding table run in reverse),
not lossy re-encoding — the closest fit to `.claude/rules/jt1078.md` #5's "repackage, don't
transcode" that is actually achievable with zero new dependencies.

**Decode algorithm** is the standard ITU-T G.711 A-law expansion, reproduced verbatim from the
public-domain reference implementation traceable to Sun Microsystems' `g711.c` (the same algorithm
underlying FFmpeg's, SoX's, and Asterisk's own G.711 codecs) — not invented here.
"""

from __future__ import annotations


def _alaw_byte_to_linear16(a_val: int) -> int:
    """One A-law byte -> one signed 16-bit linear PCM sample (ITU-T G.711, standard reference
    algorithm). A-law's own encoding XORs even bits with `0x55` before transmission; the segment
    (top 3 of the remaining 7 bits) selects a linear-slope region, the mantissa (low 4 bits)
    interpolates within it — this is exactly that decode, not a guessed approximation."""
    a_val ^= 0x55
    t = (a_val & 0x0F) << 4
    seg = (a_val & 0x70) >> 4
    if seg == 0:
        t += 8
    elif seg == 1:
        t += 0x108
    else:
        t += 0x108
        t <<= seg - 1
    return t if (a_val & 0x80) else -t


_ALAW_TO_LINEAR16_TABLE: tuple[int, ...] = tuple(
    _alaw_byte_to_linear16(byte) for byte in range(256)
)


def decode_g711a(payload: bytes) -> bytes:
    """G.711A-encoded bytes -> 16-bit little-endian linear PCM (2 bytes out per 1 byte in) —
    the shape FLV `SoundFormat=3` (and `mpegts.js`'s own `ipcm` decode path) expects."""
    samples = bytearray(len(payload) * 2)
    for i, byte in enumerate(payload):
        sample = _ALAW_TO_LINEAR16_TABLE[byte]
        # Python's `int` has no fixed width; struct-pack as a signed 16-bit little-endian value.
        samples[2 * i] = sample & 0xFF
        samples[2 * i + 1] = (sample >> 8) & 0xFF
    return bytes(samples)


def resample_linear_pcm16(pcm16le: bytes, *, from_hz: int, to_hz: int) -> bytes:
    """Linear interpolation between adjacent 16-bit mono samples, changing the sample *count*
    to match `to_hz` while representing the same audio duration — generic (not G.711-specific),
    since any future codec reporting a device-native rate FLV's own 4-value legacy SoundRate
    table (5500/11025/22050/44100 Hz) can't represent directly will need the same treatment.
    A no-op (returns the input unchanged) when `from_hz == to_hz`."""
    if from_hz == to_hz:
        return pcm16le
    sample_count = len(pcm16le) // 2
    if sample_count == 0:
        return b""
    samples = [
        int.from_bytes(pcm16le[2 * i : 2 * i + 2], "little", signed=True)
        for i in range(sample_count)
    ]
    out_count = max(1, round(sample_count * to_hz / from_hz))
    out = bytearray(out_count * 2)
    ratio = (sample_count - 1) / (out_count - 1) if out_count > 1 else 0.0
    for i in range(out_count):
        src_pos = i * ratio
        idx = int(src_pos)
        frac = src_pos - idx
        left = samples[idx]
        right = samples[idx + 1] if idx + 1 < sample_count else left
        value = int(round(left + (right - left) * frac))
        value = max(-32768, min(32767, value))
        packed = value & 0xFFFF
        out[2 * i] = packed & 0xFF
        out[2 * i + 1] = (packed >> 8) & 0xFF
    return bytes(out)
