"""Outbound ports the `video` application layer depends on (Backend LLD §4.2). `UnitOfWork` is
the existing core abstraction (`core.db.unit_of_work`), extended here with `video`'s own
repository, mirroring `billing.application.ports.BillingUnitOfWork` exactly.

**`VideoProviderPort` — originally an MVP hardware/vendor-API abstraction, now also the seam a
native JT1078 relay adapter implements (`infra/adapters.Jt1078RelayAdapter`, the JT1078
backend-integration phase).** It still names the three capabilities the documented routes need
(start a live stream, start a playback stream, stop a stream) without committing to *which*
provider answers them, the same "domain never sees a provider-specific field" Anti-Corruption-
Layer posture `billing.application.ports.PaymentProviderPort`'s own docstring already establishes
for EVC Plus.

**`terminal_id`/`channel_no` were added to `start_live`/`start_playback` (JT1078 backend-
integration phase) — a deliberate, minimal port evolution, not a breaking redesign**, mirroring
ADR-0022's own precedent for `PaymentProviderPort` ("the previous port was shaped entirely around
mobile money, with no way to carry a client-tokenized card `payment_method_id`"): the original
MVP-era signature had no way to express a JT/T 1078 signaling concept (which logical channel),
because no concrete implementation existed yet to reveal the gap. Both fields are resolved
**once**, by `api/routers.py`, from the same already-loaded `DeviceDTO`/`CameraDTO` the existing
camera-ownership check already reads — no new cross-module call, no second lookup inside the
adapter, and critically no scope-resolution ambiguity a *second*, adapter-internal
`fleet_device` call would otherwise raise (the router's own call already ran under the request's
real `TenantRegionScope`; the adapter has no request context of its own to re-derive one from).

`start_live`/`start_playback` return the provider's own stream URL/token — surfaced directly in
the API response (never persisted; `domain/entities.py`'s module docstring explains why
`VideoSession` itself carries no such column). `stop` returns nothing; a provider-side teardown
is fire-and-forget from this layer's perspective, mirroring `.claude/rules/jt1078.md` #4's "ports
are pooled and reclaimed on teardown" being the *provider's* responsibility, not this port
caller's — `stop` needs no `terminal_id`/`channel_no` since `Jt1078RelayAdapter.stop` only ever
needs `reference` (the relay's own session id) to tear a session down.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.video.domain.repositories import VideoSessionRepository


@dataclass(frozen=True)
class IntercomStreamUrls:
    """`start_intercom`'s own return shape (ADR-0036 §4) — deliberately not a single `str` like
    `start_live`/`start_playback`: an intercom session is bidirectional and needs two distinct
    URLs (the existing WS-FLV viewer contract, unchanged, for hearing the bus mic; a new,
    separately-tokened uplink WebSocket for sending the operator's own mic audio toward the
    device) — folding both into one `str` would either silently drop the uplink URL or force
    every ordinary live/playback caller to handle a return shape they never need."""

    downlink_url: str
    uplink_url: str


class VideoProviderPort(ABC):
    """Video provider abstraction (see module docstring) — `Jt1078RelayAdapter` is the one real
    implementation; the interface stays provider-agnostic in shape so a future non-native vendor
    API could still implement it too."""

    @abstractmethod
    async def start_live(
        self,
        *,
        device_id: str,
        camera_id: str,
        terminal_id: str,
        channel_no: int,
        reference: str,
        audio_codec: int | None = None,
    ) -> str:
        """Requests a live stream from the provider; returns a stream URL/token.

        `audio_codec` (added for the G.711A audio fix): the device's own real `0x1003`-reported
        `input_audio_codec` (`AudioCapability.codec`, ADR-0033) — the same narrow, additive
        `VideoProviderPort` widening precedent `terminal_id`/`channel_no` already established.
        `None` when the device has no captured `AudioCapability` yet; the relay's own explicit
        per-codec dispatch table treats that identically to any codec it hasn't implemented —
        no audio, video unaffected."""
        raise NotImplementedError

    @abstractmethod
    async def start_playback(
        self,
        *,
        device_id: str,
        camera_id: str,
        terminal_id: str,
        channel_no: int,
        window_start: datetime,
        window_end: datetime,
        reference: str,
        audio_codec: int | None = None,
    ) -> str:
        """Requests a playback stream for the given window; returns a stream URL/token. See
        `start_live`'s own docstring for `audio_codec`."""
        raise NotImplementedError

    @abstractmethod
    async def start_intercom(
        self,
        *,
        device_id: str,
        camera_id: str,
        terminal_id: str,
        channel_no: int,
        reference: str,
        audio_codec: int | None = None,
    ) -> IntercomStreamUrls:
        """Requests a two-way intercom session (ADR-0036). Signals the device with
        `data_type=2` (two-way intercom, spec Table 6.2) — distinct from `start_live`'s
        unchanged `data_type=0`. Returns both a downlink (hear the bus mic) and an uplink (send
        operator mic audio) URL."""
        raise NotImplementedError

    @abstractmethod
    async def stop(self, *, reference: str) -> None:
        """Tears down a previously started stream."""
        raise NotImplementedError


class VideoUnitOfWork(UnitOfWork):
    """Bundles this module's one repository onto one transaction boundary, mirroring
    `BillingUnitOfWork`'s identical shape. The concrete implementation is
    `infra.repositories.SqlAlchemyVideoUnitOfWork`.
    """

    video_sessions: VideoSessionRepository
