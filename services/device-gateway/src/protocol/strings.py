"""JT/T 808-2013 `STRING` data type (§4.2, verbatim): "STRING GBK 编码，若无数据，置空" —
"STRING: GBK encoding; empty if no data." Every `STRING`-typed field in the spec (registration's
vehicle identifier §8.5, authentication's auth code §8.8, the future registration response's
auth code §8.6) uses this encoding — centralized here rather than duplicated per handler.
"""

from __future__ import annotations

from src.protocol.exceptions import MalformedFrameError


def decode_gbk_string(data: bytes) -> str:
    if not data:
        return ""
    try:
        return data.decode("gbk")
    except UnicodeDecodeError as exc:
        raise MalformedFrameError(f"Invalid GBK-encoded STRING field: {exc}") from exc


def encode_gbk_string(value: str) -> bytes:
    if not value:
        return b""
    return value.encode("gbk")
