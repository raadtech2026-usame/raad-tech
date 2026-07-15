"""JT/T 808 wire-level framing (Phase 9.1 — Transport Layer only).

Frame *boundary detection* only — finding where one frame ends and the next begins in a byte
stream. No byte-unescaping, checksum verification, or `message_id`/body field parsing: that is
the Packet Parser (Phase 3.4 §6), explicitly out of this phase's scope. See `framing.py`'s
module docstring for why boundary-scanning is protocol-correct without unescaping first.
"""
