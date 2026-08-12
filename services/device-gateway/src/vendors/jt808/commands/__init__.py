"""Platform-initiated command downlink (JT/T 1078 video-signaling forwarding phase; ADR-0024
§1/§6/§7/§8, ADR-0025 §5). Previously an empty scaffold (`.gitkeep` only) — the task's own
architecture requirement named this package as where downlink command infrastructure belongs.

- `video_signaling.py` — JT/T 1078 signaling body encode/decode (`0x9101`/`0x9102`/`0x9105`/
  `0x9205`/`0x9201`/`0x9202` downlink, `0x1205` uplink).
- `pending_commands.py` — `PendingCommandTracker`, the correlation-ID bookkeeping `jt808.md` #6
  requires for every platform-issued command.
- `command_sender.py` — `CommandSender`, resolves a terminal's live connection and sends a
  correlation-tracked JT/T 808 frame.
- `redis_video_signaling_consumer.py` — `RedisVideoSignalingConsumer`, the Redis-broker
  consumer that receives structured command requests from the Business API (ADR-0024 §8's
  "Command direction (Backend -> device, via device-gateway)").

Generic across every JT/T 808 platform-initiated command family — `pending_commands.py`/
`command_sender.py` know nothing about JT/T 1078 specifically; `video_signaling.py` is their
first real caller, not a dependency baked into their own design.
"""
