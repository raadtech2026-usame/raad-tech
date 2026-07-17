"""Password hashing service (Backend LLD §17 `security`: "password hashing").

`PasswordHasher` is the contract; `Pbkdf2PasswordHasher` is its concrete implementation
using PBKDF2-HMAC-SHA256 (stdlib `hashlib`, no new dependency — Rule: Workflow #2). No login
or password-reset *flow* is implemented here — only the reusable hash/verify primitives those
future `modules/iam` use-cases will call.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from abc import ABC, abstractmethod
from base64 import b64decode, b64encode

_ALGORITHM_ID = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 260_000
_SALT_BYTES = 16


class PasswordHasher(ABC):
    @abstractmethod
    def hash(self, plain_password: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def verify(self, plain_password: str, hashed_password: str) -> bool:
        raise NotImplementedError


class Pbkdf2PasswordHasher(PasswordHasher):
    """Stored format: `pbkdf2_sha256$<iterations>$<salt_b64>$<derived_key_b64>` — the
    iteration count travels with the hash so it can be raised over time without invalidating
    already-hashed passwords."""

    def __init__(self, *, iterations: int = _DEFAULT_ITERATIONS) -> None:
        self._iterations = iterations

    def hash(self, plain_password: str) -> str:
        salt = secrets.token_bytes(_SALT_BYTES)
        derived = self._derive(plain_password, salt, self._iterations)
        return "$".join(
            [
                _ALGORITHM_ID,
                str(self._iterations),
                b64encode(salt).decode("ascii"),
                b64encode(derived).decode("ascii"),
            ]
        )

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        try:
            algorithm_id, iterations_str, salt_b64, derived_b64 = hashed_password.split(
                "$"
            )
            if algorithm_id != _ALGORITHM_ID:
                return False
            iterations = int(iterations_str)
            salt = b64decode(salt_b64)
            expected = b64decode(derived_b64)
        except (ValueError, TypeError):
            return False

        actual = self._derive(plain_password, salt, iterations)
        return hmac.compare_digest(actual, expected)

    @staticmethod
    def _derive(plain_password: str, salt: bytes, iterations: int) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256", plain_password.encode("utf-8"), salt, iterations
        )
