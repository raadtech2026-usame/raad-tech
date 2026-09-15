"""`DeviceRegistryProjection` — an in-memory read-model of `fleet_device` devices, updated by
consuming that module's own domain events (`DeviceRegistered`/`DeviceActivated`/`DeviceSuspended`/
`DeviceReactivated`/`DeviceRetired`/`DeviceAssignedToVehicle`/`DeviceUnassignedFromVehicle`/
`DeviceReassigned`/`DeviceTerminalIdChanged`) — never by a synchronous cross-service DB read
(`.claude/rules/architecture.md` #3). Vendor-agnostic: keyed by both `terminal_id` (JT/T 808 identity) and
`serial_number` (this platform's LSZ MDVR identity, per ADR-0009's Consequences section noting
`device_registered`'s payload needed an additive `serial_number` field for exactly this purpose),
so any current or future vendor adapter can resolve its own identity string back to
`{device_id, organization_id, vehicle_id}` through the same shared projection.

**Event payload shapes this projection depends on — traced to `backend/raad/modules/fleet_device/
domain/events.py` directly, not guessed:** `DeviceRegistered`'s payload carries `terminal_id`/
`serial_number`; every subsequent lifecycle event (`DeviceActivated`/`DeviceSuspended`/
`DeviceReactivated`/`DeviceRetired`) carries only `{actor_id}` and relies on `aggregate_id` (the
`device_id`) to identify which already-registered record it updates — a record for a device_id
this projection has never seen `DeviceRegistered` for is silently ignored (the projection has
nothing to update; this is expected during a consumer's initial catch-up window, not an error).
`DeviceAssignedToVehicle`/`DeviceUnassignedFromVehicle` carry `device_id` directly in their own
payload (their `aggregate_id` is the *assignment* id, not the device id — `fleet_device`'s own
`events.py` docstring: "Reassignment is an orchestration... performed by the application layer
across two DeviceAssignment aggregates"). `DeviceReassigned`'s `aggregate_id` *is* the device_id,
with `new_vehicle_id` in its payload.

**Authorization join condition — a decision this projection makes, not dictated by any single
document:** a device is considered *provisionable* (usable to authorize a vendor protocol
registration) only when `is_active` (has been `Activated`/`Reactivated`, not `Suspended`/
`Retired`) **and** `vehicle_id is not None` (assigned to a vehicle) — both are required because
every position-reporting handler in this deployable (`vendors.jt808.handlers.location_handler.
LocationHandler`, `vendors.lsz.handlers.position_handler.MdvrPositionHandler`) already requires a
resolved `vehicle_id` before it will publish anything; a device authorized without one would
create sessions no handler could ever use.

**`DeviceTerminalIdChanged` — a Founder/RAAD-staff correction of a mis-entered terminal ID after
registration (`backend/raad/modules/fleet_device/domain/entities.Device.update_terminal_id`).**
Before this event existed, nothing in this projection ever re-indexed `_device_id_by_terminal_id`
for an already-registered device — `terminal_id` was set exactly once, from `DeviceRegistered`'s
own payload, and never touched again by any other branch. A terminal ID corrected any other way
(most dangerously, a direct database edit bypassing this event entirely) leaves this projection
permanently unable to resolve the device under its corrected value, indefinitely, regardless of
`replay_from_start` — replay only ever reproduces the *original* `DeviceRegistered` event's
payload. `_apply_terminal_id_changed` below removes the stale index entry (not just adds the new
one) so a device is never resolvable under two terminal IDs at once.

**`auth_key_hashes` is a bounded list, not a single scalar (production fix, 2026-09-15).**
A real MDVR was observed, over a real production window, opening several overlapping TCP
connections for the *same* terminal within seconds of each other and re-sending `0x0100` on
each one before ever completing `0x0102` on the first — each fresh registration used to
overwrite this record's one `auth_key_hash` field unconditionally, so by the time the device
finally echoed back the code from its *own* connection's `0x8100`, that code had already been
silently invalidated by a sibling connection's later registration. `0x0102` then failed closed
every time, indefinitely, with no code-level error anywhere (`verify_auth_code` correctly
reports "wrong code," not a bug) — confirmed live: 19 registrations for one terminal in a 2-hour
production window, only 1 ever reached `0x0102`, and that one failed for exactly this reason.
Keeping the last `_MAX_PENDING_AUTH_KEY_HASHES` still-unconsumed hashes (oldest evicted first)
lets any of a terminal's own recently-issued codes still authenticate, regardless of how many
sibling registrations arrived in between — `verify_auth_code` removes a hash the instant it's
successfully used, so a spent code still can't be replayed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Generous headroom over the worst observed real burst (5 overlapping connections/registrations
#: for one terminal inside ~2.5 minutes) — small and bounded either way, since this only ever
#: holds short PBKDF2 hash strings for one device at a time.
_MAX_PENDING_AUTH_KEY_HASHES = 8


@dataclass
class DeviceRecord:
    device_id: str
    organization_id: str | None
    terminal_id: str | None
    serial_number: str | None
    is_active: bool
    vehicle_id: str | None
    #: ADR-0025 §3: hashes of the JT/T 808 `0x0102` credential(s), minted locally by
    #: `ProjectionBackedJt808ProvisioningPort.authorize_registration` on every successful
    #: `0x0100` (`fleet_device` never originates this value; the device-gateway process is the
    #: one that mints it) and appended here immediately, oldest evicted past
    #: `_MAX_PENDING_AUTH_KEY_HASHES`. Empty until a first successful registration mints one.
    #: Also fed by a replayed `DeviceAuthCodeIssued` broker event, the same as every other field
    #: on this record — `apply_event`'s own `DeviceAuthCodeIssued` branch — so
    #: `RedisDeviceRegistryConsumer.replay_from_start` recovers previously-minted hashes on a
    #: device-gateway restart instead of leaving every already-registered device permanently
    #: unable to complete `0x0102` (an *ordinary* reconnect, which does not resend `0x0100` —
    #: see `ProjectionBackedJt808ProvisioningPort`'s own docstring) short of a factory reset.
    auth_key_hashes: list[str] = field(default_factory=list)

    @property
    def is_provisionable(self) -> bool:
        return self.is_active and self.vehicle_id is not None

    def add_auth_key_hash(self, auth_key_hash: str) -> None:
        self.auth_key_hashes.append(auth_key_hash)
        del self.auth_key_hashes[:-_MAX_PENDING_AUTH_KEY_HASHES]


_ACTIVATING_EVENTS = {"DeviceActivated", "DeviceReactivated"}
_DEACTIVATING_EVENTS = {"DeviceSuspended", "DeviceRetired"}


class DeviceRegistryProjection:
    def __init__(self) -> None:
        self._by_device_id: dict[str, DeviceRecord] = {}
        self._device_id_by_terminal_id: dict[str, str] = {}
        self._device_id_by_serial_number: dict[str, str] = {}

    def apply_event(
        self, *, event_type: str, aggregate_id: str, org_id: str | None, payload: dict
    ) -> None:
        if event_type == "DeviceRegistered":
            self._apply_registered(aggregate_id=aggregate_id, org_id=org_id, payload=payload)
        elif event_type in _ACTIVATING_EVENTS:
            self._set_active(aggregate_id, True)
        elif event_type in _DEACTIVATING_EVENTS:
            self._set_active(aggregate_id, False)
        elif event_type in ("DeviceAssignedToVehicle", "DeviceUnassignedFromVehicle"):
            device_id = payload.get("device_id")
            if device_id:
                record = self._by_device_id.get(device_id)
                if record is not None:
                    record.vehicle_id = (
                        payload.get("vehicle_id")
                        if event_type == "DeviceAssignedToVehicle"
                        else None
                    )
        elif event_type == "DeviceReassigned":
            record = self._by_device_id.get(aggregate_id)
            if record is not None:
                record.vehicle_id = payload.get("new_vehicle_id")
        elif event_type == "DeviceTerminalIdChanged":
            self._apply_terminal_id_changed(aggregate_id=aggregate_id, payload=payload)
        elif event_type == "DeviceAuthCodeIssued":
            # P0 #2 fix: mirrors DeviceReassigned's shape immediately above -- aggregate_id is
            # the device_id for this event too (redis_event_publisher.py's own
            # aggregate_id=event.device_id choice). A record for a device this projection has
            # never seen DeviceRegistered for is silently ignored, same convention as every
            # other branch here (expected during a consumer's initial catch-up window).
            record = self._by_device_id.get(aggregate_id)
            if record is not None:
                auth_key_hash = payload.get("auth_key_hash")
                if auth_key_hash:
                    record.add_auth_key_hash(auth_key_hash)

    def _apply_registered(self, *, aggregate_id: str, org_id: str | None, payload: dict) -> None:
        terminal_id = payload.get("terminal_id")
        serial_number = payload.get("serial_number")
        record = DeviceRecord(
            device_id=aggregate_id,
            organization_id=org_id,
            terminal_id=terminal_id,
            serial_number=serial_number,
            is_active=False,
            vehicle_id=None,
        )
        self._by_device_id[aggregate_id] = record
        if terminal_id:
            self._device_id_by_terminal_id[terminal_id] = aggregate_id
        if serial_number:
            self._device_id_by_serial_number[serial_number] = aggregate_id

    def _apply_terminal_id_changed(self, *, aggregate_id: str, payload: dict) -> None:
        """Removes the stale `_device_id_by_terminal_id` entry (keyed on whatever
        `DeviceRegistered` originally carried, or a prior correction) and adds the corrected
        one — see this class's own module docstring for why simply adding the new key without
        removing the old one would leave a device resolvable under two terminal IDs at once.
        A record this projection has never seen `DeviceRegistered` for is silently ignored, the
        same convention every other branch in `apply_event` already follows (expected during a
        consumer's initial catch-up window, not an error)."""
        record = self._by_device_id.get(aggregate_id)
        if record is None:
            return
        old_terminal_id = payload.get("old_terminal_id")
        new_terminal_id = payload.get("new_terminal_id")
        if old_terminal_id and self._device_id_by_terminal_id.get(old_terminal_id) == aggregate_id:
            del self._device_id_by_terminal_id[old_terminal_id]
        record.terminal_id = new_terminal_id
        if new_terminal_id:
            self._device_id_by_terminal_id[new_terminal_id] = aggregate_id

    def _set_active(self, device_id: str, active: bool) -> None:
        record = self._by_device_id.get(device_id)
        if record is not None:
            record.is_active = active

    def lookup_by_terminal_id(self, terminal_id: str) -> DeviceRecord | None:
        device_id = self._device_id_by_terminal_id.get(terminal_id)
        return self._by_device_id.get(device_id) if device_id else None

    def lookup_by_serial_number(self, serial_number: str) -> DeviceRecord | None:
        device_id = self._device_id_by_serial_number.get(serial_number)
        return self._by_device_id.get(device_id) if device_id else None

    def __len__(self) -> int:
        return len(self._by_device_id)
