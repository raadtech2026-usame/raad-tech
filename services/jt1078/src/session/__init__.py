"""Video Session Manager (VSM) — session lifecycle (ADR-0024 §5), viewer-count tracking, and
signed single-use viewer tokens (ADR-0024 §5 point 2, D5 enforcement). Holds only in-memory,
per-session state for the lifetime of an active session (ADR-0024 §4) — nothing here is ever
written to disk or to Postgres; `events/` publishes lifecycle facts onto the broker for the
Business API to persist its own `video_sessions` control-metadata row.
"""
