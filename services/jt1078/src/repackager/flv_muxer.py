"""Minimal FLV container muxer — pure struct-packing against the public Adobe FLV file format
spec (stable, unambiguous, not JT/T-1078-specific): 9-byte file header, then repeated
`PreviousTagSize(4) + Tag(TagType(1) + DataSize(UI24) + Timestamp(UI24) + TimestampExt(1) +
StreamID(UI24) + Data)`. This module owns *only* the container — it never decodes, re-encodes, or
inspects the underlying video/audio bitstream beyond what FLV's own tag headers require
(`.claude/rules/jt1078.md` #5's "repackage, never transcode").

**Two things this module does *not* verify, flagged rather than silently assumed** (neither is
specified by `mdvrdocs/MDVR-808-1078-spec.pdf` §6.2.1.1 — that section defines the RTP-extension
wrapper, not the video elementary-stream format inside it):

1. **NAL delimiter convention.** `AnnexBToAvccConverter` assumes the reassembled H.264/H.265
   payload arrives Annex-B-delimited (`0x000001`/`0x00000001` start codes) — the overwhelmingly
   common convention for MDVR/IP-camera H.264 output — and rewrites it into the 4-byte-length-
   prefixed AVCC format FLV's own `AVCVIDEOPACKET` requires. **This conversion is unverified
   against the real procured hardware's actual byte stream** and is exactly the kind of thing
   `.claude/rules/testing.md`'s "live-device-tested" bar exists for — see this phase's own
   implementation report.
2. **Keyframe/codec identification.** `is_keyframe` is derived from `ExtendedRtpFrame.data_type`
   (`I_FRAME` -> keyframe) per the *signaling* spec's own field, not by inspecting NAL unit
   types — correct as long as the device's own `data_type` tagging is accurate, which this module
   has no independent way to cross-check.

**Timestamps**: FLV's own 32-bit millisecond timestamp is built directly from
`ReassembledFrame.timestamp_ms` (already the frame's own relative-time field, spec §6.2.1.1) —
no re-basing beyond wrapping the first frame's timestamp to `0` (`FlvMuxer` tracks a base offset),
since FLV timestamps are conventionally stream-relative, not wall-clock.
"""

from __future__ import annotations

_FLV_HEADER = b"FLV" + bytes([0x01, 0x05]) + (9).to_bytes(4, "big")  # audio+video flags=0x05

TAG_TYPE_AUDIO = 8
TAG_TYPE_VIDEO = 9
TAG_TYPE_SCRIPT = 18

_CODEC_ID_AVC = 7
_CODEC_ID_HEVC = 12  # ("ex" extended codec ID scheme uses a FourCC in real players; kept simple)

_AVC_PACKET_TYPE_SEQUENCE_HEADER = 0
_AVC_PACKET_TYPE_NALU = 1

_FRAME_TYPE_KEYFRAME = 1
_FRAME_TYPE_INTER_FRAME = 2

_SOUND_FORMAT_AAC = 10
_AAC_PACKET_TYPE_RAW = 1

_START_CODE_3 = b"\x00\x00\x01"


def split_annex_b_nalus(payload: bytes) -> list[bytes]:
    """Splits an Annex-B-delimited byte string on `0x000001`/`0x00000001` start codes, returning
    each NAL unit's own bytes (start code stripped). Payload chunks with no recognizable start
    code at all are returned as a single opaque NALU unchanged (defensive — never silently drops
    real bytes, even if the delimiter assumption above turns out to be wrong for this hardware)."""
    positions: list[int] = []
    i = 0
    while i < len(payload) - 2:
        if payload[i : i + 3] == _START_CODE_3:
            positions.append(i)
            i += 3
        else:
            i += 1
    if not positions:
        return [payload] if payload else []

    nalus: list[bytes] = []
    for idx, start in enumerate(positions):
        end = positions[idx + 1] if idx + 1 < len(positions) else len(payload)
        nalu = payload[start + 3 : end]
        # A 4-byte start code (0x00000001) contains the 3-byte code `positions` just matched
        # starting one byte in, so the *previous* NALU's own slice picks up one trailing 0x00
        # byte here - this is H.264 Annex-B's own defined "zero_byte" and decoders are required
        # to tolerate a trailing zero in a NAL unit, so it is left as-is rather than "fixed."
        if nalu:
            nalus.append(nalu)
    return nalus


def build_avcc_from_annex_b(payload: bytes) -> bytes:
    """Annex-B -> length-prefixed AVCC (each NALU prefixed by its own 4-byte big-endian length,
    no start codes) — the format FLV's `AVCVIDEOPACKET` (`AVCPacketType=1`) requires."""
    nalus = split_annex_b_nalus(payload)
    return b"".join(len(nalu).to_bytes(4, "big") + nalu for nalu in nalus)


def _build_tag(*, tag_type: int, timestamp_ms: int, data: bytes) -> bytes:
    timestamp_ms &= 0xFFFFFFFF
    timestamp_low = timestamp_ms & 0xFFFFFF
    timestamp_ext = (timestamp_ms >> 24) & 0xFF
    header = (
        bytes([tag_type])
        + len(data).to_bytes(3, "big")
        + timestamp_low.to_bytes(3, "big")
        + bytes([timestamp_ext])
        + (0).to_bytes(3, "big")  # StreamID, always 0
    )
    return header + data


def build_avc_sequence_header_tag(*, avc_decoder_config: bytes, timestamp_ms: int) -> bytes:
    """The FLV muxer's own "codec parameter set" tag (SPS/PPS wrapped in an
    `AVCDecoderConfigurationRecord`) — real players require this *before* the first NALU tag to
    decode anything. Building `avc_decoder_config` from a real device's SPS/PPS NAL units is a
    genuinely separate, real concern this module exposes a seam for
    (`avc_decoder_config`) but does not build itself, since JT/T 1078's signaling spec gives no
    guarantee about *when*/*how often* a device resends SPS/PPS on the media socket — a real
    integration needs to capture the first I-frame's own parameter sets live, which this codebase
    cannot do without the physical MDVR."""
    body = (
        bytes([(_FRAME_TYPE_KEYFRAME << 4) | _CODEC_ID_AVC])
        + bytes([_AVC_PACKET_TYPE_SEQUENCE_HEADER])
        + (0).to_bytes(3, "big", signed=True)  # composition time
        + avc_decoder_config
    )
    return _build_tag(tag_type=TAG_TYPE_VIDEO, timestamp_ms=timestamp_ms, data=body)


def build_avc_nalu_tag(*, avcc_payload: bytes, is_keyframe: bool, timestamp_ms: int) -> bytes:
    frame_type = _FRAME_TYPE_KEYFRAME if is_keyframe else _FRAME_TYPE_INTER_FRAME
    body = (
        bytes([(frame_type << 4) | _CODEC_ID_AVC])
        + bytes([_AVC_PACKET_TYPE_NALU])
        + (0).to_bytes(3, "big", signed=True)  # composition time
        + avcc_payload
    )
    return _build_tag(tag_type=TAG_TYPE_VIDEO, timestamp_ms=timestamp_ms, data=body)


def build_aac_raw_tag(*, aac_payload: bytes, timestamp_ms: int) -> bytes:
    header_byte = (_SOUND_FORMAT_AAC << 4) | (0b11 << 2) | (0b1 << 1) | 0b1  # 44kHz/16-bit/stereo
    body = bytes([header_byte, _AAC_PACKET_TYPE_RAW]) + aac_payload
    return _build_tag(tag_type=TAG_TYPE_AUDIO, timestamp_ms=timestamp_ms, data=body)


class FlvMuxer:
    """Stateful only in the sense of tracking `PreviousTagSize` (the 4-byte value FLV requires
    before every tag, including the file header's own trailing zero) and rebasing the first
    frame's timestamp to 0. Holds no video bytes across calls — each `feed_*` call returns exactly
    the bytes to forward to the viewer immediately, matching ADR-0024 §4's "no growing cache."
    """

    def __init__(self) -> None:
        self._base_timestamp_ms: int | None = None
        self._wrote_header = False

    def _relative_timestamp(self, timestamp_ms: int | None) -> int:
        if timestamp_ms is None:
            return 0
        if self._base_timestamp_ms is None:
            self._base_timestamp_ms = timestamp_ms
        return max(0, timestamp_ms - self._base_timestamp_ms)

    def start(self) -> bytes:
        self._wrote_header = True
        return _FLV_HEADER + (0).to_bytes(4, "big")  # PreviousTagSize0 = 0

    def feed_video_nalu(
        self, *, avcc_payload: bytes, is_keyframe: bool, timestamp_ms: int | None
    ) -> bytes:
        tag = build_avc_nalu_tag(
            avcc_payload=avcc_payload,
            is_keyframe=is_keyframe,
            timestamp_ms=self._relative_timestamp(timestamp_ms),
        )
        return tag + len(tag).to_bytes(4, "big")

    def feed_audio_aac(self, *, aac_payload: bytes, timestamp_ms: int | None) -> bytes:
        tag = build_aac_raw_tag(
            aac_payload=aac_payload, timestamp_ms=self._relative_timestamp(timestamp_ms)
        )
        return tag + len(tag).to_bytes(4, "big")
