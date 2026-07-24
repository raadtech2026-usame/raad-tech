"""JT808 Message Dispatcher (Phase 9.4; JT808 Technical Design §7). Routes a decoded
`InboundMessage` (Phase 9.3's `PacketParser` output) to the handler registered for its
`message_id` (`registry.py`'s `HandlerRegistry`), or to `unknown_handler.
UnknownMessageHandler` if none is registered (JT808 Technical Design §7: unknown message ids
are "logged + counted and answered per protocol"). `dispatcher.py`'s `MessageDispatcher`
orchestrates resolution, handler invocation, exception containment, and the automatic
general-response send.

Handlers registered this phase (`placeholder_handler.py`'s `PlaceholderMessageHandler`, one
instance per `message_id`) are no-ops — the real business behavior for register/auth/
heartbeat/location/bulk-location/alarm/command-ack/logout (JT808 Technical Design §8) belongs
to a later phase. Dispatcher depends only on packet objects (`protocol.message.
InboundMessage`), the session layer (`session.device_session_manager.DeviceSessionManager`,
via `handler.HandlerContext`), and handler interfaces — never SQLAlchemy, FastAPI, Redis, or
any business module (Tracking/Fleet Device/Organization).
"""
