"""JT/T 808-2013 wire-level protocol handling — two tiers.

**Frame boundary detection (Phase 9.1):** `framing.py`'s `FrameBuffer` — finding where one
frame ends and the next begins in a byte stream. No unescaping, checksum, or field parsing.

**Packet Parser (Phase 9.3):** `escaping.py` (unescape), `checksum.py` (verify), `header.py`
(parse the fixed header + optional subpackage block), `reassembly.py` (multi-part messages),
`message.py` (`InboundMessage`, the typed output), `parser.py` (`PacketParser`, orchestrates
all of the above in the spec-mandated order). Produces a validated `InboundMessage` with an
untyped `body` — message-specific body decoding (register/auth/heartbeat/location/alarm) is
§8 Handlers, a later phase. See `parser.py`'s module docstring for the exact pipeline and
`header.py`'s for the primary-spec citations behind every field.

**Outbound encoding (Phase 9.4 addition):** `escaping.escape` + `header.encode_bcd_phone` +
`encoder.build_frame` — the mirror of the Packet Parser, added because the Message Dispatcher
(`dispatcher/`) needs to send real automatic-acknowledgment frames (§7).
"""
