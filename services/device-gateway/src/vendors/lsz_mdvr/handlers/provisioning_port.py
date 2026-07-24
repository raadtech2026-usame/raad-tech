"""`MdvrDeviceProvisioningPort` — the vendor-protocol equivalent of `src.handlers.
provisioning_port.DeviceProvisioningPort`, deliberately **simpler**, not just renamed: this
vendor's registration message (`V101`) has no separate authentication step and no credential of
any kind to verify (`docs/vendor/HARDWARE_ANALYSIS.md` §11 — "no cryptographic authentication
mechanism of any kind is documented... registration validity is decided purely by whether the
submitted device serial number is already present in the center's own database"). There is
therefore no `verify_auth_code` method here at all — `authorize_registration` is the entire
contract, deciding accept/reject by serial-number allow-list only.

**This is an accepted, flagged security gap, not silently closed** — `docs/architecture/adr/
0009-mdvr-vendor-protocol-device-plane.md`'s Consequences section records it explicitly: the
missing cryptographic assurance must be closed at the network layer (mutual TLS / IP allow-listing
/ DMZ isolation, `.claude/rules/security.md` #9), not invented here as a fake credential this
hardware doesn't actually support.

**No real device-registry projection is implemented in this phase.** The roadmap's revised B1 asks
for a local projection kept current by consuming `fleet_device`'s `DeviceRegistered`/
`DeviceActivated`/`DeviceAssignedToVehicle` domain events over the broker — that requires a bound
`BrokerConsumer`, which itself requires a Redis client dependency for this deployable that has not
yet been proposed/approved (`.claude/rules/workflow.md` #1/#2; `pyproject.toml`'s own comment
already anticipates exactly this checkpoint). `InMemoryMdvrDeviceProvisioningPort` below is a
directly-testable, explicitly-interim stand-in — a plain allow-list populated by whoever
constructs it (a test, or a manual ops script) — not that projection. The real, broker-driven
projection is follow-up work, tracked, not silently substituted.

**Default binding (`NullMdvrDeviceProvisioningPort`):** fail-closed, mirroring the parent
package's `NullDeviceProvisioningPort` exactly — every registration is "unknown device" until a
real implementation is wired.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class MdvrRegistrationResult(str, Enum):
    """Mapped to this vendor's own documented `V101` failure-cause codes (`docs/vendor/
    HARDWARE_ANALYSIS.md` §10) where a code exists; `UNKNOWN_DEVICE` is the only rejection reason
    this port can actually determine (code 2, "Illegal Car Serial Number") — codes 1/3/4/5
    (format error, server-address mismatch, protocol-version mismatch, unsupported device type)
    are protocol/transport-level concerns this port has no basis to evaluate and are not
    represented here."""

    SUCCESS = "success"
    UNKNOWN_DEVICE = "unknown_device"


@dataclass(frozen=True)
class MdvrRegistrationAuthorization:
    result: MdvrRegistrationResult
    device_id: str | None = None
    vehicle_id: str | None = None
    organization_id: str | None = None


class MdvrDeviceProvisioningPort(ABC):
    @abstractmethod
    async def authorize_registration(
        self, *, device_serial_number: str
    ) -> MdvrRegistrationAuthorization:
        raise NotImplementedError


class NullMdvrDeviceProvisioningPort(MdvrDeviceProvisioningPort):
    """Fail-closed default — see module docstring."""

    async def authorize_registration(
        self, *, device_serial_number: str
    ) -> MdvrRegistrationAuthorization:
        return MdvrRegistrationAuthorization(result=MdvrRegistrationResult.UNKNOWN_DEVICE)


class InMemoryMdvrDeviceProvisioningPort(MdvrDeviceProvisioningPort):
    """Explicitly-interim allow-list — see module docstring. Not wired as any default; a caller
    (test, manual verification script) populates it via `register_known_device` and passes it to
    `Jt808MdvrServer` explicitly."""

    def __init__(self) -> None:
        self._devices: dict[str, MdvrRegistrationAuthorization] = {}

    def register_known_device(
        self,
        *,
        device_serial_number: str,
        device_id: str,
        vehicle_id: str,
        organization_id: str,
    ) -> None:
        self._devices[device_serial_number] = MdvrRegistrationAuthorization(
            result=MdvrRegistrationResult.SUCCESS,
            device_id=device_id,
            vehicle_id=vehicle_id,
            organization_id=organization_id,
        )

    async def authorize_registration(
        self, *, device_serial_number: str
    ) -> MdvrRegistrationAuthorization:
        return self._devices.get(
            device_serial_number,
            MdvrRegistrationAuthorization(result=MdvrRegistrationResult.UNKNOWN_DEVICE),
        )
