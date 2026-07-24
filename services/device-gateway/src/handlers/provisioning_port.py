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

if TYPE_CHECKING:
    from src.handlers.registration_body import RegistrationRequest


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
    auth_code: str | None = None  # present only when result == SUCCESS, §8.6
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
