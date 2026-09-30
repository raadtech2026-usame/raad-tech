# ADR-0057: Acknowledging an SOS on the Terminal (`0x8203`)

## Status

**Proposed** (2026-09-30), Phase 3, with ADR-0055 and ADR-0056.

## Context

On a JT/T 808 terminal the emergency (SOS) bit stays set until the platform confirms it with
`0x8203` ("manual confirmation of alarm message", supplier spec §6.8.2). Without that, the driver's
panel keeps signalling, and a later SOS press has nothing new to raise. ADR-0055 records the
alert in RAAD; this ADR closes it on the device too.

## Decision

- Acknowledging an `sos` alert in RAAD (ADR-0055 §5) also asks the device gateway to send
  `0x8203` to that terminal, confirming the emergency bit (alarm serial `0` = the current alarm,
  type bit 0).
- The request reuses the existing command path: the Business API publishes a command request on
  `raad:events` (the `Jt1078SignalCommandRequested` wire contract), and the device gateway's
  `RedisVideoSignalingConsumer` gains one entry in its builder table that encodes `0x8203`. It is
  sent through the correlation-tracked `CommandSender` (`.claude/rules/jt808.md` #6), like every
  other platform command.
- The result is best effort. If the terminal is offline or does not answer, the alert stays
  acknowledged in RAAD and the Safety page shows "not confirmed on the device". Nothing retries
  automatically.
- Only `sos` is confirmed this way. The other types are status bits the terminal clears itself.

## Consequences

- One new downlink message; no new event type and no new consumer.
- **Not hardware-verified**: the terminal is offline. The encoding follows the supplier spec and
  is tested against synthetic frames only.
