# Skill: JT808 Review

## Purpose
Validate changes to the JT808 TCP server against the protocol design and the device-plane
architectural boundary.

## Workflow
1. Confirm the change does not write to Business API tables directly — only events are published.
2. Confirm any new vendor-specific handling is isolated in the Anti-Corruption Layer/adapter, not
   mixed into the core parser/dispatcher.
3. Confirm backfilled data (0x0704, late 0x0200) is flagged `backfill=true` and carries its original
   timestamp, and that live-view logic still excludes it.
4. Confirm session-state changes go through the Redis session registry contract, not ad hoc local
   state that would break sharding.
5. Confirm new commands are correlation-ID tracked end-to-end.
6. Confirm unknown/unauthenticated devices are still rejected and audited after the change.

## When to use
Before merging any change to `services/jt808/`.
