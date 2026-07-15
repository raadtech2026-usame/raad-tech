"""Transport-layer session abstraction and registry (Phase 9.1 — Transport Layer only).

See `session.py`'s module docstring for why this is deliberately narrower than the JT808
LLD's full "Session Manager" concept (no `device_id`/`auth_state` yet — no frame has been
parsed or authenticated at this layer).
"""
