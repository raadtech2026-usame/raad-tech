"""Session-lifecycle event publishing (ADR-0024 §8/§9) — the relay's own participant role on the
shared `raad:events` Redis Stream, alongside the Business API's outbox relay and
`device-gateway`'s own publishers/consumers. Two directions:

- **Lifecycle facts (this service -> Backend)**: `VideoSessionActivated`/`VideoSessionEnded`/
  `VideoSessionFailed`, consumed by the Business API to drive its own `VideoSession` Postgres
  row through the identical, already-implemented `activate()`/`end()`/`fail()` transitions.
- **Stop-signal commands (this service -> device-gateway, ADR-0024 §5 point 4)**: on teardown,
  the relay publishes the *same* `Jt1078SignalCommandRequested` wire event
  `services/device-gateway/src/vendors/jt808/commands/redis_video_signaling_consumer.py` already
  consumes from the Business API — the relay is a second, legitimate publisher of that event
  family for exactly the one case ADR-0024 §5 point 4 names ("the relay:... signals the device to
  stop its media channel via the same coordination path used to start it (§8)"), not a new
  command family of its own.
"""
