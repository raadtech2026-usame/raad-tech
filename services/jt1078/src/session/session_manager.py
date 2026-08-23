"""`SessionManager` — the relay's own Video Session Manager (VSM, ADR-0024 §5). Owns
`VideoSession` lifecycle end to end: creation (`REQUESTED`), activation on first ingested frame
(`ACTIVE`), viewer join/leave, idle-timeout teardown, explicit stop, and the resulting
`VideoSessionActivated`/`VideoSessionEnded`/`VideoSessionFailed` events + device stop-signal
command (ADR-0024 §5 point 4).

**Correlates an inbound ingest connection to a session by `terminal_id` *and* `logical_channel`**
— the JT/T 1078 media socket itself carries no session token (ADR-0024 §1: "the relay's own
correctness anchor for *that* socket remains identity/session correlation... never by trusting
the connection's source IP alone"). `resolve_ingest_by_terminal_id` only ever returns a session in
`REQUESTED` or `ACTIVE` state — an `ENDED`/`FAILED` session (or one this manager never created)
correlates to nothing, so a stray/unsolicited media connection is rejected by the caller
(`ingest/ingest_server.py`), not silently accepted.

**A real, live-found bug (2026-08-22, physical bench unit, multi-camera grid): matching by
`terminal_id` alone is only correct when at most one session is ever `REQUESTED`/`ACTIVE` for a
given device at a time.** ADR-0030's multi-camera grid (`MultiCameraVideoPanel`) requests all of a
device's cameras' sessions simultaneously — up to four `REQUESTED` sessions sharing the *same*
`terminal_id`, distinguished only by `logical_channel`. `ExtendedRtpFrame` already carries its own
`logical_channel` (`ingest/extended_rtp.py`, spec Table 5.31, byte 14) on every single frame, but
the previous terminal-id-only match ignored it and returned whichever same-device session
happened to be first in `self._sessions`' iteration order — non-deterministic, tied to RPC
processing order, not to which channel a given ingest connection was actually for. Confirmed
live: the physical MDVR genuinely opens one independent ingest TCP connection per requested
channel (four simultaneous connections observed on the ingest port for a 4-camera Start Live),
but all four could resolve to the *same* session, interleaving frames from multiple physical
channels into one broadcast hub while the other sessions' own real ingest connections went
unattributed and later failed on `ingest_timeout` — exactly matching the observed "1/4 Live, and
which camera is Live changes between attempts" symptom. Matching on `logical_channel` too (already
present on every frame, already stored on every `VideoSession` at creation) makes each of a
device's concurrently-pending sessions resolvable only by its own channel's ingest connection.

**`on_session_created`/`on_session_removed`** — sync hooks `relay.py`'s composition root uses to
keep its own `session_id -> SessionBroadcastHub` dict in lockstep with session lifecycle (a hub
must exist the moment a session is `REQUESTED`, so a viewer's token can be honored even before the
device's first frame arrives, and must be torn down the instant the session is). Kept as plain
sync callables, not events on the broker — this is in-process coordination between two objects
this composition root owns directly, not a cross-service fact.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

from src.events.publisher_port import SessionEventPublisher
from src.events.session_events import VideoSessionActivated, VideoSessionEnded, VideoSessionFailed
from src.session.video_session import VideoSession, VideoSessionKind, VideoSessionState, new_session_id

DEFAULT_VIEWER_GRACE_SECONDS = 15.0
DEFAULT_ABSOLUTE_IDLE_SECONDS = 60.0
DEFAULT_INGEST_TIMEOUT_SECONDS = 30.0
#: ADR-0026 §8, citing `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §13.1's own
#: "Concurrent live video streams | Hard ceiling per org + global (e.g., start 50 global)" - the
#: one concrete number an approved document names. No per-org number is given anywhere, so that
#: ceiling defaults to unconfigured (`None`, no additional restriction) rather than inventing one.
DEFAULT_MAX_GLOBAL_SESSIONS = 50

OnSessionCreated = Callable[[VideoSession], None]
OnSessionRemoved = Callable[[str], None]


class SessionCapacityExceededError(Exception):
    """Raised by `SessionManager.create_session` when either ceiling (§ constructor docstring)
    is exceeded. `SessionRequestServer._process_one`'s existing generic exception handling
    already turns this into `{"ok": false, "error": str(exc)}` with no new plumbing needed —
    which `Jt1078RelayRpcClient.call` (Business API) already turns into `Jt1078RelayError`,
    propagating uncaught through `VideoApplicationService` exactly as every other unbound-
    provider/relay failure already does (ADR-0026 §8)."""


def _default_on_session_created(_session: VideoSession) -> None:
    return None


def _default_on_session_removed(_session_id: str) -> None:
    return None


def _terminal_id_matches_sim_card_number(terminal_id: str, sim_card_number: str) -> bool:
    """**A real, live-found bug (2026-08-19, physical `LSZ-C5804DG-Q-F` bench unit):** JT/T
    1078's own extended-RTP ingest frame carries only a `BCD[6]` (12 hex-digit) SIM card number
    (`ingest/extended_rtp.py` §6.2.1.1 Table 6.3) - narrower than JT/T 808-2019's own `BCD[10]`
    (20 hex-digit) terminal-phone field (ADR-0025 §2) `VideoSession.terminal_id` is keyed by.
    They are the *same* underlying SIM/phone number, right-justified and zero-padded to the
    wider field, per JT/T 808's own convention - confirmed live, not assumed: a real
    `terminal_id` of `00000000014482607571`'s own trailing 12 characters are exactly the ingest
    frame's own `014482607571`. `resolve_ingest_by_terminal_id`'s previous exact `==` comparison
    between the two could therefore never match: the device correctly dialed this relay's own
    ingest port (once `JT1078_RELAY_PUBLIC_INGEST_HOST` was also fixed, a separate gap found the
    same session) and sent valid extended-RTP frames, every single one rejected as
    `unsolicited_ingest_connection_rejected` regardless."""
    return (
        len(terminal_id) >= len(sim_card_number)
        and terminal_id[-len(sim_card_number) :] == sim_card_number
    )


class SessionManager:
    def __init__(
        self,
        *,
        event_publisher: SessionEventPublisher,
        viewer_grace_seconds: float = DEFAULT_VIEWER_GRACE_SECONDS,
        absolute_idle_seconds: float = DEFAULT_ABSOLUTE_IDLE_SECONDS,
        ingest_timeout_seconds: float = DEFAULT_INGEST_TIMEOUT_SECONDS,
        max_global_sessions: int | None = DEFAULT_MAX_GLOBAL_SESSIONS,
        max_sessions_per_organization: int | None = None,
        on_session_created: OnSessionCreated | None = None,
        on_session_removed: OnSessionRemoved | None = None,
    ) -> None:
        """`max_global_sessions`/`max_sessions_per_organization` (ADR-0026 §8): `None` or any
        value `<= 0` means "no ceiling" for that dimension — the two are independent, both
        checked, either alone can reject a request."""
        self._event_publisher = event_publisher
        self._viewer_grace_seconds = viewer_grace_seconds
        self._absolute_idle_seconds = absolute_idle_seconds
        self._ingest_timeout_seconds = ingest_timeout_seconds
        self._max_global_sessions = max_global_sessions
        self._max_sessions_per_organization = max_sessions_per_organization
        self._on_session_created = on_session_created or _default_on_session_created
        self._on_session_removed = on_session_removed or _default_on_session_removed
        self._sessions: dict[str, VideoSession] = {}

    def create_session(
        self,
        *,
        terminal_id: str,
        kind: VideoSessionKind,
        correlation_id: str,
        logical_channel: int,
        device_id: str | None = None,
        vehicle_id: str | None = None,
        organization_id: str | None = None,
        session_id: str | None = None,
    ) -> VideoSession:
        """`session_id` is optional and defaults to a fresh id (`new_session_id()`) — a caller
        that already has its own correlation identity (the Business API's `SessionRequestServer`
        adapter, pinning this relay's own session to the Business API's `VideoSession.id` so one
        id traces the whole request end to end) may pass it in instead of letting this manager
        mint an unrelated second one.

        Raises `SessionCapacityExceededError` (ADR-0026 §8) if creating this session would
        exceed either the global ceiling or `organization_id`'s own per-org ceiling — checked
        *before* the session is created, so a rejected request never partially allocates
        anything. An `organization_id`-less caller is only ever subject to the global ceiling."""
        if (
            self._max_global_sessions is not None
            and self._max_global_sessions > 0
            and self.active_session_count >= self._max_global_sessions
        ):
            raise SessionCapacityExceededError(
                f"Global concurrent-session ceiling reached ({self._max_global_sessions})."
            )
        if (
            organization_id is not None
            and self._max_sessions_per_organization is not None
            and self._max_sessions_per_organization > 0
            and self._count_for_organization(organization_id)
            >= self._max_sessions_per_organization
        ):
            raise SessionCapacityExceededError(
                f"Organization {organization_id!r} concurrent-session ceiling reached "
                f"({self._max_sessions_per_organization})."
            )

        session = VideoSession(
            session_id=session_id or new_session_id(),
            terminal_id=terminal_id,
            kind=kind,
            device_id=device_id,
            vehicle_id=vehicle_id,
            organization_id=organization_id,
            correlation_id=correlation_id,
            logical_channel=logical_channel,
        )
        self._sessions[session.session_id] = session
        self._on_session_created(session)
        return session

    def _count_for_organization(self, organization_id: str) -> int:
        return sum(
            1
            for session in self._sessions.values()
            if session.organization_id == organization_id
        )

    def resolve(self, session_id: str) -> VideoSession | None:
        return self._sessions.get(session_id)

    def resolve_ingest_by_terminal_id(
        self, sim_card_number: str, logical_channel: int
    ) -> VideoSession | None:
        """Despite the parameter's own historical name (kept for `ingest_server.py`'s existing
        call-site compatibility), `sim_card_number` actually receives the ingest frame's `BCD[6]`
        SIM card number, not the wider `BCD[10]` `terminal_id` - see
        `_terminal_id_matches_sim_card_number` for why the two need width-aware matching, not
        `==`. `logical_channel` disambiguates between a device's own multiple concurrently-pending
        sessions (module docstring) - required, not optional, since a single-field terminal-id
        match is silently wrong the instant more than one session is pending for the same device."""
        for session in self._sessions.values():
            if (
                _terminal_id_matches_sim_card_number(session.terminal_id, sim_card_number)
                and session.logical_channel == logical_channel
                and session.state in (VideoSessionState.REQUESTED, VideoSessionState.ACTIVE)
            ):
                return session
        return None

    async def mark_ingest_active(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None or session.state == VideoSessionState.ACTIVE:
            return
        was_requested = session.state == VideoSessionState.REQUESTED
        session.activate()
        if was_requested:
            await self._event_publisher.publish(
                VideoSessionActivated(
                    session_id=session.session_id,
                    terminal_id=session.terminal_id,
                    organization_id=session.organization_id,
                    vehicle_id=session.vehicle_id,
                    device_id=session.device_id,
                    correlation_id=session.correlation_id,
                    event_time=datetime.now(timezone.utc),
                )
            )

    def touch_ingest(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.touch()

    def add_viewer(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.add_viewer()

    def remove_viewer(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.remove_viewer()

    async def end_session(self, session_id: str, *, reason: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        self._on_session_removed(session_id)
        await self._signal_device_stop(session)
        await self._event_publisher.publish(
            VideoSessionEnded(
                session_id=session.session_id,
                terminal_id=session.terminal_id,
                organization_id=session.organization_id,
                vehicle_id=session.vehicle_id,
                device_id=session.device_id,
                correlation_id=session.correlation_id,
                reason=reason,
                event_time=datetime.now(timezone.utc),
            )
        )

    async def fail_session(self, session_id: str, *, reason: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        self._on_session_removed(session_id)
        await self._event_publisher.publish(
            VideoSessionFailed(
                session_id=session.session_id,
                terminal_id=session.terminal_id,
                organization_id=session.organization_id,
                vehicle_id=session.vehicle_id,
                device_id=session.device_id,
                correlation_id=session.correlation_id,
                reason=reason,
                event_time=datetime.now(timezone.utc),
            )
        )

    async def _signal_device_stop(self, session: VideoSession) -> None:
        """ADR-0024 §5 point 4: the relay itself signals the device to stop, via the same
        `Jt1078SignalCommandRequested` coordination path `device-gateway`'s
        `RedisVideoSignalingConsumer` already consumes from the Business API (`events/
        publisher_port.py`'s own module docstring has the full reasoning)."""
        if session.kind == VideoSessionKind.LIVE:
            command, fields = "live_video_control", {
                "logical_channel": session.logical_channel,
                "control": 0,  # close A/V transmission, Table 6.4
            }
        else:
            command, fields = "playback_control", {
                "av_channel": session.logical_channel,
                "control": 2,  # end playback, Table 6.11
            }
        await self._event_publisher.publish_stop_command(
            terminal_id=session.terminal_id,
            correlation_id=session.correlation_id,
            command=command,
            fields=fields,
        )

    async def sweep_idle_sessions(self) -> list[str]:
        """Called periodically by the relay's own composition root (mirrors `device-gateway`'s
        `DeviceSessionManager._sweep_loop` shape) — ends every session past its own idle bound
        (`VideoSession.is_idle_past`, ADR-0024 §5 point 3's two independent conditions) or its
        ingest timeout (still `REQUESTED`, the device never connected within
        `ingest_timeout_seconds` — ADR-0024 §16's "the relay's own allocation times out"). Returns
        the ended/failed session ids, mainly for test observability."""
        acted_on: list[str] = []
        for session_id, session in list(self._sessions.items()):
            if session.state == VideoSessionState.REQUESTED:
                if time.monotonic() - session.created_at > self._ingest_timeout_seconds:
                    await self.fail_session(session_id, reason="ingest_timeout")
                    acted_on.append(session_id)
                continue
            if session.state == VideoSessionState.ACTIVE and session.is_idle_past(
                viewer_grace_seconds=self._viewer_grace_seconds,
                absolute_idle_seconds=self._absolute_idle_seconds,
            ):
                await self.end_session(session_id, reason="viewer_idle_timeout")
                acted_on.append(session_id)
        return acted_on

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)
