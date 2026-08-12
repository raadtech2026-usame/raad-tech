"""Viewer token tests (`session/viewer_token.py`) — D5-critical: signature, expiry, and
single-use enforcement, all testable without hardware or a real Redis connection."""

import asyncio
import time
import unittest

from src.session.viewer_token import (
    InMemorySingleUseTokenGuard,
    mint_token,
    verify_token_signature,
)

SECRET = b"test-secret-do-not-use-in-prod"


class TokenSignatureTests(unittest.TestCase):
    def test_a_freshly_minted_token_verifies(self) -> None:
        token = mint_token(session_id="session-1", secret=SECRET, ttl_seconds=30)
        self.assertEqual(verify_token_signature(token, secret=SECRET), "session-1")

    def test_a_token_signed_with_a_different_secret_is_rejected(self) -> None:
        token = mint_token(session_id="session-1", secret=SECRET, ttl_seconds=30)
        self.assertIsNone(verify_token_signature(token, secret=b"wrong-secret"))

    def test_a_tampered_payload_is_rejected(self) -> None:
        token = mint_token(session_id="session-1", secret=SECRET, ttl_seconds=30)
        payload_part, signature_part = token.split(".")
        tampered = payload_part + "AAAA" + "." + signature_part
        self.assertIsNone(verify_token_signature(tampered, secret=SECRET))

    def test_an_expired_token_is_rejected(self) -> None:
        token = mint_token(session_id="session-1", secret=SECRET, ttl_seconds=0.01)
        time.sleep(0.05)
        self.assertIsNone(verify_token_signature(token, secret=SECRET))

    def test_malformed_token_strings_are_rejected_not_raised(self) -> None:
        for garbage in ("", "not-a-token", "a.b.c", "..", "notbase64!@#.also-not"):
            self.assertIsNone(verify_token_signature(garbage, secret=SECRET))

    def test_different_sessions_mint_different_tokens(self) -> None:
        token_a = mint_token(session_id="session-A", secret=SECRET, ttl_seconds=30)
        token_b = mint_token(session_id="session-B", secret=SECRET, ttl_seconds=30)
        self.assertNotEqual(token_a, token_b)
        self.assertEqual(verify_token_signature(token_a, secret=SECRET), "session-A")
        self.assertEqual(verify_token_signature(token_b, secret=SECRET), "session-B")


class InMemorySingleUseTokenGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_claim_succeeds(self) -> None:
        guard = InMemorySingleUseTokenGuard()
        self.assertTrue(await guard.claim("token-1"))

    async def test_second_claim_of_the_same_token_fails(self) -> None:
        guard = InMemorySingleUseTokenGuard()
        await guard.claim("token-1")
        self.assertFalse(await guard.claim("token-1"))

    async def test_distinct_tokens_can_each_be_claimed_once(self) -> None:
        guard = InMemorySingleUseTokenGuard()
        self.assertTrue(await guard.claim("token-1"))
        self.assertTrue(await guard.claim("token-2"))
        self.assertFalse(await guard.claim("token-1"))
        self.assertFalse(await guard.claim("token-2"))

    async def test_claimed_entries_expire_after_ttl(self) -> None:
        guard = InMemorySingleUseTokenGuard(ttl_seconds=0.01)
        await guard.claim("token-1")
        await asyncio.sleep(0.05)
        self.assertTrue(await guard.claim("token-1"))  # swept, claimable again


if __name__ == "__main__":
    unittest.main()
