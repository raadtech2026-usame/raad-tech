"""Subpackage reassembly (JT808 Technical Design §6: "Fragmentation: JT808 messages may be
split; the parser reassembles multi-packet messages by (terminal, message-id, total/index)
before dispatch."). JT/T 808-2013 §4.4.3's subpackage block (总包数 total_packages, 包序号
package_sequence — both WORD, sequence starting at 1, §4.4.3 Table 3) is the wire-level fact
this reassembles against.

Keyed by `(terminal_id, message_id)`, not also `total_packages` — a terminal sending two
*different* concurrent multi-part messages of the same `message_id` would be inherently
ambiguous at the protocol level (nothing else disambiguates them), so a new arrival whose
`total_packages` disagrees with an already-pending entry for the same key is treated as a
fresh submission that replaces the old one, not a corrupt continuation.

**Retransmission requests for missing subpackages (§8.4, msg `0x8003` "补传分包请求") are a
Business-message-specific behavior — a Handler's job, not the Packet Parser's — explicitly out
of this phase's scope.** This reassembler only accumulates what arrives and evicts abandoned
partial sets after a configurable timeout — no approved document gives a reassembly-timeout
number, so it stays caller-configured, the same "don't invent a protocol constant" stance
Phase 9.1's `idle_timeout_seconds` and Phase 9.2's `device_session_timeout_seconds` both take.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.protocol.exceptions import ReassemblyOverflowError


@dataclass
class _PendingMessage:
    total_packages: int
    parts: dict[int, bytes] = field(default_factory=dict)
    first_seen_at: float = field(default_factory=time.monotonic)


class MessageReassembler:
    def __init__(self, *, max_pending: int = 1000) -> None:
        self._max_pending = max_pending
        self._pending: dict[tuple[str, int], _PendingMessage] = {}

    def add_part(
        self,
        *,
        terminal_id: str,
        message_id: int,
        total_packages: int,
        package_sequence: int,
        body: bytes,
    ) -> bytes | None:
        """Returns the fully reassembled body once every package `1..total_packages` has
        arrived, or `None` while still awaiting more parts."""
        key = (terminal_id, message_id)
        pending = self._pending.get(key)
        if pending is None or pending.total_packages != total_packages:
            if pending is None and len(self._pending) >= self._max_pending:
                raise ReassemblyOverflowError(
                    f"Too many pending subpackaged messages (max={self._max_pending})."
                )
            pending = _PendingMessage(total_packages=total_packages)
            self._pending[key] = pending

        pending.parts[package_sequence] = body

        if len(pending.parts) >= total_packages and all(
            i in pending.parts for i in range(1, total_packages + 1)
        ):
            del self._pending[key]
            return b"".join(pending.parts[i] for i in range(1, total_packages + 1))
        return None

    def sweep_expired(self, *, timeout_seconds: float) -> list[tuple[str, int]]:
        """Evicts partial message sets older than `timeout_seconds` (measured from the first
        part received). Returns the evicted `(terminal_id, message_id)` keys."""
        now = time.monotonic()
        expired = [
            key
            for key, pending in self._pending.items()
            if now - pending.first_seen_at > timeout_seconds
        ]
        for key in expired:
            del self._pending[key]
        return expired

    def __len__(self) -> int:
        return len(self._pending)
