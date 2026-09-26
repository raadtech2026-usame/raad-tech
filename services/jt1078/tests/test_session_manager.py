"""`SessionManager` tests (`session/session_manager.py`, ADR-0046): device stream ownership shared by
viewer sessions, one ordered command path stamped with a generation, the per-channel start slot,
live/intercom independence, idle teardown - all against a recording fake publisher and a fake
clock."""

import time
import unittest

from src.events.session_events import VideoSessionActivated, VideoSessionEnded, VideoSessionFailed
from src.session.device_stream import DeviceStreamState
from src.session.session_manager import SessionCapacityExceededError, SessionManager
from src.session.video_session import StreamType, VideoSessionKind, VideoSessionState

TERMINAL = "00000000014482607571"
SIM = "014482607571"  # the BCD[6] form a JT/T 1078 ingest frame carries


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[object] = []
        self.stop_commands: list[dict] = []  # every device command, starts included

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

    @property
    def commands(self) -> list[dict]:
        return self.stop_commands

    def kinds(self) -> list[str]:
        """Compact command log: `start:<ch>:<stream type or data type>` / `stop:<ch>:...`."""
        out = []
        for c in self.stop_commands:
            f = c["fields"]
            if c["command"] == "live_video_request":
                label = "intercom" if f["data_type"] == 2 else ("main" if f["stream_type"] == 0 else "sub")
                out.append(f"start:{f['logical_channel']}:{label}")
            elif c["command"] == "live_video_control":
                if f["control"] == 4:
                    out.append(f"stop:{f['logical_channel']}:intercom")
                else:
                    out.append(f"stop:{f['logical_channel']}:av{f.get('close_av_type', 0)}")
            elif c["command"] == "playback_request":
                out.append(f"start:{f['logical_channel']}:playback")
            elif c["command"] == "playback_control":
                out.append(f"stop:{f['av_channel']}:playback")
        return out


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _manager(**kwargs) -> tuple[SessionManager, RecordingPublisher]:
    publisher = RecordingPublisher()
    kwargs.setdefault("ingest_target", ("203.0.113.5", 7910))
    manager = SessionManager(event_publisher=publisher, **kwargs)
    return manager, publisher


def _live(manager, session_id, *, channel=1, stream_type=StreamType.MAIN, relay=True, org="O1"):
    return manager.create_session(
        session_id=session_id,
        terminal_id=TERMINAL,
        kind=VideoSessionKind.LIVE,
        correlation_id=session_id,
        logical_channel=channel,
        organization_id=org,
        stream_type=stream_type,
        relay_signals_device=relay,
    )


def _intercom(manager, session_id, *, channel=1, relay=True):
    return manager.create_session(
        session_id=session_id,
        terminal_id=TERMINAL,
        kind=VideoSessionKind.INTERCOM,
        correlation_id=session_id,
        logical_channel=channel,
        relay_signals_device=relay,
    )


async def _connect(manager, *, channel=1, is_audio=False):
    """What `IngestServer` does for a new media connection's first frame."""
    stream = manager.resolve_ingest_stream(SIM, channel, is_audio=is_audio)
    assert stream is not None, "no stream accepted the connection"
    manager.note_ingest_connected(stream.stream_id)
    await manager.mark_stream_active(stream.stream_id)
    return stream


class StreamOwnershipTests(unittest.IsolatedAsyncioTestCase):
    """The production bug of 2026-09-23: two users on one channel, one user's stop killed the
    other's video. One device stream per channel, stopped only by its last session."""

    async def test_two_viewers_of_one_channel_share_one_device_stream(self) -> None:
        manager, publisher = _manager()
        a = _live(manager, "A")
        b = _live(manager, "B")
        await manager.flush()
        self.assertEqual(a.stream_id, b.stream_id)
        self.assertEqual(publisher.kinds(), ["start:1:main"], "one start for two viewers")

    async def test_b_stops_and_a_continues(self) -> None:
        manager, publisher = _manager()
        a = _live(manager, "A")
        _live(manager, "B")
        await _connect(manager)
        await manager.end_session("B", reason="business_api_requested")
        self.assertEqual(publisher.kinds(), ["start:1:main"], "no stop while A still watches")
        self.assertEqual(manager.resolve("A").state, VideoSessionState.ACTIVE)
        self.assertIsNotNone(manager.resolve_stream(a.stream_id))

    async def test_a_stops_and_b_continues(self) -> None:
        manager, publisher = _manager()
        _live(manager, "A")
        b = _live(manager, "B")
        await _connect(manager)
        await manager.end_session("A", reason="business_api_requested")
        self.assertEqual(publisher.kinds(), ["start:1:main"])
        self.assertEqual(manager.resolve("B").state, VideoSessionState.ACTIVE)
        self.assertIsNotNone(manager.resolve_stream(b.stream_id))

    async def test_the_last_viewer_leaving_stops_the_stream_once(self) -> None:
        manager, publisher = _manager()
        _live(manager, "A")
        _live(manager, "B")
        await _connect(manager)
        await manager.end_session("A", reason="business_api_requested")
        await manager.end_session("B", reason="business_api_requested")
        self.assertEqual(publisher.kinds(), ["start:1:main", "stop:1:av0"])
        self.assertEqual(manager.active_stream_count, 0)

    async def test_viewers_of_different_channels_are_independent(self) -> None:
        manager, publisher = _manager()
        a = _live(manager, "A", channel=1)
        b = _live(manager, "B", channel=3)
        await _connect(manager, channel=1)
        await _connect(manager, channel=3)
        self.assertNotEqual(a.stream_id, b.stream_id)
        await manager.end_session("A", reason="business_api_requested")
        self.assertEqual(publisher.kinds(), ["start:1:main", "start:3:main", "stop:1:av0"])
        self.assertEqual(manager.resolve("B").state, VideoSessionState.ACTIVE)

    async def test_a_second_viewer_joining_a_running_stream_is_active_at_once(self) -> None:
        manager, publisher = _manager()
        _live(manager, "A")
        await _connect(manager)
        _live(manager, "B")
        await manager.flush()
        self.assertEqual(manager.resolve("B").state, VideoSessionState.ACTIVE)
        activated = [e.session_id for e in publisher.published if isinstance(e, VideoSessionActivated)]
        self.assertEqual(activated, ["A", "B"])

    async def test_a_timed_out_second_viewer_cannot_kill_the_first(self) -> None:
        """Exactly the 2026-09-23 sequence: B's session used to wait for a connection that never
        came, fail on ingest_timeout and send 0x9102. Now B shares A's running stream."""
        clock = FakeClock()
        manager, publisher = _manager(clock=clock)
        _live(manager, "A")
        await _connect(manager)
        _live(manager, "B")
        clock.now += 60  # well past ingest_timeout; A's stream keeps delivering
        manager.touch_stream(manager.resolve("A").stream_id)
        await manager.sweep_idle_sessions()
        self.assertEqual(manager.resolve("A").state, VideoSessionState.ACTIVE)
        self.assertEqual(manager.resolve("B").state, VideoSessionState.ACTIVE)
        self.assertEqual(publisher.kinds(), ["start:1:main"])


class StopStartOrderingTests(unittest.IsolatedAsyncioTestCase):
    """A late stop must never be able to kill a newer start."""

    async def test_restart_after_release_orders_stop_before_the_new_start(self) -> None:
        manager, publisher = _manager()  # linger 0
        first = _live(manager, "A")
        await _connect(manager)
        await manager.end_session("A", reason="business_api_requested")
        second = _live(manager, "B")
        await manager.flush()
        self.assertEqual(publisher.kinds(), ["start:1:main", "stop:1:av0", "start:1:main"])
        self.assertNotEqual(first.stream_id, second.stream_id)

    async def test_a_new_viewer_within_the_linger_reuses_the_stream_with_no_stop(self) -> None:
        clock = FakeClock()
        manager, publisher = _manager(clock=clock, stream_linger_seconds=5)
        a = _live(manager, "A")
        await _connect(manager)
        await manager.end_session("A", reason="business_api_requested")  # reconnect: old session
        clock.now += 1
        b = _live(manager, "B")  # ...and its replacement
        clock.now += 10
        await manager.sweep_idle_sessions()
        self.assertEqual(a.stream_id, b.stream_id)
        self.assertEqual(publisher.kinds(), ["start:1:main"], "no stop/start churn")

    async def test_released_stream_stops_after_the_linger(self) -> None:
        clock = FakeClock()
        manager, publisher = _manager(clock=clock, stream_linger_seconds=5)
        _live(manager, "A")
        await _connect(manager)
        await manager.end_session("A", reason="business_api_requested")
        clock.now += 4
        await manager.sweep_idle_sessions()
        self.assertEqual(publisher.kinds(), ["start:1:main"])
        clock.now += 2
        await manager.sweep_idle_sessions()
        self.assertEqual(publisher.kinds(), ["start:1:main", "stop:1:av0"])

    async def test_commands_carry_their_stream_generation(self) -> None:
        manager, publisher = _manager()
        _live(manager, "A", stream_type=StreamType.SUB)
        await _connect(manager)
        _live(manager, "B", stream_type=StreamType.MAIN)  # upgrade: restart as generation 2
        await manager.flush()
        ids = [c["correlation_id"] for c in publisher.commands]
        self.assertTrue(ids[0].endswith("-g1"))
        self.assertTrue(ids[1].endswith("-g1-stop"))
        self.assertTrue(ids[2].endswith("-g2"))

    async def test_an_old_generations_connection_closing_does_not_end_the_restarted_stream(self) -> None:
        manager, publisher = _manager()
        a = _live(manager, "A", stream_type=StreamType.SUB)
        await _connect(manager)
        _live(manager, "B", stream_type=StreamType.MAIN)
        await manager.flush()
        stream = manager.resolve_stream(a.stream_id)
        self.assertEqual(stream.generation, 2)
        await manager.handle_ingest_disconnected(a.stream_id, generation=1, remaining_connections=0)
        self.assertIsNotNone(manager.resolve_stream(a.stream_id))
        self.assertEqual(manager.resolve("A").state, VideoSessionState.ACTIVE)

    async def test_a_legacy_request_is_never_started_by_the_relay_but_is_still_stopped(self) -> None:
        """Rolling-deploy compatibility: a Business API without `relay_signals_device` still
        publishes its own start; the relay must not add a second one."""
        manager, publisher = _manager()
        _live(manager, "A", relay=False)
        await _connect(manager)
        await manager.end_session("A", reason="business_api_requested")
        self.assertEqual(publisher.kinds(), ["stop:1:av0"])


class StreamTypeTests(unittest.IsolatedAsyncioTestCase):
    """One live stream per channel; it runs main if any session wants main (ADR-0046 §2)."""

    async def test_sub_only_viewers_get_a_sub_stream(self) -> None:
        manager, publisher = _manager()
        _live(manager, "A", stream_type=StreamType.SUB)
        await manager.flush()
        self.assertEqual(publisher.kinds(), ["start:1:sub"])

    async def test_a_main_viewer_upgrades_a_running_sub_stream_immediately(self) -> None:
        manager, publisher = _manager()
        _live(manager, "A", stream_type=StreamType.SUB)
        await _connect(manager)
        _live(manager, "B", stream_type=StreamType.MAIN)
        await manager.flush()
        self.assertEqual(publisher.kinds(), ["start:1:sub", "stop:1:av0", "start:1:main"])

    async def test_one_viewer_falling_back_to_sub_does_not_downgrade_a_main_viewer(self) -> None:
        clock = FakeClock()
        manager, publisher = _manager(clock=clock, stream_linger_seconds=5)
        _live(manager, "A", stream_type=StreamType.MAIN)
        _live(manager, "B", stream_type=StreamType.MAIN)
        await _connect(manager)
        await manager.end_session("B", reason="business_api_requested")
        _live(manager, "B2", stream_type=StreamType.SUB)  # B's fallback session
        clock.now += 60
        manager.touch_stream(manager.resolve("A").stream_id)
        await manager.sweep_idle_sessions()
        self.assertEqual(publisher.kinds(), ["start:1:main"], "A still wants main")

    async def test_downgrade_waits_for_the_linger(self) -> None:
        clock = FakeClock()
        manager, publisher = _manager(clock=clock, stream_linger_seconds=5)
        _live(manager, "A", stream_type=StreamType.MAIN)
        await _connect(manager)
        await manager.end_session("A", reason="business_api_requested")  # unfocus...
        _live(manager, "A2", stream_type=StreamType.SUB)  # ...same tile now wants sub
        await manager.sweep_idle_sessions()
        self.assertEqual(publisher.kinds(), ["start:1:main"])
        clock.now += 6
        manager.touch_stream(manager.resolve("A2").stream_id)
        await manager.sweep_idle_sessions()
        self.assertEqual(publisher.kinds(), ["start:1:main", "stop:1:av0", "start:1:sub"])


class IntercomIndependenceTests(unittest.IsolatedAsyncioTestCase):
    """Live A/V and intercom on channel 1 are separate device streams (ADR-0046 §4)."""

    async def test_intercom_and_live_on_one_channel_are_separate_streams(self) -> None:
        manager, _ = _manager()
        live = _live(manager, "V")
        await _connect(manager)
        talk = _intercom(manager, "I")
        await manager.flush()
        self.assertNotEqual(live.stream_id, talk.stream_id)

    async def test_intercom_start_waits_for_the_live_streams_connection(self) -> None:
        """Both pending on one channel would make the next connection ambiguous."""
        manager, publisher = _manager()
        _live(manager, "V")
        _intercom(manager, "I")
        await manager.flush()
        self.assertEqual(publisher.kinds(), ["start:1:main"], "intercom start held")
        live_stream = await _connect(manager)
        await manager.flush()
        self.assertEqual(live_stream.kind, VideoSessionKind.LIVE)
        self.assertEqual(publisher.kinds(), ["start:1:main", "start:1:intercom"])
        talk_stream = await _connect(manager, is_audio=True)
        self.assertEqual(talk_stream.kind, VideoSessionKind.INTERCOM)

    async def test_the_start_slot_is_released_after_the_window_even_without_a_connection(self) -> None:
        clock = FakeClock()
        manager, publisher = _manager(clock=clock, start_serialization_window_seconds=10)
        _live(manager, "V")
        _intercom(manager, "I")
        clock.now += 11
        await manager.sweep_idle_sessions()
        self.assertEqual(publisher.kinds(), ["start:1:main", "start:1:intercom"])

    async def test_stopping_live_while_talking_closes_video_only(self) -> None:
        manager, publisher = _manager()
        _live(manager, "V")
        await _connect(manager)
        _intercom(manager, "I")
        await _connect(manager, is_audio=True)
        await manager.end_session("V", reason="business_api_requested")
        self.assertEqual(publisher.kinds()[-1], "stop:1:av2", "close type 2 keeps the intercom audio")
        self.assertEqual(manager.resolve("I").state, VideoSessionState.ACTIVE)

    async def test_stopping_intercom_keeps_live_video(self) -> None:
        manager, publisher = _manager()
        _live(manager, "V")
        await _connect(manager)
        _intercom(manager, "I")
        await _connect(manager, is_audio=True)
        await manager.end_session("I", reason="business_api_requested")
        self.assertEqual(publisher.kinds()[-1], "stop:1:intercom")
        self.assertEqual(manager.resolve("V").state, VideoSessionState.ACTIVE)

    async def test_another_live_viewer_never_takes_the_intercom_connection(self) -> None:
        manager, _ = _manager()
        _intercom(manager, "I")
        talk_stream = await _connect(manager, is_audio=True)
        viewer = _live(manager, "V")
        await manager.flush()
        live_stream = await _connect(manager, is_audio=False)
        self.assertEqual(live_stream.stream_id, viewer.stream_id)
        self.assertNotEqual(live_stream.stream_id, talk_stream.stream_id)

    async def test_a_live_ac_connection_opening_with_audio_still_goes_to_the_pending_live_stream(self) -> None:
        """A live A/V connection may deliver an audio frame first; the stream waiting for its
        connection wins over an already-connected intercom."""
        manager, _ = _manager()
        _intercom(manager, "I")
        await _connect(manager, is_audio=True)
        viewer = _live(manager, "V")
        await manager.flush()
        stream = await _connect(manager, is_audio=True)
        self.assertEqual(stream.stream_id, viewer.stream_id)

    async def test_live_stop_with_no_intercom_closes_everything_as_before(self) -> None:
        manager, publisher = _manager()
        _live(manager, "V")
        await _connect(manager)
        await manager.end_session("V", reason="business_api_requested")
        self.assertEqual(publisher.kinds()[-1], "stop:1:av0")


class RestartSlotTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_restart_waits_while_an_intercom_on_the_channel_awaits_its_connection(self) -> None:
        manager, publisher = _manager()
        _live(manager, "V", stream_type=StreamType.SUB)
        await _connect(manager)
        _intercom(manager, "I")  # started, waiting for its connection
        await manager.flush()
        _live(manager, "V2", stream_type=StreamType.MAIN)  # upgrade -> restart
        await manager.flush()
        self.assertEqual(
            publisher.kinds(), ["start:1:sub", "start:1:intercom", "stop:1:av2"],
            "the restart's start is held until the intercom has its connection",
        )
        await _connect(manager, is_audio=True)
        await manager.flush()
        self.assertEqual(publisher.kinds()[-1], "start:1:main")


class IngestResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_matches_the_narrower_bcd6_sim_card_number(self) -> None:
        manager, _ = _manager()
        _live(manager, "A")
        await manager.flush()
        self.assertIsNotNone(manager.resolve_ingest_stream("014482607571", 1))

    async def test_does_not_match_a_coincidental_short_suffix(self) -> None:
        manager, _ = _manager()
        _live(manager, "A")
        self.assertIsNone(manager.resolve_ingest_stream("999999999999", 1))

    async def test_unsolicited_channel_resolves_to_nothing(self) -> None:
        manager, _ = _manager()
        _live(manager, "A", channel=1)
        self.assertIsNone(manager.resolve_ingest_stream(SIM, 2))

    async def test_a_stream_waiting_for_its_start_slot_accepts_no_connection(self) -> None:
        manager, _ = _manager()
        _live(manager, "V")
        _intercom(manager, "I")  # deferred: generation 0
        stream = manager.resolve_ingest_stream(SIM, 1, is_audio=True)
        self.assertEqual(stream.kind, VideoSessionKind.LIVE)

    async def test_video_prefers_the_live_stream_over_a_running_intercom(self) -> None:
        manager, _ = _manager()
        _intercom(manager, "I")
        await _connect(manager, is_audio=True)
        viewer = _live(manager, "V")
        await manager.flush()
        await _connect(manager, is_audio=False)
        # A reconnect of the running live stream (not waiting any more) still prefers live.
        stream = manager.resolve_ingest_stream(SIM, 1, is_audio=False)
        self.assertEqual(stream.stream_id, viewer.stream_id)

    async def test_playback_on_a_live_channel_is_its_own_stream(self) -> None:
        manager, publisher = _manager()
        live = _live(manager, "V")
        await _connect(manager)
        playback = manager.create_session(
            session_id="P",
            terminal_id=TERMINAL,
            kind=VideoSessionKind.PLAYBACK,
            correlation_id="P",
            logical_channel=1,
            relay_signals_device=True,
            window_start="2026-09-25T10:00:00+00:00",
            window_end="2026-09-25T10:05:00+00:00",
        )
        await manager.flush()
        self.assertNotEqual(live.stream_id, playback.stream_id)
        self.assertEqual(publisher.kinds(), ["start:1:main", "start:1:playback"])
        start = publisher.commands[-1]["fields"]
        self.assertEqual(start["start_time"], "2026-09-25T10:00:00+00:00")
        await manager.end_session("P", reason="business_api_requested")
        self.assertEqual(publisher.kinds()[-1], "stop:1:playback")
        self.assertEqual(manager.resolve("V").state, VideoSessionState.ACTIVE)

    async def test_start_command_names_this_relays_ingest_target(self) -> None:
        manager, publisher = _manager()
        _live(manager, "A", stream_type=StreamType.SUB)
        await manager.flush()
        fields = publisher.commands[0]["fields"]
        self.assertEqual(
            fields,
            {
                "server_ip": "203.0.113.5",
                "tcp_port": 7910,
                "udp_port": 0,
                "logical_channel": 1,
                "data_type": 0,
                "stream_type": 1,
            },
        )


class LifecycleEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_activation_is_published_once_per_session(self) -> None:
        manager, publisher = _manager()
        _live(manager, "A")
        stream = await _connect(manager)
        await manager.mark_stream_active(stream.stream_id)
        activated = [e for e in publisher.published if isinstance(e, VideoSessionActivated)]
        self.assertEqual(len(activated), 1)

    async def test_ending_a_session_publishes_ended_and_calls_the_removal_hook(self) -> None:
        removed = []
        manager, publisher = _manager(on_session_removed=lambda *a: removed.append(a))
        _live(manager, "A")
        await manager.end_session("A", reason="explicit_stop")
        self.assertEqual(removed, [("A", "ended", "explicit_stop")])
        self.assertIsInstance(publisher.published[-1], VideoSessionEnded)

    async def test_ingest_timeout_fails_every_session_of_the_stream_and_stops_it(self) -> None:
        clock = FakeClock()
        removed = []
        manager, publisher = _manager(clock=clock, on_session_removed=lambda *a: removed.append(a))
        _live(manager, "A")
        _live(manager, "B")
        clock.now += 31
        acted = await manager.sweep_idle_sessions()
        self.assertCountEqual(acted, ["A", "B"])
        self.assertCountEqual(removed, [("A", "failed", "ingest_timeout"), ("B", "failed", "ingest_timeout")])
        failed = [e for e in publisher.published if isinstance(e, VideoSessionFailed)]
        self.assertEqual(len(failed), 2)
        # A stream that never connected is still cancelled on the terminal (2026-09-02).
        self.assertEqual(publisher.kinds(), ["start:1:main", "stop:1:av0"])

    async def test_a_stalled_stream_ends_its_sessions(self) -> None:
        clock = FakeClock()
        manager, publisher = _manager(clock=clock)
        _live(manager, "A")
        await _connect(manager)
        clock.now += 61
        await manager.sweep_idle_sessions()
        ended = [e for e in publisher.published if isinstance(e, VideoSessionEnded)]
        self.assertEqual([e.reason for e in ended], ["ingest_stalled_timeout"])
        self.assertEqual(manager.active_stream_count, 0)

    async def test_device_closing_the_current_connection_ends_active_sessions(self) -> None:
        manager, publisher = _manager()
        a = _live(manager, "A")
        await _connect(manager)
        await manager.handle_ingest_disconnected(a.stream_id, generation=1, remaining_connections=0)
        self.assertIsNone(manager.resolve("A"))
        ended = [e for e in publisher.published if isinstance(e, VideoSessionEnded)]
        self.assertEqual([e.reason for e in ended], ["ingest_disconnected"])

    async def test_device_closing_before_any_frame_fails_the_session(self) -> None:
        manager, publisher = _manager()
        a = _live(manager, "A")
        await manager.flush()
        await manager.handle_ingest_disconnected(a.stream_id, generation=1, remaining_connections=0)
        failed = [e for e in publisher.published if isinstance(e, VideoSessionFailed)]
        self.assertEqual([e.reason for e in failed], ["ingest_disconnected"])

    async def test_a_superseded_connection_closing_is_not_news(self) -> None:
        manager, _ = _manager()
        a = _live(manager, "A")
        await _connect(manager)
        await manager.handle_ingest_disconnected(a.stream_id, generation=1, remaining_connections=1)
        self.assertIsNotNone(manager.resolve("A"))

    async def test_disconnect_for_an_unknown_stream_is_a_no_op(self) -> None:
        manager, publisher = _manager()
        await manager.handle_ingest_disconnected("nope", generation=1)
        self.assertEqual(publisher.published, [])

    async def test_viewer_idle_ends_only_that_session(self) -> None:
        manager, publisher = _manager(viewer_grace_seconds=15)
        _live(manager, "A")
        _live(manager, "B")
        stream = await _connect(manager)
        manager.add_viewer("A")
        manager.add_viewer("B")
        manager.remove_viewer("A")
        manager.resolve("A").last_viewer_disconnected_at = time.monotonic() - 16
        acted = await manager.sweep_idle_sessions()
        self.assertEqual(acted, ["A"])
        self.assertIsNotNone(manager.resolve_stream(stream.stream_id))
        self.assertEqual(publisher.kinds(), ["start:1:main"])

    async def test_a_viewer_that_never_connects_is_released(self) -> None:
        """Without this an abandoned request would keep a shared stream alive forever."""
        manager, _ = _manager(viewer_grace_seconds=15)
        _live(manager, "A")
        stream = await _connect(manager)
        manager.resolve("A").created_at = time.monotonic() - 31
        acted = await manager.sweep_idle_sessions()
        self.assertEqual(acted, ["A"])
        self.assertIsNone(manager.resolve_stream(stream.stream_id))

    async def test_a_watched_delivering_stream_is_never_swept(self) -> None:
        manager, publisher = _manager()
        _live(manager, "A")
        await _connect(manager)
        manager.add_viewer("A")
        self.assertEqual(await manager.sweep_idle_sessions(), [])
        self.assertEqual(manager.resolve_stream(manager.resolve("A").stream_id).state, DeviceStreamState.ACTIVE)

    async def test_viewer_count_never_goes_negative(self) -> None:
        manager, _ = _manager()
        session = _live(manager, "A")
        manager.add_viewer("A")
        manager.remove_viewer("A")
        manager.remove_viewer("A")
        self.assertEqual(session.viewer_count, 0)


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



