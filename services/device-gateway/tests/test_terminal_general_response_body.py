"""`0x0001` terminal general response body parsing (`handlers/terminal_general_response_body.py`,
`mdvrdocs/MDVR-808-1078-spec.pdf` §5.1.1 Table 5.1)."""

import unittest

from src.vendors.jt808.handlers.terminal_general_response_body import (
    RESULT_FAILURE,
    RESULT_MESSAGE_ERROR,
    RESULT_NOT_SUPPORTED,
    RESULT_SUCCESS,
    parse_terminal_general_response,
)
from src.vendors.jt808.protocol.exceptions import MalformedFrameError


class TerminalGeneralResponseTests(unittest.TestCase):
    def test_parses_all_fields(self) -> None:
        body = (7).to_bytes(2, "big") + (0x9101).to_bytes(2, "big") + bytes([RESULT_SUCCESS])
        ack = parse_terminal_general_response(body)
        self.assertEqual(ack.original_serial_no, 7)
        self.assertEqual(ack.original_message_id, 0x9101)
        self.assertEqual(ack.result, RESULT_SUCCESS)
        self.assertTrue(ack.is_success)

    def test_non_success_results_are_not_is_success(self) -> None:
        for result in (RESULT_FAILURE, RESULT_MESSAGE_ERROR, RESULT_NOT_SUPPORTED):
            body = (1).to_bytes(2, "big") + (1).to_bytes(2, "big") + bytes([result])
            ack = parse_terminal_general_response(body)
            self.assertFalse(ack.is_success)
            self.assertEqual(ack.result, result)

    def test_rejects_body_shorter_than_5_bytes(self) -> None:
        with self.assertRaises(MalformedFrameError):
            parse_terminal_general_response(b"\x00\x01\x00\x02")


if __name__ == "__main__":
    unittest.main()
