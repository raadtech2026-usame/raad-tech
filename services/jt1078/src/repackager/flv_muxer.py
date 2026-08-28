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

# FLV file-header TypeFlags byte (offset 4): bit 0 = video present, bit 2 = audio present
# (Adobe FLV spec). Video is always present for every session this relay ever muxes; audio is
# NOT - a real, previously-latent bug (found live, 2026-08-28, diagnosing a video regression):
# this byte used to be the hardcoded constant `0x05` (claiming audio present) for *every*
# session regardless of whether any audio tag would ever actually be sent. That was invisible
# only because the frontend's own `hasAudio: false` override forcibly suppressed audio-tag
# parsing client-side, masking the header's false claim - removing that override (the G.711A
# audio fix) exposed it: `mpegts.js`'s own `isComplete()` gate waits forever for audio metadata
# a video-only session never sends, once the header itself says to expect it. `build_flv_header`
# makes this byte honest per-session instead of a blanket assumption.
_TYPE_FLAGS_VIDEO = 0b001
_TYPE_FLAGS_AUDIO = 0b100


def build_flv_header(*, has_audio: bool) -> bytes:
    type_flags = _TYPE_FLAGS_VIDEO | (_TYPE_FLAGS_AUDIO if has_audio else 0)
    return b"FLV" + bytes([0x01, type_flags]) + (9).to_bytes(4, "big")


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

# FLV Linear PCM, little-endian (Adobe FLV spec's own SoundFormat enum) - the format
# `mpegts.js`'s own FLV demuxer actually decodes (confirmed by inspecting its bundled source;
# it does not implement G.711/A-law at all), used for the G.711A-decoded bench MDVR audio via
# `codec/g711a.decode_g711a`. Never sent for any codec this relay hasn't confirmed how to decode.
_SOUND_FORMAT_LINEAR_PCM_LE = 3
_SOUND_SIZE_16BIT = 1
_SOUND_TYPE_MONO = 0
# FLV's legacy audio tag header has only a 2-bit SoundRate field - four fixed values, no
# "arbitrary Hz" option (confirmed against `mpegts.js`'s own `_flvSoundRateTable`:
# `[5500, 11025, 22050, 44100, 48000]` - only the first four are reachable via this 2-bit field,
# the fifth needs the newer FourCC/"Enhanced FLV" tag shape this module doesn't use). A caller
# must resample to one of these four rates first (`codec.g711a.resample_linear_pcm16`) -
# `build_linear_pcm_tag` raises rather than silently mislabeling a rate this field can't encode.
_FLV_SOUND_RATE_FLAGS: dict[int, int] = {5500: 0, 11025: 1, 22050: 2, 44100: 3}

_START_CODE_3 = b"\x00\x00\x01"

# H.264 Annex-B NAL unit type — the low 5 bits of the NALU's first byte (ITU-T H.264 §7.3.1,
# a stable, codec-spec-defined constant, independent of any JT/T 1078 signaling detail).
_NAL_TYPE_MASK = 0x1F
_NAL_TYPE_SPS = 7
_NAL_TYPE_PPS = 8


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
    return _avcc_from_nalus(nalus)


def _avcc_from_nalus(nalus: list[bytes]) -> bytes:
    return b"".join(len(nalu).to_bytes(4, "big") + nalu for nalu in nalus)


def extract_sps_pps(nalus: list[bytes]) -> tuple[list[bytes], list[bytes]]:
    """Classifies already-Annex-B-split NAL units (`split_annex_b_nalus`'s own output) into
    `(sps_list, pps_list)` by NAL unit type — a fixed H.264 bitstream property (ITU-T H.264
    §7.3.1), unrelated to JT/T 1078 signaling, so this needs no vendor-specific knowledge to get
    right. A NALU with a malformed/empty byte is skipped, never raises — real bytes from a real
    ingest connection are never assumed well-formed just because they arrived."""
    sps_list: list[bytes] = []
    pps_list: list[bytes] = []
    for nalu in nalus:
        if not nalu:
            continue
        nal_type = nalu[0] & _NAL_TYPE_MASK
        if nal_type == _NAL_TYPE_SPS:
            sps_list.append(nalu)
        elif nal_type == _NAL_TYPE_PPS:
            pps_list.append(nalu)
    return sps_list, pps_list


def build_avc_decoder_config(*, sps_list: list[bytes], pps_list: list[bytes]) -> bytes:
    """Builds an `AVCDecoderConfigurationRecord` (ISO/IEC 14496-15 §5.2.4.1.1 — a stable,
    codec-container-spec-defined byte structure, not JT/T-1078-specific) from real, already-
    parsed SPS/PPS NAL units. `AVCProfileIndication`/`profile_compatibility`/`AVCLevelIndication`
    are read directly from the first SPS's own bytes 1-3 (immediately after its 1-byte NAL
    header) — always present in any syntactically valid SPS, regardless of device/vendor.
    `lengthSizeMinusOne=3` (4-byte NALU length prefix) matches this muxer's own
    `build_avcc_from_annex_b` convention exactly, so the two must always agree.

    Raises `ValueError` for an empty `sps_list` — there is no valid `AVCDecoderConfigurationRecord`
    without at least one SPS to source the profile/level bytes from; `pps_list` may be empty
    (a real player still needs *a* PPS to decode, but this function's own job is only to build
    a structurally valid record from whatever was actually seen on the wire, not to invent one).
    """
    if not sps_list:
        raise ValueError("build_avc_decoder_config requires at least one SPS.")
    first_sps = sps_list[0]
    if len(first_sps) < 4:
        raise ValueError("SPS NALU too short to read profile/compatibility/level bytes.")

    avc_profile_indication = first_sps[1]
    profile_compatibility = first_sps[2]
    avc_level_indication = first_sps[3]

    parts = [
        bytes(
            [
                0x01,  # configurationVersion
                avc_profile_indication,
                profile_compatibility,
                avc_level_indication,
                0xFF,  # reserved(6 bits)=111111 + lengthSizeMinusOne(2 bits)=11 -> 4-byte length
                0xE0 | (len(sps_list) & 0x1F),  # reserved(3 bits)=111 + numOfSPS(5 bits)
            ]
        )
    ]
    for sps in sps_list:
        parts.append(len(sps).to_bytes(2, "big") + sps)
    parts.append(bytes([len(pps_list) & 0xFF]))  # numOfPictureParameterSets
    for pps in pps_list:
        parts.append(len(pps).to_bytes(2, "big") + pps)
    return b"".join(parts)


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
    decode anything. `avc_decoder_config` is built by `build_avc_decoder_config` (above) from
    whatever SPS/PPS `FlvMuxer.feed_annex_b_video` actually observes on the wire — this function
    itself only wraps an already-built record in its own tag header, unchanged."""
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


def build_linear_pcm_tag(*, pcm_payload: bytes, sample_rate_hz: int, timestamp_ms: int) -> bytes:
    """FLV `SoundFormat=3` (Linear PCM, little-endian) tag - unlike `build_aac_raw_tag`, the
    sound-rate/size/type flags are derived from the caller's own real values, never hardcoded
    (the AAC path's "44kHz/16-bit/stereo" was fabricated and never matched any real device).
    `pcm_payload` must already be 16-bit little-endian mono samples at exactly `sample_rate_hz`
    (`codec.g711a.decode_g711a` + `resample_linear_pcm16`) - this function only builds the tag
    header, it does not itself decode or resample anything."""
    sound_rate_flag = _FLV_SOUND_RATE_FLAGS.get(sample_rate_hz)
    if sound_rate_flag is None:
        raise ValueError(
            f"{sample_rate_hz}Hz has no FLV legacy SoundRate encoding "
            f"(only {sorted(_FLV_SOUND_RATE_FLAGS)} are representable) - resample first."
        )
    header_byte = (
        (_SOUND_FORMAT_LINEAR_PCM_LE << 4)
        | (sound_rate_flag << 2)
        | (_SOUND_SIZE_16BIT << 1)
        | _SOUND_TYPE_MONO
    )
    body = bytes([header_byte]) + pcm_payload
    return _build_tag(tag_type=TAG_TYPE_AUDIO, timestamp_ms=timestamp_ms, data=body)


class FlvMuxer:
    """Stateful only in the sense of tracking `PreviousTagSize` (the 4-byte value FLV requires
    before every tag, including the file header's own trailing zero), rebasing the first frame's
    timestamp to 0, and remembering the latest-seen SPS/PPS NALUs (`_latest_sps_list`/
    `_latest_pps_list`) so a parameter set that arrives in a call by itself (no reassembled JT/T
    1078 frame is guaranteed to carry both together) is still picked up rather than silently
    dropped — see `feed_annex_b_video`. Holds no other video bytes across calls — each `feed_*`
    call returns exactly the bytes to forward to the viewer immediately, matching ADR-0024 §4's
    "no growing cache."
    """

    def __init__(self) -> None:
        self._base_timestamp_ms: int | None = None
        self._wrote_header = False
        self._sent_avc_decoder_config: bytes | None = None
        self._latest_sps_list: list[bytes] = []
        self._latest_pps_list: list[bytes] = []

    def _relative_timestamp(self, timestamp_ms: int | None) -> int:
        if timestamp_ms is None:
            return 0
        if self._base_timestamp_ms is None:
            self._base_timestamp_ms = timestamp_ms
        return max(0, timestamp_ms - self._base_timestamp_ms)

    def start(self, *, has_audio: bool = False) -> bytes:
        """`has_audio` must reflect whether *this session* actually has a working audio decoder
        (`relay.py`'s own `_AUDIO_DECODERS` dispatch table) - never assumed `True` regardless of
        content (see `build_flv_header`'s own docstring for the regression this fixes). Defaults
        to `False`, matching every session's real behavior before any audio capability existed."""
        self._wrote_header = True
        return build_flv_header(has_audio=has_audio) + (0).to_bytes(4, "big")  # PreviousTagSize0

    def feed_video_nalu(
        self, *, avcc_payload: bytes, is_keyframe: bool, timestamp_ms: int | None
    ) -> bytes:
        tag = build_avc_nalu_tag(
            avcc_payload=avcc_payload,
            is_keyframe=is_keyframe,
            timestamp_ms=self._relative_timestamp(timestamp_ms),
        )
        return tag + len(tag).to_bytes(4, "big")

    def feed_annex_b_video(
        self, *, annex_b_payload: bytes, is_keyframe: bool, timestamp_ms: int | None
    ) -> bytes:
        """The SPS/PPS-aware entry point (completes the seam `build_avc_sequence_header_tag`'s
        own docstring used to flag as unpopulated). Splits the raw Annex-B payload once,
        separates SPS(7)/PPS(8) from every other NAL unit (`extract_sps_pps`), and:

        - persists whichever of SPS/PPS this call actually observed into `_latest_sps_list`/
          `_latest_pps_list` independently — a reassembled JT/T 1078 frame is not guaranteed to
          carry SPS and PPS together (the wire format's own `data_type` has no distinct
          "parameter set" value, so a device may deliver them as separate reassembled frames);
          requiring both in the same call would silently and permanently drop whichever one
          arrives alone;
        - emits a fresh `AVCDecoderConfigurationRecord` sequence-header tag, built from the
          *latest known* SPS/PPS state (not just this call's own local NALUs), the first time
          this *viewer's own muxer* has a complete SPS, or again if the latest known pair differs
          byte-for-byte from the one already sent (a real, if rare, mid-stream parameter-set
          change — whether SPS and PPS change together or independently) — never on every frame,
          real players expect this tag once per configuration, not per-NALU;
        - strips SPS/PPS out of the AVCC NALU tag itself (they are carried by the sequence
          header instead, the standard FLV/RTMP muxing convention — sending them twice is
          redundant, not merely harmless, for some real players);
        - returns the concatenated bytes (sequence-header tag, if newly emitted, followed by the
          NALU tag) — still exactly one call, one contiguous chunk to forward to the viewer,
          matching every other `feed_*` method's own contract.

        A frame carrying no VCL NALUs at all (SPS/PPS-only, e.g. a parameter-set refresh with no
        picture data) returns just the sequence-header bytes, if any — never an empty AVCC tag
        with a zero-length payload.
        """
        relative_timestamp = self._relative_timestamp(timestamp_ms)
        nalus = split_annex_b_nalus(annex_b_payload)
        sps_list, pps_list = extract_sps_pps(nalus)
        other_nalus = [
            nalu
            for nalu in nalus
            if nalu and (nalu[0] & _NAL_TYPE_MASK) not in (_NAL_TYPE_SPS, _NAL_TYPE_PPS)
        ]

        if sps_list:
            self._latest_sps_list = sps_list
        if pps_list:
            self._latest_pps_list = pps_list

        chunks: list[bytes] = []
        if (sps_list or pps_list) and self._latest_sps_list:
            avc_decoder_config = build_avc_decoder_config(
                sps_list=self._latest_sps_list, pps_list=self._latest_pps_list
            )
            if avc_decoder_config != self._sent_avc_decoder_config:
                self._sent_avc_decoder_config = avc_decoder_config
                header_tag = build_avc_sequence_header_tag(
                    avc_decoder_config=avc_decoder_config, timestamp_ms=relative_timestamp
                )
                chunks.append(header_tag + len(header_tag).to_bytes(4, "big"))

        # Delivered unconditionally, whether or not a sequence header has been sent yet on
        # *this* muxer (e.g. a viewer joining mid-GOP, before the next keyframe's own
        # parameter-set refresh): a real player buffers/discards NALUs it cannot yet decode
        # rather than erroring, and never delivering stream data at all until the next SPS/PPS
        # refresh would silently stall a legitimately-connected viewer for longer than
        # necessary - the same "never drop real bytes" posture `split_annex_b_nalus`'s own
        # docstring already commits to.
        if other_nalus:
            nalu_tag = build_avc_nalu_tag(
                avcc_payload=_avcc_from_nalus(other_nalus),
                is_keyframe=is_keyframe,
                timestamp_ms=relative_timestamp,
            )
            chunks.append(nalu_tag + len(nalu_tag).to_bytes(4, "big"))

        return b"".join(chunks)

    def feed_audio_aac(self, *, aac_payload: bytes, timestamp_ms: int | None) -> bytes:
        tag = build_aac_raw_tag(
            aac_payload=aac_payload, timestamp_ms=self._relative_timestamp(timestamp_ms)
        )
        return tag + len(tag).to_bytes(4, "big")

    def feed_audio_pcm(
        self, *, pcm_payload: bytes, sample_rate_hz: int, timestamp_ms: int | None
    ) -> bytes:
        """The G.711A-decoded-to-PCM path (see `codec/g711a.py`) - shares this muxer's own
        timestamp rebasing with `feed_video_nalu`/`feed_annex_b_video` so audio and video tags
        from the same session stay on one consistent timeline."""
        tag = build_linear_pcm_tag(
            pcm_payload=pcm_payload,
            sample_rate_hz=sample_rate_hz,
            timestamp_ms=self._relative_timestamp(timestamp_ms),
        )
        return tag + len(tag).to_bytes(4, "big")
