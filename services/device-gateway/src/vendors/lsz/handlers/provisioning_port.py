"""`MdvrDeviceProvisioningPort` — the vendor-protocol equivalent of `src.handlers.
provisioning_port.DeviceProvisioningPort`, deliberately **simpler**, not just renamed: this
vendor's registration message (`V101`) has no separate authentication step and no credential of
any kind to verify (`docs/vendor/HARDWARE_ANALYSIS.md` §11 — "no cryptographic authentication
mechanism of any kind is documented... registration validity is decided purely by whether the
submitted device serial number is already present in the center's own database"). There is
therefore no `verify_auth_code` method here at all — `authorize_registration` is the entire
contract, deciding accept/reject by serial-number allow-list only.

**This is an accepted, flagged security gap, not silently closed — and, per ADR-0015, it is not
"closed at the network layer" either.** `docs/architecture/adr/
0009-mdvr-vendor-protocol-device-plane.md`'s Consequences section originally framed this as a gap
that "must be closed at the network layer (mutual TLS / IP allow-listing / DMZ isolation)"; ADR-0015
(`docs/architecture/adr/0015-device-plane-authentication-trust-model.md`) supersedes that framing —
RAAD's device fleet runs over ordinary dynamic-IP public cellular by default, so an IP/network-layer
control cannot reliably identify a specific device in the first place, and is never assumed present.
The actual, accepted control is `authorize_registration`'s own **identity** check below (serial
number must resolve to an active, vehicle-assigned device in the real device-registry projection) —
flagged as identity-only, deliberately *not* a "secure device credential" in the cryptographic
sense `.claude/rules/security.md` #9 now describes as primary, since this hardware's firmware has
no credential mechanism to verify at all. No fake credential is invented here to paper over that.

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

from src.registry.device_registry_projection import DeviceRegistryProjection


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


class ProjectionBackedMdvrProvisioningPort(MdvrDeviceProvisioningPort):
    """The real, non-interim implementation (device-gateway Redis integration) — resolves a
    device serial number against the shared `registry.device_registry_projection.
    DeviceRegistryProjection`, kept current by `RedisDeviceRegistryConsumer` off the Business
    API's own `fleet_device` domain events. Replaces `InMemoryMdvrDeviceProvisioningPort` as
    `DeviceGateway`'s actual default whenever a broker is configured — see `gateway.py`.

    A device must be `is_provisionable` (`DeviceRegistryProjection.DeviceRecord`'s own join
    condition: active *and* assigned to a vehicle) to authorize — anything else (unknown serial
    number, registered-but-not-yet-activated, activated-but-unassigned, suspended, retired) is
    treated identically as `UNKNOWN_DEVICE`. This is a deliberate simplification: the vendor
    protocol itself has no distinct wire-level failure code for "known but not yet provisioned"
    versus "genuinely unknown" (`docs/vendor/HARDWARE_ANALYSIS.md` §10's own documented failure
    causes have no such distinction either), so collapsing them here invents nothing the protocol
    couldn't already express.
    """

    def __init__(self, projection: DeviceRegistryProjection) -> None:
        self._projection = projection

    async def authorize_registration(
        self, *, device_serial_number: str
    ) -> MdvrRegistrationAuthorization:
        record = self._projection.lookup_by_serial_number(device_serial_number)
        if record is None or not record.is_provisionable:
            return MdvrRegistrationAuthorization(result=MdvrRegistrationResult.UNKNOWN_DEVICE)
        return MdvrRegistrationAuthorization(
            result=MdvrRegistrationResult.SUCCESS,
            device_id=record.device_id,
            vehicle_id=record.vehicle_id,
            organization_id=record.organization_id,
        )
