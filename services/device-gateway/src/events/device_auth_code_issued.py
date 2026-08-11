"""`DeviceAuthCodeIssued` — ADR-0025 §3's auth-code lifecycle, the durability half. Published by
`TerminalRegistrationHandler` whenever `DeviceProvisioningPort.authorize_registration` mints a
fresh `0x0102` credential, so `fleet_device`'s own `Device.auth_key_hash` column (previously
always `None`, per that column's own docstring) stays a durable mirror of the hash the
device-gateway process actually verifies against. Carries the **hash only, never the plaintext
code** — the plaintext is embedded once in the `0x8100` wire response to the terminal itself and
is never otherwise transmitted, logged, or persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DeviceAuthCodeIssued:
    terminal_id: str
    organization_id: str | None
    vehicle_id: str | None
    device_id: str
    auth_key_hash: str
    event_time: datetime
    received_at: datetime
