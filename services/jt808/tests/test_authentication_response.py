"""`build_general_response_body` as used for Terminal Authentication (`0x0102` -> `0x8001`,
Phase 9.5; JT/T 808-2013 §8.2 Table 5): echoed serial/message-id and the success/failure byte.
"""

import unittest

from src.dispatcher.general_response import (
    RESULT_FAILURE,
    RESULT_SUCCESS,
    build_general_response_body,
)


class AuthenticationResponseEncodingTests(unittest.TestCase):
    def test_success_echoes_serial_and_message_id_and_result_zero(self) -> None:
        body = build_general_response_body(
            original_serial_no=9, original_message_id=0x0102, result=RESULT_SUCCESS
        )
        self.assertEqual(body[0:2], (9).to_bytes(2, "big"))
        self.assertEqual(body[2:4], (0x0102).to_bytes(2, "big"))
        self.assertEqual(body[4], 0)

    def test_failure_encodes_result_one(self) -> None:
        body = build_general_response_body(
            original_serial_no=9, original_message_id=0x0102, result=RESULT_FAILURE
        )
        self.assertEqual(body[4], 1)

    def test_body_is_exactly_five_bytes(self) -> None:
        body = build_general_response_body(
            original_serial_no=0, original_message_id=0x0102, result=RESULT_SUCCESS
        )
        self.assertEqual(len(body), 5)


if __name__ == "__main__":
    unittest.main()
