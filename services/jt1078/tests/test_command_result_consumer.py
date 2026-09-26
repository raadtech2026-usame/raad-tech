"""Audit 2026-09-26: a start the device-gateway could not deliver (terminal offline) ends its stream
at once instead of after the 30 s ingest timeout - `SessionManager.handle_start_not_delivered` and
the `CommandResultConsumer` that feeds it."""

import json
import unittest

from src.events.session_events import VideoSessionFailed
from src.session.command_result_consumer import CommandResultConsumer
from src.session.session_manager import SessionManager
from src.session.video_session import StreamType, VideoSessionKind


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[object] = []
        self.commands: list[dict] = []

    async def publish(self, event) -> None:
        self.published.append(event)

    async def publish_stop_command(self, *, terminal_id, correlation_id, command, fields) -> None:
        self.commands.append({"correlation_id": correlation_id, "command": command})


def _manager() -> tuple[SessionManager, RecordingPublisher]:
    publisher = RecordingPublisher()
    return SessionManager(event_publisher=publisher, ingest_target=("203.0.113.5", 7910)), publisher


def _live(manager: SessionManager, session_id: str, channel: int = 1):
    return manager.create_session(
        session_id=session_id,
        terminal_id="00000000014482607571",
        kind=VideoSessionKind.LIVE,
        correlation_id=session_id,
        logical_channel=channel,
        stream_type=StreamType.SUB,
        relay_signals_device=True,
    )


class HandleStartNotDeliveredTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_undelivered_start_fails_the_stream_at_once_without_a_stop(self) -> None:
        manager, publisher = _manager()
        session = _live(manager, "A")
        await manager.flush()
        start_id = publisher.commands[0]["correlation_id"]

        self.assertTrue(await manager.handle_start_not_delivered(start_id))

        self.assertIsNone(manager.resolve("A"))
        self.assertIsNone(manager.resolve_stream(session.stream_id))
        failed = [e for e in publisher.published if isinstance(e, VideoSessionFailed)]
        self.assertEqual([e.reason for e in failed], ["device_offline"])
        self.assertEqual(len(publisher.commands), 1, "no stop for a start that never arrived")

    async def test_a_stale_generation_is_ignored(self) -> None:
        manager, publisher = _manager()
        session = _live(manager, "A")
        await manager.flush()
        stream = manager.resolve_stream(session.stream_id)
        self.assertFalse(await manager.handle_start_not_delivered(f"{stream.stream_id}-g9"))
        self.assertIsNotNone(manager.resolve("A"))

    async def test_a_stop_correlation_is_ignored(self) -> None:
        manager, publisher = _manager()
        session = _live(manager, "A")
        await manager.flush()
        self.assertFalse(await manager.handle_start_not_delivered(f"{session.stream_id}-g1-stop"))
        self.assertIsNotNone(manager.resolve("A"))

    async def test_a_stream_that_already_connected_is_left_alone(self) -> None:
        manager, publisher = _manager()
        session = _live(manager, "A")
        await manager.flush()
        manager.note_ingest_connected(session.stream_id)
        self.assertFalse(await manager.handle_start_not_delivered(f"{session.stream_id}-g1"))
        self.assertIsNotNone(manager.resolve("A"))

    async def test_unknown_or_foreign_ids_are_ignored(self) -> None:
        manager, _ = _manager()
        for correlation_id in ("", "nope", "01M3F3EZJ5X8HPAT4WF6AVEEJW", "abc-gx"):
            self.assertFalse(await manager.handle_start_not_delivered(correlation_id))


class FakeRedis:
    def __init__(self) -> None:
        self.entries: list[tuple[str, dict]] = []
        self.acked: list[str] = []
        self.groups: list[tuple] = []

    def add(self, event_type: str, payload: dict) -> None:
        message_id = str(len(self.entries) + 1)
        self.entries.append(
            (message_id, {"data": json.dumps({"event_type": event_type, "payload": payload})})
        )

    async def xgroup_create(self, name, groupname, id, mkstream) -> None:
        self.groups.append((name, groupname, id))

    async def xreadgroup(self, group, consumer, streams, count, block):
        pending = [(m, f) for m, f in self.entries if m not in self.acked]
        return [("raad:events", pending)] if pending else []

    async def xack(self, name, group, message_id) -> None:
        self.acked.append(message_id)


class CommandResultConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_offline_result_for_a_waiting_start_ends_the_stream(self) -> None:
        manager, publisher = _manager()
        _live(manager, "A")
        await manager.flush()
        redis = FakeRedis()
        redis.add(
            "DeviceCommandResult",
            {
                "terminal_id": "00000000014482607571",
                "correlation_id": publisher.commands[0]["correlation_id"],
                "success": False,
                "reason": "device_offline",
            },
        )
        consumer = CommandResultConsumer(redis, session_manager=manager)
        self.assertEqual(await consumer.poll_once(), 1)
        self.assertIsNone(manager.resolve("A"))
        self.assertEqual(redis.acked, ["1"])
        self.assertEqual(redis.groups, [("raad:events", "jt1078-relay-command-results", "$")])

    async def test_other_events_and_results_are_acked_and_ignored(self) -> None:
        manager, publisher = _manager()
        _live(manager, "A")
        await manager.flush()
        start_id = publisher.commands[0]["correlation_id"]
        redis = FakeRedis()
        redis.add("DevicePositionReported", {"terminal_id": "x"})
        redis.add("DeviceCommandResult", {"correlation_id": start_id, "success": True, "reason": "ok"})
        redis.add("DeviceCommandResult", {"correlation_id": start_id, "success": False, "reason": "timed_out"})
        consumer = CommandResultConsumer(redis, session_manager=manager)
        self.assertEqual(await consumer.poll_once(), 0)
        self.assertEqual(redis.acked, ["1", "2", "3"])
        self.assertIsNotNone(manager.resolve("A"), "a timed-out start may still connect")
