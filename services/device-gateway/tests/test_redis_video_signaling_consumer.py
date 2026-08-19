"""`RedisVideoSignalingConsumer` tests — mirrors `test_redis_device_registry_consumer.py`'s fake
Redis Streams double exactly. Verifies the wire contract this consumer's own module docstring
defines, and that a real `CommandSender` actually gets called with the right message id/body for
each of the seven supported command kinds (six JT/T 1078 video-signaling kinds plus ADR-0030's
`query_av_attributes` channel-discovery kind)."""

import json
import unittest
from datetime import datetime, timezone

from src.vendors.jt808.commands.command_sender import CommandSender
from src.vendors.jt808.commands.pending_commands import PendingCommandTracker
from src.vendors.jt808.commands.redis_video_signaling_consumer import (
    RedisVideoSignalingConsumer,
)
from src.vendors.jt808.dispatcher import message_ids
from src.vendors.jt808.dispatcher.dispatcher import OutboundSerialCounter
from src.vendors.jt808.protocol.parser import PacketParser
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry

_PHONE = "00000000013800138000"


class FakeRedisConsumerGroupStream:
    def __init__(self) -> None:
        self._next_id = 1
        self.entries: list[tuple[str, dict[str, str]]] = []
        self.groups: set[tuple[str, str]] = set()
        self.acked: list[str] = []

    def add_event(self, *, event_type: str, payload: dict) -> None:
        message_id = str(self._next_id)
        self._next_id += 1
        data = json.dumps(
            {
                "event_id": f"evt-{message_id}",
                "event_type": event_type,
                "version": 1,
                "occurred_at": "2026-08-11T10:00:00+00:00",
                "org_id": "org-1",
                "correlation_id": payload.get("correlation_id"),
                "payload": payload,
                "aggregate_type": "Device",
                "aggregate_id": payload.get("terminal_id"),
            }
        )
        self.entries.append((message_id, {"data": data}))

    async def xgroup_create(self, name, groupname, id, mkstream) -> None:
        key = (name, groupname)
        if key in self.groups:
            raise Exception("BUSYGROUP Consumer Group name already exists")
        self.groups.add(key)

    async def xreadgroup(self, group_name, consumer_name, streams, count, block):
        (stream_name, _marker) = next(iter(streams.items()))
        pending = [
            (message_id, fields)
            for message_id, fields in self.entries
            if message_id not in self.acked
        ]
        batch = pending[:count]
        if not batch:
            return []
        return [(stream_name, batch)]

    async def xack(self, name, groupname, message_id) -> None:
        self.acked.append(message_id)


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)


async def _noop_close(connection_id: str, reason: str) -> None:
    return None


async def _make_command_sender_with_authenticated_terminal():
    device_sessions = DeviceSessionManager(
        registry=DeviceSessionRegistry(), close_connection=_noop_close
    )
    await device_sessions.create(
        connection_id="conn-1",
        terminal_id=_PHONE,
        device_id="device-1",
        vehicle_id="vehicle-1",
        organization_id="org-1",
    )
    sent_frames: list[tuple[str, bytes]] = []

    async def _send(connection_id: str, frame: bytes) -> None:
        sent_frames.append((connection_id, frame))

    command_sender = CommandSender(
        device_sessions=device_sessions,
        send=_send,
        serial_counter=OutboundSerialCounter(),
        pending=PendingCommandTracker(),
        event_publisher=RecordingEventPublisher(),
    )
    return command_sender, sent_frames


class RedisVideoSignalingConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_video_request_is_forwarded_as_0x9101(self) -> None:
        command_sender, sent_frames = await _make_command_sender_with_authenticated_terminal()
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="Jt1078SignalCommandRequested",
            payload={
                "terminal_id": _PHONE,
                "correlation_id": "corr-1",
                "command": "live_video_request",
                "fields": {
                    "server_ip": "10.0.0.5",
                    "tcp_port": 7900,
                    "udp_port": 7901,
                    "logical_channel": 1,
                    "data_type": 0,
                    "stream_type": 0,
                },
            },
        )
        consumer = RedisVideoSignalingConsumer(redis, command_sender=command_sender)

        forwarded = await consumer.poll_once()

        self.assertEqual(forwarded, 1)
        self.assertEqual(redis.acked, ["1"])
        self.assertEqual(len(sent_frames), 1)
        _, frame = sent_frames[0]
        message = PacketParser().parse(frame[1:-1], received_at=datetime.now(timezone.utc))
        self.assertEqual(message.message_id, message_ids.LIVE_VIDEO_REQUEST)
        self.assertEqual(message.terminal_id, _PHONE)

    async def test_playback_request_is_forwarded_as_0x9201(self) -> None:
        command_sender, sent_frames = await _make_command_sender_with_authenticated_terminal()
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="Jt1078SignalCommandRequested",
            payload={
                "terminal_id": _PHONE,
                "correlation_id": "corr-2",
                "command": "playback_request",
                "fields": {
                    "server_ip": "10.0.0.5",
                    "tcp_port": 7910,
                    "udp_port": 0,
                    "logical_channel": 1,
                    "av_type": 0,
                    "stream_type": 0,
                    "storage_type": 0,
                    "playback_mode": 0,
                    "start_time": "2026-08-11T08:00:00+00:00",
                    "end_time": "2026-08-11T09:00:00+00:00",
                },
            },
        )
        consumer = RedisVideoSignalingConsumer(redis, command_sender=command_sender)

        forwarded = await consumer.poll_once()

        self.assertEqual(forwarded, 1)
        message = PacketParser().parse(
            sent_frames[0][1][1:-1], received_at=datetime.now(timezone.utc)
        )
        self.assertEqual(message.message_id, message_ids.PLAYBACK_REQUEST)

    async def test_query_resource_list_with_no_time_window_is_forwarded_as_0x9205(self) -> None:
        command_sender, sent_frames = await _make_command_sender_with_authenticated_terminal()
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="Jt1078SignalCommandRequested",
            payload={
                "terminal_id": _PHONE,
                "correlation_id": "corr-3",
                "command": "query_resource_list",
                "fields": {
                    "logical_channel": 0,
                    "resource_type": 3,
                    "stream_type": 0,
                    "storage_type": 0,
                },
            },
        )
        consumer = RedisVideoSignalingConsumer(redis, command_sender=command_sender)

        forwarded = await consumer.poll_once()

        self.assertEqual(forwarded, 1)
        message = PacketParser().parse(
            sent_frames[0][1][1:-1], received_at=datetime.now(timezone.utc)
        )
        self.assertEqual(message.message_id, message_ids.QUERY_RESOURCE_LIST)
        self.assertEqual(message.body[1:7], b"\x00" * 6)  # no start-time constraint

    async def test_query_av_attributes_is_forwarded_as_0x9003_with_empty_body(self) -> None:
        # ADR-0030 — the automatic channel-discovery trigger reuses this exact consumer/wire
        # contract, one more entry in _BUILDERS, not a new consumer or event type.
        command_sender, sent_frames = await _make_command_sender_with_authenticated_terminal()
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="Jt1078SignalCommandRequested",
            payload={
                "terminal_id": _PHONE,
                "correlation_id": "corr-4",
                "command": "query_av_attributes",
                "fields": {},
            },
        )
        consumer = RedisVideoSignalingConsumer(redis, command_sender=command_sender)

        forwarded = await consumer.poll_once()

        self.assertEqual(forwarded, 1)
        message = PacketParser().parse(
            sent_frames[0][1][1:-1], received_at=datetime.now(timezone.utc)
        )
        self.assertEqual(message.message_id, message_ids.QUERY_AV_ATTRIBUTES)
        self.assertEqual(message.body, b"")

    async def test_irrelevant_event_type_is_acked_but_not_forwarded(self) -> None:
        command_sender, sent_frames = await _make_command_sender_with_authenticated_terminal()
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(event_type="DeviceOnline", payload={"terminal_id": _PHONE})
        consumer = RedisVideoSignalingConsumer(redis, command_sender=command_sender)

        forwarded = await consumer.poll_once()

        self.assertEqual(forwarded, 0)
        self.assertEqual(sent_frames, [])
        self.assertEqual(redis.acked, ["1"])

    async def test_unknown_command_kind_is_acked_but_not_forwarded(self) -> None:
        command_sender, sent_frames = await _make_command_sender_with_authenticated_terminal()
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="Jt1078SignalCommandRequested",
            payload={
                "terminal_id": _PHONE,
                "correlation_id": "corr-4",
                "command": "not_a_real_command",
                "fields": {},
            },
        )
        consumer = RedisVideoSignalingConsumer(redis, command_sender=command_sender)

        forwarded = await consumer.poll_once()

        self.assertEqual(forwarded, 0)
        self.assertEqual(sent_frames, [])
        self.assertEqual(redis.acked, ["1"])

    async def test_malformed_fields_is_acked_but_not_forwarded_and_does_not_raise(self) -> None:
        command_sender, sent_frames = await _make_command_sender_with_authenticated_terminal()
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="Jt1078SignalCommandRequested",
            payload={
                "terminal_id": _PHONE,
                "correlation_id": "corr-5",
                "command": "live_video_request",
                "fields": {"server_ip": "10.0.0.5"},  # missing required keys
            },
        )
        consumer = RedisVideoSignalingConsumer(redis, command_sender=command_sender)

        forwarded = await consumer.poll_once()

        self.assertEqual(forwarded, 0)
        self.assertEqual(sent_frames, [])
        self.assertEqual(redis.acked, ["1"])

    async def test_missing_correlation_id_is_acked_but_not_forwarded(self) -> None:
        command_sender, sent_frames = await _make_command_sender_with_authenticated_terminal()
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="Jt1078SignalCommandRequested",
            payload={
                "terminal_id": _PHONE,
                "command": "live_video_request",
                "fields": {
                    "server_ip": "10.0.0.5",
                    "tcp_port": 1,
                    "udp_port": 2,
                    "logical_channel": 1,
                    "data_type": 0,
                    "stream_type": 0,
                },
            },
        )
        consumer = RedisVideoSignalingConsumer(redis, command_sender=command_sender)

        forwarded = await consumer.poll_once()

        self.assertEqual(forwarded, 0)
        self.assertEqual(sent_frames, [])

    async def test_group_already_exists_does_not_raise(self) -> None:
        command_sender, _ = await _make_command_sender_with_authenticated_terminal()
        redis = FakeRedisConsumerGroupStream()
        consumer = RedisVideoSignalingConsumer(redis, command_sender=command_sender)
        await consumer.poll_once()
        await consumer.poll_once()  # second call must not raise on BUSYGROUP


if __name__ == "__main__":
    unittest.main()
