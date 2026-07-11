"""ID generation port (Backend LLD §17 `ids`; the §20.2 open item — resolved by the approved
Database Design: Phase 3.2 §1 fixes primary keys as **ULID**, stored `CHAR(26)`, time-sortable
and index-friendly. `UlidGenerator` is the concrete implementation, built on the standard
library only (`time`/`secrets`) — no new dependency for what is a small, well-specified
encoding (Crockford Base32).
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from abc import ABC, abstractmethod

_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class IdGenerator(ABC):
    @abstractmethod
    def new_id(self) -> str:
        raise NotImplementedError


class UlidGenerator(IdGenerator):
    """Generates a 26-character ULID: 48 bits of millisecond timestamp (10 Crockford-Base32
    characters) followed by 80 bits of randomness (16 characters). Monotonic within the same
    millisecond in the same process — if two IDs are requested in the same millisecond, the
    random component is incremented rather than redrawn, so IDs generated in quick succession
    stay lexicographically sortable (ULID spec's monotonicity extension).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_timestamp_ms = -1
        self._last_randomness = 0

    def new_id(self) -> str:
        with self._lock:
            timestamp_ms = int(time.time() * 1000)
            if timestamp_ms == self._last_timestamp_ms:
                self._last_randomness += 1
            else:
                self._last_timestamp_ms = timestamp_ms
                self._last_randomness = int.from_bytes(os.urandom(10), "big")
            timestamp_ms = self._last_timestamp_ms
            randomness = self._last_randomness

        return _encode_timestamp(timestamp_ms) + _encode_randomness(randomness)


def _encode_timestamp(timestamp_ms: int) -> str:
    chars = []
    value = timestamp_ms
    for _ in range(10):
        chars.append(_CROCKFORD_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def _encode_randomness(randomness: int) -> str:
    randomness &= (1 << 80) - 1
    chars = []
    value = randomness
    for _ in range(16):
        chars.append(_CROCKFORD_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def generate_ulid() -> str:
    """Module-level convenience for call sites that don't need the `IdGenerator` port (e.g.
    ORM `default=` callables, which must be plain functions, not a bound method needing
    process-shared monotonic state)."""
    timestamp_ms = int(time.time() * 1000)
    randomness = int.from_bytes(secrets.token_bytes(10), "big")
    return _encode_timestamp(timestamp_ms) + _encode_randomness(randomness)
