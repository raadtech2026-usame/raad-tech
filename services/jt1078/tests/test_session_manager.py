"""`SessionManager` tests (`session/session_manager.py`) — lifecycle, viewer counting, idle
teardown, and the device stop-signal publish, all against a recording fake publisher."""

import unittest

from src.events.session_events import VideoSessionActivated, VideoSessionEnded, VideoSessionFailed
from src.session.session_manager import SessionManager
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

    async def test_resolve_ingest_by_terminal_id_finds_a_requested_session(self) -> None:
        manager, _ = _manager()
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        found = manager.resolve_ingest_by_terminal_id("T1")
        self.assertEqual(found.session_id, session.session_id)

    async def test_resolve_ingest_by_terminal_id_returns_none_for_unsolicited_terminal(
        self,
    ) -> None:
        manager, _ = _manager()
        manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        self.assertIsNone(manager.resolve_ingest_by_terminal_id("some-other-terminal"))

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

    async def test_fail_session_publishes_failed_and_does_not_signal_stop(self) -> None:
        manager, publisher = _manager()
        session = manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="corr-1", logical_channel=1
        )
        await manager.fail_session(session.session_id, reason="ingest_timeout")
        self.assertIsNone(manager.resolve(session.session_id))
        failed = [e for e in publisher.published if isinstance(e, VideoSessionFailed)]
        self.assertEqual(len(failed), 1)
        self.assertEqual(publisher.stop_commands, [])  # device never connected - nothing to stop

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


if __name__ == "__main__":
    unittest.main()
