"""`SessionManager` tests (`session/session_manager.py`) — lifecycle, viewer counting, idle
teardown, and the device stop-signal publish, all against a recording fake publisher."""

import unittest

from src.events.session_events import VideoSessionActivated, VideoSessionEnded, VideoSessionFailed
from src.session.session_manager import SessionCapacityExceededError, SessionManager
from src.session.video_session import VideoSessionKind, VideoSessionState


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[object] = []
        self.stop_commands: list[dict] = []

    async def publish(self, event) -> None:
        self.published.append(event)

    async def publish_stop_command(self, *, terminal_id, correlation_id, command, fields) -> None:
        self.stop_commands.append(
            {
                "terminal_id": terminal_id,
                "correlation_id": correlation_id,
                "command": command,
                "fields": fields,
            }
        )


def _manager(**kwargs) -> tuple[SessionManager, RecordingPublisher]:
    publisher = RecordingPublisher()
    manager = SessionManager(event_publisher=publisher, **kwargs)
    return manager, publisher


class SessionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_session_starts_requested(self) -> None:
        manager, _ = _manager()
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        self.assertEqual(session.state, VideoSessionState.REQUESTED)
        self.assertEqual(manager.resolve(session.session_id), session)

    async def test_create_session_defaults_audio_codec_to_none(self) -> None:
        manager, _ = _manager()
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        self.assertIsNone(session.audio_codec)

    async def test_create_session_stores_the_given_audio_codec(self) -> None:
        manager, _ = _manager()
        session = manager.create_session(
            terminal_id="T1",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-1",
            logical_channel=1,
            audio_codec=6,
        )
        self.assertEqual(session.audio_codec, 6)

    async def test_resolve_ingest_by_terminal_id_finds_a_requested_session(self) -> None:
        manager, _ = _manager()
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        found = manager.resolve_ingest_by_terminal_id("T1", 1)
        self.assertEqual(found.session_id, session.session_id)

    async def test_resolve_ingest_by_terminal_id_returns_none_for_unsolicited_terminal(
        self,
    ) -> None:
        manager, _ = _manager()
        manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        self.assertIsNone(manager.resolve_ingest_by_terminal_id("some-other-terminal", 1))

    async def test_resolve_ingest_by_terminal_id_disambiguates_a_devices_own_concurrent_sessions(
        self,
    ) -> None:
        """Regression test for a real, live-found bug (2026-08-22, physical bench unit,
        multi-camera grid): four cameras on one device are live-requested simultaneously, giving
        four `REQUESTED` sessions that share the same `terminal_id` and differ only by
        `logical_channel`. Matching by `terminal_id` alone (the previous behavior) returned
        whichever same-device session happened to be first in iteration order, regardless of
        which channel a given ingest connection's own frames were actually for — confirmed live:
        the device opened four independent, simultaneous ingest connections, but every one of
        them resolved to the same one session."""
        manager, _ = _manager()
        sessions = [
            manager.create_session(
                terminal_id="T1",
                kind=VideoSessionKind.LIVE,
                correlation_id=f"corr-{channel}",
                logical_channel=channel,
            )
            for channel in (1, 2, 3, 4)
        ]

        for channel, session in zip((1, 2, 3, 4), sessions):
            found = manager.resolve_ingest_by_terminal_id("T1", channel)
            self.assertEqual(
                found.session_id,
                session.session_id,
                f"channel {channel}'s ingest frame resolved to the wrong session",
            )

    async def test_resolve_ingest_by_terminal_id_prefers_intercom_for_an_audio_frame_on_a_shared_channel(
        self,
    ) -> None:
        """Bug 2 regression test — a real, live-reproduced production scenario: an operator is
        viewing a device's live multi-camera grid (LIVE session already `ACTIVE` on channel 1)
        while another operator starts "Talk to Driver" against that same device's first camera
        (INTERCOM session `REQUESTED` on the identical channel 1, ADR-0036 §6's own default). Both
        share `(terminal_id, logical_channel)`, so the pre-fix first-match-wins behavior would
        always resolve a genuine intercom audio connection to the *already-inserted* LIVE session
        instead — silently starving the intercom session until it hit `ingest_timeout`, exactly
        the symptom production session `01M1EQZE1D1831D74MHXCTDGQP` exhibited (a concurrently
        `ACTIVE` LIVE session on the identical camera/channel was confirmed in the DB at the exact
        moment that intercom session failed)."""
        manager, _ = _manager()
        live_session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-live", logical_channel=1
        )
        await manager.mark_ingest_active(live_session.session_id)
        intercom_session = manager.create_session(
            terminal_id="T1",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="corr-intercom",
            logical_channel=1,
        )

        found = manager.resolve_ingest_by_terminal_id("T1", 1, is_audio=True)

        self.assertEqual(found.session_id, intercom_session.session_id)

    async def test_resolve_ingest_by_terminal_id_prefers_live_for_a_video_frame_on_a_shared_channel(
        self,
    ) -> None:
        """The reverse direction of the fix above — a video frame on a channel that has both a
        pending LIVE and a pending INTERCOM session must still resolve to the LIVE session, never
        get mis-attributed to the audio-only intercom call."""
        manager, _ = _manager()
        intercom_session = manager.create_session(
            terminal_id="T1",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="corr-intercom",
            logical_channel=1,
        )
        await manager.mark_ingest_active(intercom_session.session_id)
        live_session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-live", logical_channel=1
        )

        found = manager.resolve_ingest_by_terminal_id("T1", 1, is_audio=False)

        self.assertEqual(found.session_id, live_session.session_id)

    async def test_resolve_ingest_by_terminal_id_without_is_audio_keeps_first_match_behavior(
        self,
    ) -> None:
        """A caller that doesn't pass `is_audio` (none exists today besides `ingest_server.py`
        itself, which always does — this proves the parameter is genuinely optional, not a
        required migration) gets the exact pre-fix behavior: first `(terminal_id,
        logical_channel)` match, no kind preference."""
        manager, _ = _manager()
        live_session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-live", logical_channel=1
        )
        manager.create_session(
            terminal_id="T1",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="corr-intercom",
            logical_channel=1,
        )

        found = manager.resolve_ingest_by_terminal_id("T1", 1)

        self.assertEqual(found.session_id, live_session.session_id)

    async def test_resolve_ingest_by_terminal_id_returns_none_for_a_channel_with_no_pending_session(
        self,
    ) -> None:
        manager, _ = _manager()
        manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        self.assertIsNone(manager.resolve_ingest_by_terminal_id("T1", 2))

    async def test_resolve_ingest_by_terminal_id_matches_the_narrower_bcd6_sim_card_number(
        self,
    ) -> None:
        """Regression test for a real, live-found bug (2026-08-19, physical bench unit): the
        ingest frame's own SIM card number is `BCD[6]` (12 hex digits), narrower than the
        `BCD[10]` (20 hex digits) `terminal_id` a `VideoSession` is keyed by - the device's real
        terminal_id `00000000014482607571` and its ingest frame's own `014482607571` are the
        same identity, right-justified/zero-padded to the wider field. An exact `==` comparison
        rejected every real ingest connection regardless of correctness."""
        manager, _ = _manager()
        session = manager.create_session(
            terminal_id="00000000014482607571",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-1",
            logical_channel=1,
        )

        found = manager.resolve_ingest_by_terminal_id("014482607571", 1)

        self.assertIsNotNone(found)
        self.assertEqual(found.session_id, session.session_id)

    async def test_resolve_ingest_by_terminal_id_does_not_match_a_coincidental_short_suffix(
        self,
    ) -> None:
        manager, _ = _manager()
        manager.create_session(
            terminal_id="00000000014482607571",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-1",
            logical_channel=1,
        )
        self.assertIsNone(manager.resolve_ingest_by_terminal_id("999999999999", 1))

    async def test_mark_ingest_active_transitions_and_publishes_once(self) -> None:
        manager, publisher = _manager()
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )

        await manager.mark_ingest_active(session.session_id)
        self.assertEqual(session.state, VideoSessionState.ACTIVE)
        self.assertEqual(len(publisher.published), 1)
        self.assertIsInstance(publisher.published[0], VideoSessionActivated)

        # a second frame arriving must not re-publish activation
        await manager.mark_ingest_active(session.session_id)
        self.assertEqual(len(publisher.published), 1)

    async def test_end_session_publishes_ended_and_signals_live_stop(self) -> None:
        manager, publisher = _manager()
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=2
        )
        await manager.mark_ingest_active(session.session_id)

        await manager.end_session(session.session_id, reason="explicit_stop")

        self.assertIsNone(manager.resolve(session.session_id))
        ended = [e for e in publisher.published if isinstance(e, VideoSessionEnded)]
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0].reason, "explicit_stop")
        self.assertEqual(len(publisher.stop_commands), 1)
        self.assertEqual(publisher.stop_commands[0]["command"], "live_video_control")
        self.assertEqual(publisher.stop_commands[0]["fields"]["control"], 0)
        self.assertEqual(publisher.stop_commands[0]["fields"]["logical_channel"], 2)

    async def test_end_session_for_intercom_signals_close_intercom_not_close_av(self) -> None:
        """ADR-0036 — `control=4` (close intercom, Table 6.4), distinct from LIVE's `control=0`
        (close A/V)."""
        manager, publisher = _manager()
        session = manager.create_session(
            terminal_id="T1",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="corr-3",
            logical_channel=1,
        )
        await manager.end_session(session.session_id, reason="explicit_stop")
        self.assertEqual(publisher.stop_commands[0]["command"], "live_video_control")
        self.assertEqual(publisher.stop_commands[0]["fields"]["control"], 4)
        self.assertEqual(publisher.stop_commands[0]["fields"]["logical_channel"], 1)

    async def test_end_session_for_playback_signals_playback_stop(self) -> None:
        manager, publisher = _manager()
        session = manager.create_session(
            terminal_id="T1",
            kind=VideoSessionKind.PLAYBACK,
            correlation_id="corr-2",
            logical_channel=1,
        )
        await manager.end_session(session.session_id, reason="window_exhausted")
        self.assertEqual(publisher.stop_commands[0]["command"], "playback_control")
        self.assertEqual(publisher.stop_commands[0]["fields"]["control"], 2)

    async def test_fail_session_publishes_failed_and_DOES_signal_stop(self) -> None:
        """**Deliberate reversal of this test's own earlier assertion (2026-09-02).** It
        previously asserted `stop_commands == []`, on the reasoning "device never connected -
        nothing to stop." Live measurement against the physical `LSZ-C5804DG-Q-F` bench unit
        disproved that premise: on a session that later times out, the device *does* accept the
        `0x9101` (acknowledging it with `result: 0`) and *does* open the media TCP connection to
        the ingest port - it simply never sends a media byte on it (13 of 15 such connections in
        one observed window). So the device demonstrably holds per-channel state for a request
        RAAD then abandoned, and `ingest_timeout` - the single most common session outcome
        measured here - was the one teardown path that never told it to release that state, while
        the frontend immediately requested the same channel again. A `0x9102` for a stream the
        device isn't actually running is a harmless no-op; never sending it is not."""
        manager, publisher = _manager()
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        await manager.fail_session(session.session_id, reason="ingest_timeout")
        self.assertIsNone(manager.resolve(session.session_id))
        failed = [e for e in publisher.published if isinstance(e, VideoSessionFailed)]
        self.assertEqual(len(failed), 1)
        self.assertEqual(
            publisher.stop_commands,
            [
                {
                    "terminal_id": "T1",
                    "correlation_id": "corr-1",
                    "command": "live_video_control",
                    "fields": {"logical_channel": 1, "control": 0},
                }
            ],
        )

    async def test_fail_session_signals_the_intercom_specific_stop_for_an_intercom_session(self) -> None:
        """The stop must stay purpose-correct on the failure path too: `control: 4` (close
        two-way intercom, Table 6.4) for an INTERCOM session, never LIVE's own `control: 0`."""
        manager, publisher = _manager()
        session = manager.create_session(
            terminal_id="T1",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="corr-1",
            logical_channel=1,
        )
        await manager.fail_session(session.session_id, reason="ingest_timeout")
        self.assertEqual(publisher.stop_commands[0]["fields"], {"logical_channel": 1, "control": 4})

    async def test_fail_session_calls_on_session_removed_with_outcome_and_reason(self) -> None:
        """Bug 1 fix: `OnSessionRemoved` widened from `Callable[[str], None]` to
        `Callable[[str, str, str], None]` — `relay.py._on_session_removed` needs both to pick the
        right WS close code and tell an already-connected browser *why*."""
        calls: list[tuple[str, str, str]] = []
        manager, _ = _manager(on_session_removed=lambda sid, outcome, reason: calls.append((sid, outcome, reason)))
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        await manager.fail_session(session.session_id, reason="ingest_timeout")
        self.assertEqual(calls, [(session.session_id, "failed", "ingest_timeout")])

    async def test_end_session_calls_on_session_removed_with_outcome_and_reason(self) -> None:
        calls: list[tuple[str, str, str]] = []
        manager, _ = _manager(on_session_removed=lambda sid, outcome, reason: calls.append((sid, outcome, reason)))
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        await manager.end_session(session.session_id, reason="explicit_stop")
        self.assertEqual(calls, [(session.session_id, "ended", "explicit_stop")])

    async def test_viewer_count_tracks_join_and_leave(self) -> None:
        manager, _ = _manager()
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        manager.add_viewer(session.session_id)
        manager.add_viewer(session.session_id)
        self.assertEqual(session.viewer_count, 2)
        manager.remove_viewer(session.session_id)
        self.assertEqual(session.viewer_count, 1)
        manager.remove_viewer(session.session_id)
        self.assertEqual(session.viewer_count, 0)
        manager.remove_viewer(session.session_id)  # never goes negative
        self.assertEqual(session.viewer_count, 0)

    async def test_sweep_idle_sessions_ends_a_session_past_viewer_grace(self) -> None:
        manager, publisher = _manager(viewer_grace_seconds=0.01, absolute_idle_seconds=999)
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        await manager.mark_ingest_active(session.session_id)
        manager.add_viewer(session.session_id)
        manager.remove_viewer(session.session_id)

        import asyncio

        await asyncio.sleep(0.05)
        acted_on = await manager.sweep_idle_sessions()

        self.assertEqual(acted_on, [session.session_id])
        self.assertIsNone(manager.resolve(session.session_id))
        ended = [e for e in publisher.published if isinstance(e, VideoSessionEnded)]
        self.assertEqual(ended[0].reason, "viewer_idle_timeout")

    async def test_sweep_idle_sessions_fails_a_session_stuck_requested_past_ingest_timeout(
        self,
    ) -> None:
        manager, publisher = _manager(ingest_timeout_seconds=0.01)
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )

        import asyncio

        await asyncio.sleep(0.05)
        acted_on = await manager.sweep_idle_sessions()

        self.assertEqual(acted_on, [session.session_id])
        failed = [e for e in publisher.published if isinstance(e, VideoSessionFailed)]
        self.assertEqual(failed[0].reason, "ingest_timeout")

    async def test_sweep_idle_sessions_leaves_an_active_recently_viewed_session_alone(
        self,
    ) -> None:
        manager, publisher = _manager(viewer_grace_seconds=999, absolute_idle_seconds=999)
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        await manager.mark_ingest_active(session.session_id)
        manager.add_viewer(session.session_id)

        acted_on = await manager.sweep_idle_sessions()

        self.assertEqual(acted_on, [])
        self.assertIsNotNone(manager.resolve(session.session_id))


class IngestDisconnectTests(unittest.IsolatedAsyncioTestCase):
    """The device's own FIN on its JT/T 1078 connection is an explicit end-of-stream signal and
    is acted on immediately, instead of being inferred ~60s later by the idle sweep. Packet-
    captured live 2026-09-02: after a radio-link outage the physical MDVR sends FIN on every
    video connection rather than resuming."""

    async def test_active_session_ends_when_its_ingest_connection_closes(self) -> None:
        manager, publisher = _manager()
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        await manager.mark_ingest_active(session.session_id)
        self.assertEqual(session.state, VideoSessionState.ACTIVE)

        await manager.handle_ingest_disconnected(session.session_id)

        self.assertIsNone(manager.resolve(session.session_id))
        ended = [e for e in publisher.published if type(e).__name__ == "VideoSessionEnded"]
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0].reason, "ingest_disconnected")

    async def test_requested_session_fails_when_its_ingest_connection_closes(self) -> None:
        """The device connected and hung up without ever streaming - a genuine failure to
        establish, not an ordinary end, so it must surface as Failed (WS close 4010)."""
        manager, publisher = _manager()
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )

        await manager.handle_ingest_disconnected(session.session_id)

        self.assertIsNone(manager.resolve(session.session_id))
        failed = [e for e in publisher.published if type(e).__name__ == "VideoSessionFailed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].reason, "ingest_disconnected")

    async def test_is_a_no_op_for_an_already_removed_session(self) -> None:
        """`IngestServer`'s `finally` also runs when *we* closed the connection during a normal
        teardown - by then the session is gone, and this must not emit a second event."""
        manager, publisher = _manager()
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        await manager.mark_ingest_active(session.session_id)
        await manager.end_session(session.session_id, reason="business_api_requested")
        before = len(publisher.published)

        await manager.handle_ingest_disconnected(session.session_id)

        self.assertEqual(len(publisher.published), before)

    async def test_unknown_session_id_is_a_no_op(self) -> None:
        manager, publisher = _manager()
        await manager.handle_ingest_disconnected("no-such-session")
        self.assertEqual(publisher.published, [])


class ConcurrencyCeilingTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0026 §8 — configurable global and per-organization concurrent-session ceilings."""

    async def test_default_global_ceiling_is_fifty(self) -> None:
        """Citing Phase 2 §13.1's own "e.g., start 50 global" — the default, not a made-up
        number."""
        manager, _ = _manager()
        for i in range(50):
            manager.create_session(
                terminal_id=f"T{i}",
                kind=VideoSessionKind.LIVE,
                correlation_id=f"corr-{i}",
                logical_channel=1,
            )
        with self.assertRaises(SessionCapacityExceededError):
            manager.create_session(
                terminal_id="T-over",
                kind=VideoSessionKind.LIVE,
                correlation_id="corr-over",
                logical_channel=1,
            )

    async def test_global_ceiling_of_zero_or_less_means_unlimited(self) -> None:
        manager, _ = _manager(max_global_sessions=0)
        for i in range(5):
            manager.create_session(
                terminal_id=f"T{i}",
                kind=VideoSessionKind.LIVE,
                correlation_id=f"corr-{i}",
                logical_channel=1,
            )  # must not raise
        self.assertEqual(manager.active_session_count, 5)

    async def test_global_ceiling_rejects_the_request_before_creating_a_session(self) -> None:
        manager, _ = _manager(max_global_sessions=1)
        manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        with self.assertRaises(SessionCapacityExceededError):
            manager.create_session(
                terminal_id="T2",
                kind=VideoSessionKind.LIVE,
                correlation_id="corr-2",
                logical_channel=1,
            )
        # rejected - the session count must not have grown past the ceiling
        self.assertEqual(manager.active_session_count, 1)

    async def test_per_organization_ceiling_is_independent_of_global(self) -> None:
        manager, _ = _manager(max_global_sessions=100, max_sessions_per_organization=1)
        manager.create_session(
            terminal_id="T1",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-1",
            logical_channel=1,
            organization_id="org-A",
        )
        with self.assertRaises(SessionCapacityExceededError):
            manager.create_session(
                terminal_id="T2",
                kind=VideoSessionKind.LIVE,
                correlation_id="corr-2",
                logical_channel=1,
                organization_id="org-A",
            )

    async def test_per_organization_ceiling_does_not_affect_other_organizations(self) -> None:
        manager, _ = _manager(max_global_sessions=100, max_sessions_per_organization=1)
        manager.create_session(
            terminal_id="T1",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-1",
            logical_channel=1,
            organization_id="org-A",
        )
        session_b = manager.create_session(
            terminal_id="T2",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-2",
            logical_channel=1,
            organization_id="org-B",
        )  # must not raise - a different organization
        self.assertIsNotNone(manager.resolve(session_b.session_id))

    async def test_organization_less_session_is_only_subject_to_the_global_ceiling(self) -> None:
        manager, _ = _manager(max_global_sessions=100, max_sessions_per_organization=1)
        manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        session = manager.create_session(
            terminal_id="T2", kind=VideoSessionKind.LIVE, correlation_id="corr-2", logical_channel=1
        )  # organization_id=None both times - must not raise
        self.assertIsNotNone(manager.resolve(session.session_id))

    async def test_ending_a_session_frees_its_ceiling_slot(self) -> None:
        manager, _ = _manager(max_global_sessions=1)
        first = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        await manager.end_session(first.session_id, reason="explicit_stop")

        second = manager.create_session(
            terminal_id="T2", kind=VideoSessionKind.LIVE, correlation_id="corr-2", logical_channel=1
        )  # must not raise - the first session's slot is now free
        self.assertIsNotNone(manager.resolve(second.session_id))


class IntercomExclusivityTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0036 §2 — one active intercom session per device, in-process. The second of two
    independent checks (the backend's own `VideoApplicationService.request_intercom` makes the
    first, DB-backed one, before ever calling this relay)."""

    async def test_a_second_intercom_session_for_the_same_terminal_is_rejected(self) -> None:
        manager, _ = _manager()
        manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.INTERCOM, correlation_id="c1", logical_channel=1
        )
        with self.assertRaises(SessionCapacityExceededError):
            manager.create_session(
                terminal_id="T1",
                kind=VideoSessionKind.INTERCOM,
                correlation_id="c2",
                logical_channel=1,
            )

    async def test_a_second_intercom_session_for_a_different_terminal_is_not_blocked(self) -> None:
        manager, _ = _manager()
        manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.INTERCOM, correlation_id="c1", logical_channel=1
        )
        second = manager.create_session(
            terminal_id="T2", kind=VideoSessionKind.INTERCOM, correlation_id="c2", logical_channel=1
        )
        self.assertIsNotNone(manager.resolve(second.session_id))

    async def test_a_live_session_does_not_block_an_intercom_session_on_the_same_terminal(
        self,
    ) -> None:
        """Only INTERCOM-vs-INTERCOM is exclusive - an ordinary LIVE viewing session on the same
        device must not be affected."""
        manager, _ = _manager()
        manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="c1", logical_channel=1
        )
        intercom = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.INTERCOM, correlation_id="c2", logical_channel=1
        )
        self.assertIsNotNone(manager.resolve(intercom.session_id))

    async def test_ending_an_intercom_session_frees_the_terminal_for_a_new_one(self) -> None:
        manager, _ = _manager()
        first = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.INTERCOM, correlation_id="c1", logical_channel=1
        )
        await manager.end_session(first.session_id, reason="explicit_stop")
        second = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.INTERCOM, correlation_id="c2", logical_channel=1
        )
        self.assertIsNotNone(manager.resolve(second.session_id))



class IdleReasonTests(unittest.IsolatedAsyncioTestCase):
    """Distinct idle reasons (2026-09-02). "No viewers attached" and "the device stopped sending"
    are opposite problems - one points at the browser/network, the other at the device/vendor -
    and collapsing both into `"viewer_idle_timeout"` sent a real live investigation down the wrong
    path: every session in a two-cycle bench test against the physical unit was removed 66-70s
    after its own last keyframe (unambiguously an ingest stall, with the browser still attached),
    while the log claimed "viewer"."""

    async def test_no_viewers_reports_viewer_idle_timeout(self) -> None:
        manager, publisher = _manager(viewer_grace_seconds=0.0, absolute_idle_seconds=3600.0)
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="c1", logical_channel=1
        )
        await manager.mark_ingest_active(session.session_id)
        manager.add_viewer(session.session_id)
        manager.remove_viewer(session.session_id)  # browser detached

        acted = await manager.sweep_idle_sessions()

        self.assertEqual(acted, [session.session_id])
        ended = [e for e in publisher.published if isinstance(e, VideoSessionEnded)]
        self.assertEqual(ended[0].reason, "viewer_idle_timeout")

    async def test_device_stopped_sending_reports_ingest_stalled_timeout(self) -> None:
        """A viewer is still attached the whole time - only the media stopped. This must NOT be
        reported as a viewer problem."""
        manager, publisher = _manager(viewer_grace_seconds=3600.0, absolute_idle_seconds=0.0)
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="c1", logical_channel=1
        )
        await manager.mark_ingest_active(session.session_id)
        manager.add_viewer(session.session_id)  # viewer stays attached

        acted = await manager.sweep_idle_sessions()

        self.assertEqual(acted, [session.session_id])
        ended = [e for e in publisher.published if isinstance(e, VideoSessionEnded)]
        self.assertEqual(ended[0].reason, "ingest_stalled_timeout")

    async def test_an_actively_ingesting_session_with_a_viewer_is_never_swept(self) -> None:
        manager, _ = _manager(viewer_grace_seconds=3600.0, absolute_idle_seconds=3600.0)
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="c1", logical_channel=1
        )
        await manager.mark_ingest_active(session.session_id)
        manager.add_viewer(session.session_id)
        manager.touch_ingest(session.session_id)

        self.assertEqual(await manager.sweep_idle_sessions(), [])

if __name__ == "__main__":
    unittest.main()
