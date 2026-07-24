"""Device-registry projection (device-gateway Redis integration) — a read-model of `fleet_device`
devices, kept current by consuming that module's own domain events off the shared `raad:events`
Redis Stream. Backs the real (non-interim) `DeviceProvisioningPort` implementations, replacing
`InMemoryMdvrDeviceProvisioningPort`/`NullDeviceProvisioningPort` as this deployable's actual
device allow-list source of truth, without ever performing a forbidden synchronous cross-service
DB read (`.claude/rules/architecture.md` #3) — this is exactly the read-model/event-consumption
pattern that rule requires instead.
"""
