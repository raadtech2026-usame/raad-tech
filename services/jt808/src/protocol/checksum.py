"""JT/T 808-2013 checksum (§4.4.4, verbatim): "校验码指从消息头开始，同后一字节异或，直到校验
码前一个字节，占用一个字节" — "the checksum is: starting from the message header, XOR with the
next byte, continuing through the byte immediately before the checksum; one byte." Computed
over the *unescaped* header+body only — never the frame delimiters, never the checksum byte
itself. Must run *after* `escaping.unescape()` in the parse pipeline (`escaping.py`'s module
docstring: escaping was applied after the checksum was computed, so verification needs the
unescaped bytes back first).
"""

from __future__ import annotations


def compute_checksum(data: bytes) -> int:
    checksum = 0
    for byte in data:
        checksum ^= byte
    return checksum


def verify_checksum(data: bytes, expected: int) -> bool:
    return compute_checksum(data) == expected
