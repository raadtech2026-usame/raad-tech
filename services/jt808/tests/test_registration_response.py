"""`build_registration_response_body` (Phase 9.5; JT/T 808-2013 §8.6 Table 8): result-code
mapping, auth-code-present-only-on-success, and echoed original serial number.
"""

import unittest

from src.handlers.provisioning_port import RegistrationResult
from src.handlers.registration_response import build_registration_response_body


class RegistrationResponseEncodingTests(unittest.TestCase):
    def test_success_echoes_serial_and_result_zero_and_carries_auth_code(self) -> None:
        body = build_registration_response_body(
            original_serial_no=42, result=RegistrationResult.SUCCESS, auth_code="ABC123"
        )
        self.assertEqual(body[0:2], (42).to_bytes(2, "big"))
        self.assertEqual(body[2], 0)
        self.assertEqual(body[3:], "ABC123".encode("gbk"))

    def test_success_with_no_auth_code_encodes_empty_string(self) -> None:
        body = build_registration_response_body(
            original_serial_no=1, result=RegistrationResult.SUCCESS, auth_code=None
        )
        self.assertEqual(body[2], 0)
        self.assertEqual(body[3:], b"")

    def test_failure_result_carries_no_auth_code_field_even_if_supplied(self) -> None:
        body = build_registration_response_body(
            original_serial_no=7,
            result=RegistrationResult.TERMINAL_NOT_FOUND,
            auth_code="should-be-ignored",
        )
        self.assertEqual(len(body), 3)  # serial(2) + result(1), no auth-code bytes

    def test_all_result_codes_map_to_their_documented_byte(self) -> None:
        expected = {
            RegistrationResult.SUCCESS: 0,
            RegistrationResult.VEHICLE_ALREADY_REGISTERED: 1,
            RegistrationResult.VEHICLE_NOT_FOUND: 2,
            RegistrationResult.TERMINAL_ALREADY_REGISTERED: 3,
            RegistrationResult.TERMINAL_NOT_FOUND: 4,
        }
        for result, code in expected.items():
            body = build_registration_response_body(original_serial_no=0, result=result)
            self.assertEqual(body[2], code, msg=f"{result} should encode to {code}")


if __name__ == "__main__":
    unittest.main()
