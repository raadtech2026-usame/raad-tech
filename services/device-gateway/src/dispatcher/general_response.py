"""Platform general response (`0x8001`, JT/T 808-2013 §8.2, Table 5 — verbatim):

| Offset | Field              | Type  | Notes |
|--------|--------------------|-------|-------|
| 0      | response serial no | WORD  | the original terminal message's serial no |
| 2      | response message id| WORD  | the original terminal message's message id |
| 4      | result             | BYTE  | 0 success/ack; 1 failure; 2 message-error; 3 not-supported; 4 alarm-processing-ack |

Only `RESULT_NOT_SUPPORTED` is used this phase (`UnknownMessageHandler`) — the other result
codes require a real business decision (success/failure/alarm-ack) this phase's placeholder
handlers explicitly do not make (see `dispatcher/handler.py`'s module docstring and the
resolved Phase 9.4 scope: known-but-unimplemented message IDs send no response at all, only
genuinely unknown ones get an automatic ack).
"""

from __future__ import annotations

GENERAL_RESPONSE_MESSAGE_ID = 0x8001

RESULT_SUCCESS = 0
RESULT_FAILURE = 1
RESULT_MESSAGE_ERROR = 2
RESULT_NOT_SUPPORTED = 3
RESULT_ALARM_ACK = 4


def build_general_response_body(
    *, original_serial_no: int, original_message_id: int, result: int
) -> bytes:
    return (
        original_serial_no.to_bytes(2, "big")
        + original_message_id.to_bytes(2, "big")
        + bytes([result])
    )
