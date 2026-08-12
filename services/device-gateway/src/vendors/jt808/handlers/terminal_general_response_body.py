"""Terminal General Response (`0x0001`) body parsing — `mdvrdocs/MDVR-808-1078-spec.pdf` §5.1.1
Table 5.1 (identical shape to JT/T 808-2013's own §8.1 Table 3): the terminal's own ACK for a
platform-initiated command, the mirror direction of `dispatcher/general_response.py`'s `0x8001`
encoder (same three fields, same offsets — this module is the decode side for the *other*
direction).

| Offset | Field               | Type | Notes |
|--------|---------------------|------|-------|
| 0      | response serial no  | WORD | the platform command's own serial no |
| 2      | response message id | WORD | the platform command's own message id |
| 4      | result              | BYTE | 0 success/ack; 1 failure; 2 message-error; 3 not-supported |

**Only four result codes are defined for `0x0001`** — unlike `0x8001`'s own `RESULT_ALARM_ACK`
(4), which is specific to the platform's own response and has no `0x0001` equivalent (Table 5.1
lists only 0-3); this module does not reuse `general_response.py`'s result constants for that
reason, even though the first four values are numerically identical.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.vendors.jt808.protocol.exceptions import MalformedFrameError

_FIXED_BODY_LENGTH = 5

RESULT_SUCCESS = 0
RESULT_FAILURE = 1
RESULT_MESSAGE_ERROR = 2
RESULT_NOT_SUPPORTED = 3


@dataclass(frozen=True)
class TerminalGeneralResponse:
    original_serial_no: int
    original_message_id: int
    result: int

    @property
    def is_success(self) -> bool:
        return self.result == RESULT_SUCCESS


def parse_terminal_general_response(body: bytes) -> TerminalGeneralResponse:
    if len(body) < _FIXED_BODY_LENGTH:
        raise MalformedFrameError(
            f"Terminal general response body shorter than the {_FIXED_BODY_LENGTH}-byte "
            f"fixed shape ({len(body)} bytes)."
        )
    return TerminalGeneralResponse(
        original_serial_no=int.from_bytes(body[0:2], "big"),
        original_message_id=int.from_bytes(body[2:4], "big"),
        result=body[4],
    )
