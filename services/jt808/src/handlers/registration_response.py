"""Terminal Registration Response (`0x8100`) body encoding — JT/T 808-2013 §8.6 Table 8,
verbatim:

| Offset | Field              | Type   | Notes |
|--------|--------------------|--------|-------|
| 0      | response serial no | WORD   | the original `0x0100` message's serial no |
| 2      | result             | BYTE   | 0 success; 1 vehicle already registered; 2 no such vehicle; 3 terminal already registered; 4 no such terminal |
| 3      | auth code          | STRING | present *only* when result == success (§8.6: "只有在成功后才有该字段") |
"""

from __future__ import annotations

from src.handlers.provisioning_port import RegistrationResult
from src.protocol.strings import encode_gbk_string

REGISTRATION_RESPONSE_MESSAGE_ID = 0x8100

_RESULT_CODES = {
    RegistrationResult.SUCCESS: 0,
    RegistrationResult.VEHICLE_ALREADY_REGISTERED: 1,
    RegistrationResult.VEHICLE_NOT_FOUND: 2,
    RegistrationResult.TERMINAL_ALREADY_REGISTERED: 3,
    RegistrationResult.TERMINAL_NOT_FOUND: 4,
}


def build_registration_response_body(
    *,
    original_serial_no: int,
    result: RegistrationResult,
    auth_code: str | None = None,
) -> bytes:
    result_byte = _RESULT_CODES[result]
    body = original_serial_no.to_bytes(2, "big") + bytes([result_byte])
    if result == RegistrationResult.SUCCESS:
        body += encode_gbk_string(auth_code or "")
    return body
