"""Audit finding B19 — PBKDF2 iteration count, and the backward compatibility that makes raising
it safe.

The default moved from 260,000 to 600,000 (OWASP's current recommendation for
PBKDF2-HMAC-SHA256). The claim that justified doing it without a migration or a forced password
reset is that **the iteration count travels inside each stored hash**, so a hash written at the
old cost still verifies after the default rises. That claim is exactly the kind of thing that is
true right up until someone "simplifies" `verify` to use the module constant instead of the
parsed value — at which point every existing user is silently locked out, with no test failing.

This file pins it.
"""

from __future__ import annotations

import unittest

from raad.core.security.password_hashing import (
    _DEFAULT_ITERATIONS,
    Pbkdf2PasswordHasher,
)

_PASSWORD = "C0rrect-Horse-Battery!"


class PasswordHashingIterationTests(unittest.TestCase):
    def test_default_meets_current_owasp_guidance(self) -> None:
        """600,000 for PBKDF2-HMAC-SHA256. Pinned so a future refactor cannot quietly weaken it
        back to a legacy value."""
        self.assertGreaterEqual(_DEFAULT_ITERATIONS, 600_000)

    def test_iteration_count_is_stored_in_the_hash(self) -> None:
        """The property the whole upgrade path rests on."""
        hashed = Pbkdf2PasswordHasher(iterations=260_000).hash(_PASSWORD)
        algorithm, iterations, _salt, _key = hashed.split("$")
        self.assertEqual(algorithm, "pbkdf2_sha256")
        self.assertEqual(int(iterations), 260_000)

    def test_a_hash_written_at_the_old_cost_still_verifies_at_the_new_default(self) -> None:
        """**The regression this file exists for.** A password stored before B19 must keep
        working after it — otherwise raising the default is a silent, total lockout of every
        existing user, and no other test in this suite would catch it."""
        legacy_hash = Pbkdf2PasswordHasher(iterations=260_000).hash(_PASSWORD)

        current_hasher = Pbkdf2PasswordHasher()  # uses the new 600k default

        self.assertTrue(current_hasher.verify(_PASSWORD, legacy_hash))
        self.assertFalse(current_hasher.verify("wrong-password", legacy_hash))

    def test_a_new_hash_uses_the_new_default(self) -> None:
        hashed = Pbkdf2PasswordHasher().hash(_PASSWORD)
        self.assertEqual(int(hashed.split("$")[1]), _DEFAULT_ITERATIONS)
        self.assertTrue(Pbkdf2PasswordHasher().verify(_PASSWORD, hashed))

    def test_hashes_are_salted_per_password(self) -> None:
        """Two hashes of the same password must differ, or the salt is not doing its job."""
        hasher = Pbkdf2PasswordHasher(iterations=1_000)
        self.assertNotEqual(hasher.hash(_PASSWORD), hasher.hash(_PASSWORD))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
