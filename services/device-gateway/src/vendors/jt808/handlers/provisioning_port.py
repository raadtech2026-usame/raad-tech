"""`DeviceProvisioningPort` (Phase 9.5) — the seam between protocol-level registration/
authentication handling and whatever actually decides "is this a known device, and is its
auth code correct." No concrete implementation exists this phase (no Database, no Fleet
Device integration, no Redis — all explicitly out of Phase 9.5's scope); per the task's own
architecture requirement, "if future persistence is required, use ports/interfaces only."

**Flagged, unresolved documentation conflict (confirmed with the user before implementing —
resolved by keeping this port semantically neutral rather than committing to either reading):**

- JT808 Technical Design §4 (verbatim): "Provisioning: during Device Management onboarding...,
  a device is registered with a `terminal_id` and an auth secret. ... Authentication (`0x0102`):
  the presented auth code is verified against `auth_key_hash`." Reads as: the device already
  holds a *static, pre-provisioned secret* set at onboarding, independent of any TCP session.

- JT/T 808-2013 primary spec (§8.6 Table 8, §8.8 Table 9, §21.1 sequence diagram, verbatim):
  the registration response (`0x8100`) body's `鉴权码` (auth code) is *"只有在成功后才有该字段"*
  ("present only on success" — i.e. something the *platform* supplies); the authentication
  (`0x0102`) body's `鉴权码` is described as *"终端重连后上报鉴权码"* ("the auth code the
  terminal reports after reconnecting"); the sequence diagram shows the platform *issuing* the
  code in `0x8100`, the device *echoing* it in `0x0102`. Reads as: the code *originates from
  the platform at registration*, not a secret the device already held.

- Backend LLD adds a third data point ("a short-lived session auth token is issued, held in
  Redis; token rotation on reconnect") that doesn't cleanly map to either reading alone.

This port does not decide which model is correct. `authorize_registration` returns whatever
opaque `auth_code` string should be embedded in `0x8100` — whether that string is a stored
secret, a freshly minted token, or something else is entirely the concrete implementation's
business (a later phase, built with real device-provisioning-workflow context).
`verify_auth_code` similarly just answers "is this correct," never exposing *how*.

**Default binding (`NullDeviceProvisioningPort`):** fail-closed, not fail-open — every
registration is "terminal not found," every auth code is invalid. A device-plane service that
silently accepted every device by default (because no port was wired) would be a severe
security hole; `server.py`'s composition root only swaps this for a real implementation once
one exists, matching the "fail loudly, don't fake it" policy the Business API's own DI
container already applies to unconfigured ports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from src.registry.device_registry_projection import DeviceRegistryProjection
from src.vendors.jt808.handlers.auth_code_hashing import (
    generate_code,
    hash_code,
    verify_code,
)

if TYPE_CHECKING:
    from src.vendors.jt808.handlers.registration_body import RegistrationRequest


class RegistrationResult(str, Enum):
    """JT/T 808-2013 §8.6 Table 8's result codes, verbatim (0-4) — the closed set `0x8100`
    can express. No "malformed body" or "message error" code exists in this set (that concept
    only exists on the general response, `0x8001`) — a registration body that cannot even be
    parsed is not this enum's job to represent, see `registration_handler.py`."""

    SUCCESS = "success"  # 0: 成功
    VEHICLE_ALREADY_REGISTERED = "vehicle_already_registered"  # 1: 车辆已被注册
    VEHICLE_NOT_FOUND = "vehicle_not_found"  # 2: 数据库中无该车辆
    TERMINAL_ALREADY_REGISTERED = "terminal_already_registered"  # 3: 终端已被注册
    TERMINAL_NOT_FOUND = "terminal_not_found"  # 4: 数据库中无该终端


@dataclass(frozen=True)
class RegistrationAuthorization:
    result: RegistrationResult
    auth_code: str | None = None  # present only when result == SUCCESS, §8.6 — plaintext, wire-bound
    auth_key_hash: str | None = None  # ADR-0025 §3 — the hash to persist to Device.auth_key_hash
    device_id: str | None = None
    vehicle_id: str | None = None
    organization_id: str | None = None


@dataclass(frozen=True)
class AuthenticationResult:
    is_valid: bool
    device_id: str | None = None
    vehicle_id: str | None = None
    organization_id: str | None = None


class DeviceProvisioningPort(ABC):
    @abstractmethod
    async def authorize_registration(
        self, *, terminal_phone: str, request: "RegistrationRequest"
    ) -> RegistrationAuthorization:
        raise NotImplementedError

    @abstractmethod
    async def verify_auth_code(
        self, *, terminal_phone: str, auth_code: str
    ) -> AuthenticationResult:
        raise NotImplementedError


class NullDeviceProvisioningPort(DeviceProvisioningPort):
    """Fail-closed default — see module docstring."""

    async def authorize_registration(
        self, *, terminal_phone: str, request: "RegistrationRequest"
    ) -> RegistrationAuthorization:
        return RegistrationAuthorization(result=RegistrationResult.TERMINAL_NOT_FOUND)

    async def verify_auth_code(
        self, *, terminal_phone: str, auth_code: str
    ) -> AuthenticationResult:
        return AuthenticationResult(is_valid=False)


class ProjectionBackedJt808ProvisioningPort(DeviceProvisioningPort):
    """The real, non-interim implementation of the *identity/provisioning* half of this port —
    resolves a JT/T 808 terminal phone (`InboundMessage.terminal_id`, header `BCD[10]` per the
    2019 field-width rework, ADR-0025 §2 — the only field this codebase ever uses for identity;
    see `registration_body.py`'s own docstring on
    why the body's separate `manufacturer_terminal_id` is parsed but not used for lookup) against
    the shared `registry.device_registry_projection.DeviceRegistryProjection` — the same
    vendor-agnostic projection `vendors.lsz.handlers.provisioning_port.
    ProjectionBackedMdvrProvisioningPort` already resolves LSZ serial numbers against
    (`DeviceRegistryProjection` has always indexed by both `terminal_id` and `serial_number` for
    exactly this reason). Replaces `NullDeviceProvisioningPort` as `DeviceGateway`'s actual
    default for JT808 whenever a broker is configured — see `gateway.py`.

    A device must be `is_provisionable` (`DeviceRegistryProjection.DeviceRecord`'s own join
    condition: active *and* assigned to a vehicle) to authorize — anything else (unknown
    terminal_id, registered-but-not-yet-activated, activated-but-unassigned, suspended, retired)
    collapses to `RegistrationResult.TERMINAL_NOT_FOUND` — the one JT/T 808-2013 §8.6 result code
    this port has a basis to return; the other three rejection codes (`VEHICLE_ALREADY_
    REGISTERED`/`VEHICLE_NOT_FOUND`/`TERMINAL_ALREADY_REGISTERED`) describe conditions this
    projection cannot evaluate. This mirrors `ProjectionBackedMdvrProvisioningPort`'s own
    identical "collapse to the one code this port can actually determine" precedent exactly.

    **`0x0102` auth-code lifecycle now implemented per ADR-0025 §3** (the three-way conflict this
    module's own docstring used to flag — JT808 Technical Design's device-held-static-secret
    reading, the primary spec's platform-issued-code reading, Backend LLD's Redis-rotating-token
    reading — is resolved by that ADR in favor of the platform-issued/echoed-back model,
    corroborated directly by the new supplier specification's own §5.1.6/§5.1.7/§7.1.1/§7.1.2):
    `authorize_registration` mints a fresh, cryptographically random code
    (`auth_code_hashing.generate_code`) on every `SUCCESS` result, hashes it
    (`auth_code_hashing.hash_code`, PBKDF2-HMAC-SHA256) into the projection record's own
    `auth_key_hash` field — the *local*, in-process copy this port's `verify_auth_code` checks
    against, matching `Device.auth_key_hash`'s own docstring ("device authentication happens in
    the JT808 service against the device-registry projection," not against Postgres directly).
    The plaintext code is returned once, embedded in `0x8100`'s wire response
    (`RegistrationAuthorization.auth_code`); the hash is returned too
    (`RegistrationAuthorization.auth_key_hash`) so the calling handler can publish a
    `DeviceAuthCodeIssued` event, letting `fleet_device`'s own `Device.auth_key_hash` column stay
    a durable mirror of this record (`events/subscribers.py`-side, backend). **Every successful
    `0x0100` mints a brand-new code, unconditionally** — this is the literal reading of ADR-0025
    §3's "rotates only on a fresh, successful `0x0100` registration": a normal reconnect never
    resends `0x0100` at all under the 2019 spec's own §3.5.3 semantics (echoes the previously
    issued code straight to `0x0102`), so any `0x0100` this port sees again *is* by definition a
    fresh registration (e.g. a factory reset) — no extra "is this the first time" state is
    tracked, since ADR-0025 §3 defines none.

    `verify_auth_code` hashes the presented code with the same algorithm and compares it
    (`hmac.compare_digest`, inside `auth_code_hashing.verify_code`) against the projection
    record's stored `auth_key_hash` — a terminal with no record, an unprovisionable record, or no
    `auth_key_hash` yet minted (never registered through this port) all fail closed.
    """

    def __init__(self, projection: DeviceRegistryProjection) -> None:
        self._projection = projection

    async def authorize_registration(
        self, *, terminal_phone: str, request: "RegistrationRequest"
    ) -> RegistrationAuthorization:
        record = self._projection.lookup_by_terminal_id(terminal_phone)
        if record is None or not record.is_provisionable:
            return RegistrationAuthorization(result=RegistrationResult.TERMINAL_NOT_FOUND)

        auth_code = generate_code()
        auth_key_hash = hash_code(auth_code)
        record.auth_key_hash = auth_key_hash

        return RegistrationAuthorization(
            result=RegistrationResult.SUCCESS,
            auth_code=auth_code,
            auth_key_hash=auth_key_hash,
            device_id=record.device_id,
            vehicle_id=record.vehicle_id,
            organization_id=record.organization_id,
        )

    async def verify_auth_code(
        self, *, terminal_phone: str, auth_code: str
    ) -> AuthenticationResult:
        record = self._projection.lookup_by_terminal_id(terminal_phone)
        if record is None or not record.is_provisionable or record.auth_key_hash is None:
            return AuthenticationResult(is_valid=False)

        if not verify_code(auth_code, record.auth_key_hash):
            return AuthenticationResult(is_valid=False)

        return AuthenticationResult(
            is_valid=True,
            device_id=record.device_id,
            vehicle_id=record.vehicle_id,
            organization_id=record.organization_id,
        )
