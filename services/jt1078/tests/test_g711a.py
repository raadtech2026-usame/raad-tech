"""Tests for `codec/g711a.py` - the G.711A -> Linear PCM decode fixing the bench MDVR's real,
confirmed audio codec (`mdvrdocs/MDVR-808-1078-spec.pdf` Table 6.21, code 6), previously always
mislabeled as AAC by `repackager/flv_muxer.py`'s pre-existing `feed_audio_aac`.
"""

from __future__ import annotations

import unittest

from src.codec.g711a import _alaw_byte_to_linear16, decode_g711a, resample_linear_pcm16


class Alaw16DecodeTests(unittest.TestCase):
    def test_silence_code_decodes_near_zero(self) -> None:
        # 0xD5 is the standard ITU-T G.711 A-law "digital silence" code.
        self.assertEqual(_alaw_byte_to_linear16(0xD5), 8)

    def test_sign_bit_flip_is_an_exact_negative(self) -> None:
        # Only bit 7 (0x80) is the A-law sign bit - flipping just that bit (not the full byte)
        # must negate the decoded value; the segment/mantissa bits (which determine magnitude)
        # are unchanged.
        for byte in range(256):
            sign_flipped = byte ^ 0x80
            self.assertEqual(
                _alaw_byte_to_linear16(byte), -_alaw_byte_to_linear16(sign_flipped)
            )

    def test_every_decoded_value_fits_in_signed_16_bit_range(self) -> None:
        for byte in range(256):
            value = _alaw_byte_to_linear16(byte)
            self.assertGreaterEqual(value, -32768)
            self.assertLessEqual(value, 32767)

    def test_sign_bit_set_is_non_negative(self) -> None:
        for byte in range(256):
            value = _alaw_byte_to_linear16(byte)
            if byte & 0x80:
                self.assertGreaterEqual(value, 0, msg=hex(byte))
            else:
                self.assertLessEqual(value, 0, msg=hex(byte))


class DecodeG711ATests(unittest.TestCase):
    def test_output_is_two_bytes_per_input_byte(self) -> None:
        pcm = decode_g711a(bytes([0xD5, 0x55, 0x00, 0xFF]))
        self.assertEqual(len(pcm), 8)

    def test_empty_input_produces_empty_output(self) -> None:
        self.assertEqual(decode_g711a(b""), b"")

    def test_output_matches_little_endian_signed_16_bit_samples(self) -> None:
        pcm = decode_g711a(bytes([0xD5]))
        expected = _alaw_byte_to_linear16(0xD5)
        actual = int.from_bytes(pcm, "little", signed=True)
        self.assertEqual(actual, expected)


class ResampleLinearPcm16Tests(unittest.TestCase):
    def test_same_rate_is_a_no_op(self) -> None:
        pcm = bytes([0, 0, 100, 0, 200, 0])
        self.assertEqual(resample_linear_pcm16(pcm, from_hz=8000, to_hz=8000), pcm)

    def test_upsampling_increases_sample_count_by_the_expected_ratio(self) -> None:
        # 8 samples @ 8000Hz -> round(8 * 11025/8000) = 11 samples @ 11025Hz.
        pcm = b"".join((i * 100).to_bytes(2, "little", signed=True) for i in range(8))
        resampled = resample_linear_pcm16(pcm, from_hz=8000, to_hz=11025)
        self.assertEqual(len(resampled) % 2, 0)
        self.assertEqual(len(resampled) // 2, 11)

    def test_empty_input_produces_empty_output(self) -> None:
        self.assertEqual(resample_linear_pcm16(b"", from_hz=8000, to_hz=11025), b"")

    def test_interpolated_values_stay_within_the_original_samples_range(self) -> None:
        pcm = b"".join(
            v.to_bytes(2, "little", signed=True) for v in (0, 1000, -1000, 500)
        )
        resampled = resample_linear_pcm16(pcm, from_hz=8000, to_hz=11025)
        values = [
            int.from_bytes(resampled[i : i + 2], "little", signed=True)
            for i in range(0, len(resampled), 2)
        ]
        for value in values:
            self.assertGreaterEqual(value, -1000)
            self.assertLessEqual(value, 1000)


if __name__ == "__main__":
    unittest.main()
