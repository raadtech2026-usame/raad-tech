"""Terminal Authentication (`0x0102`) body parsing — JT/T 808-2019 shape, confirmed against
`mdvrdocs/MDVR-808-1078-spec.pdf` §5.1.7 Table 5.6 (ADR-0025 §2/§3):

| Offset | Field             | Type     | Notes |
|--------|-------------------|----------|-------|
| 0      | auth code length  | BYTE     | "记为n" — length of the following STRING, call it n |
| 1      | auth code         | STRING   | length n, GBK per §4.2 |
| 1+n    | terminal IMEI     | BYTE[15] | "15位IMEI字符串" — 15-digit IMEI character string |
| 16+n   | software version  | BYTE[20] | vendor-defined, null-padded ("不足位后补0x00") |

Widened from the 2013 shape (auth code `STRING` running to the end of the body, no length
prefix, no IMEI/software-version fields) to the confirmed 2019 shape — ADR-0025 §2.

**IMEI/software version are parsed and structurally validated only — not used as an
authorization input.** ADR-0025 §3's auth-code design (platform-minted code, hashed in
`Device.auth_key_hash`, verified by hash comparison) is the sole accept/reject mechanism this
phase implements; no approved document establishes IMEI cross-checking against `fleet_device.
Device.imei` as part of `0x0102`'s authorization decision, and inventing one would be exactly
the kind of unapproved mechanism ADR-0025 §3 itself was written to avoid. `AuthenticationRequest.
imei`/`software_version` are surfaced for logging/observability only.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.vendors.jt808.protocol.exceptions import MalformedFrameError
from src.vendors.jt808.protocol.strings import decode_gbk_string

_LENGTH_PREFIX_BYTES = 1
_IMEI_BYTES = 15
_SOFTWARE_VERSION_BYTES = 20


@dataclass(frozen=True)
class AuthenticationRequest:
    auth_code: str
    imei: str
    software_version: str


def parse_authentication_request(body: bytes) -> AuthenticationRequest:
    if len(body) < _LENGTH_PREFIX_BYTES:
        raise MalformedFrameError(
            "Authentication body shorter than the 1-byte auth-code-length prefix."
        )

    auth_code_length = body[0]
    fixed_length = (
        _LENGTH_PREFIX_BYTES + auth_code_length + _IMEI_BYTES + _SOFTWARE_VERSION_BYTES
    )
    if len(body) < fixed_length:
        raise MalformedFrameError(
            f"Authentication body shorter than the {fixed_length}-byte length this frame's "
            f"own auth-code-length prefix (n={auth_code_length}) declares "
            f"({len(body)} bytes)."
        )

    auth_code_start = _LENGTH_PREFIX_BYTES
    auth_code_end = auth_code_start + auth_code_length
    imei_end = auth_code_end + _IMEI_BYTES
    software_version_end = imei_end + _SOFTWARE_VERSION_BYTES

    auth_code = decode_gbk_string(body[auth_code_start:auth_code_end])
    imei = body[auth_code_end:imei_end].decode("ascii", errors="replace")
    software_version = (
        body[imei_end:software_version_end]
        .rstrip(b"\x00")
        .decode("ascii", errors="replace")
    )

    return AuthenticationRequest(
        auth_code=auth_code, imei=imei, software_version=software_version
    )
