"""Session layer — two tiers.

**Transport-level (Phase 9.1):** `session.py`'s `ConnectionSession` / `registry.py`'s
`SessionRegistry` — keyed by `connection_id`, exist for every accepted TCP socket regardless
of protocol state. See `session.py`'s module docstring for why this is deliberately narrower
than the JT808 LLD's full "Session Manager" concept.

**Device-level (Phase 9.2):** `device_session.py`'s `DeviceSession` / `device_session_registry.
py`'s `DeviceSessionRegistry` / `device_session_manager.py`'s `DeviceSessionManager` — keyed by
`terminal_id`, exist only after successful authentication. See `device_session_manager.py`'s
module docstring for the full Phase 3.4 §5 contract mapping and the resolved Phase 3.4
§21.1-vs-§3 documentation conflict.
"""
