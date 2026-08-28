"""Tests for `codec/aac_transcoder.py`'s pure ADTS-frame-splitting logic (ADR-0034). No real
`ffmpeg` subprocess is spawned here - `find_adts_frames` is pure byte parsing, independently
testable against hand-constructed, spec-correct ADTS bytes (ISO/IEC 13818-7 adts_frame()).
"""

from __future__ import annotations

import unittest

from src.codec.aac_transcoder import find_adts_frames

# One spec-correct, 7-byte (no-CRC) ADTS header wrapping a 5-byte payload (frame_length=12) -
# verified independently, bit-by-bit, against ISO/IEC 13818-7's adts_frame() field layout before
# being hardcoded here: AAC-LC, 8000Hz, mono, protection_absent=1, aac_frame_length=12.
_ADTS_HEADER_5_BYTE_PAYLOAD = bytes([0xFF, 0xF1, 0x6C, 0x40, 0x01, 0x9F, 0xFC])
_PAYLOAD_A = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE])
_FRAME_A = _ADTS_HEADER_5_BYTE_PAYLOAD + _PAYLOAD_A


class FindAdtsFramesTests(unittest.TestCase):
    def test_empty_buffer_yields_no_frames(self) -> None:
        frames, leftover = find_adts_frames(b"")
        self.assertEqual(frames, [])
        self.assertEqual(leftover, b"")

    def test_single_complete_frame_is_extracted_with_header_stripped(self) -> None:
        frames, leftover = find_adts_frames(_FRAME_A)
        self.assertEqual(frames, [_PAYLOAD_A])
        self.assertEqual(leftover, b"")

    def test_two_back_to_back_frames_are_both_extracted_in_order(self) -> None:
        payload_b = bytes([0x11, 0x22, 0x33, 0x44, 0x55])
        frame_b = _ADTS_HEADER_5_BYTE_PAYLOAD + payload_b
        frames, leftover = find_adts_frames(_FRAME_A + frame_b)
        self.assertEqual(frames, [_PAYLOAD_A, payload_b])
        self.assertEqual(leftover, b"")

    def test_a_partially_buffered_trailing_frame_is_left_as_leftover(self) -> None:
        """ffmpeg's stdout arrives in arbitrary chunks - a frame split across two `read()` calls
        must not be dropped or misparsed, just deferred until the rest arrives."""
        partial = _FRAME_A + _ADTS_HEADER_5_BYTE_PAYLOAD + bytes([0x01, 0x02])  # 2 of 5 bytes
        frames, leftover = find_adts_frames(partial)
        self.assertEqual(frames, [_PAYLOAD_A])
        self.assertEqual(leftover, _ADTS_HEADER_5_BYTE_PAYLOAD + bytes([0x01, 0x02]))

    def test_garbage_before_a_real_sync_word_is_skipped_not_treated_as_a_frame(self) -> None:
        frames, leftover = find_adts_frames(b"\x00\x01\x02" + _FRAME_A)
        self.assertEqual(frames, [_PAYLOAD_A])
        self.assertEqual(leftover, b"")

    def test_buffer_with_no_valid_sync_word_is_returned_whole_as_leftover(self) -> None:
        junk = b"\x00\x01\x02\x03\x04\x05\x06\x07"
        frames, leftover = find_adts_frames(junk)
        self.assertEqual(frames, [])
        self.assertEqual(leftover, junk[-6:])  # scanning consumes bytes with no valid sync

    def test_protection_absent_zero_uses_the_9_byte_header_with_crc(self) -> None:
        # protection_absent bit flipped to 0 (CRC present) - header_length becomes 9, so
        # frame_length must grow by 2 bytes (the CRC) for the same 5-byte payload to still parse.
        header = bytearray(_ADTS_HEADER_5_BYTE_PAYLOAD)
        header[1] &= 0b11111110  # clear protection_absent bit
        # frame_length was encoded for header(7)+payload(5)=12; with a 9-byte header it must be
        # 14. Recompute bytes[3]/[4]/[5]'s frame_length bits for 14 instead of 12.
        frame_length = 14
        header[3] = (header[3] & 0b11111100) | ((frame_length >> 11) & 0b11)
        header[4] = (frame_length >> 3) & 0xFF
        header[5] = (header[5] & 0b00011111) | ((frame_length & 0b111) << 5)
        crc = bytes([0x00, 0x00])
        frame = bytes(header) + crc + _PAYLOAD_A
        frames, leftover = find_adts_frames(frame)
        self.assertEqual(frames, [_PAYLOAD_A])
        self.assertEqual(leftover, b"")


if __name__ == "__main__":
    unittest.main()
