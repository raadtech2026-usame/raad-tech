"""`Jt1078RelayAdapter` tests (JT1078 backend-integration phase) — proves the two-call sequence
(relay RPC + device-start signal), the exact wire shape of the published `Jt1078SignalCommandRequested`
event (must match `services/device-gateway/src/vendors/jt808/commands/
redis_video_signaling_consumer.py`'s own documented contract byte-for-byte, or the consumer would
silently reject every real command), and `stop`'s deliberately-single-call behavior.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.events.base import DomainEvent
from raad.core.events.ports import BrokerPort
from raad.modules.video.infra.adapters import Jt1078RelayAdapter


class FakeRpcClient:
    """Duck-types `Jt1078RelayRpcClient.call` - bypasses real Redis entirely, records calls,
    returns a scripted response. `Jt1078RelayAdapter` never `isinstance`-checks its `rpc_client`
    constructor argument, so no inheritance is needed for this to work."""

    def __init__(self, response: dict) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._response = response

    async def call(self, command: str, payload: dict) -> dict:
        self.calls.append((command, payload))
        return self._response


class FakeBrokerPort(BrokerPort):
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


def _make_adapter(rpc_response: dict) -> tuple[Jt1078RelayAdapter, FakeRpcClient, FakeBrokerPort]:
    rpc = FakeRpcClient(rpc_response)
    broker = FakeBrokerPort()
    adapter = Jt1078RelayAdapter(
        rpc_client=rpc, broker=broker, viewer_base_url="ws://relay.example.com:7911/"
    )
    return adapter, rpc, broker


class StartLiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_create_live_session_with_the_right_fields(self) -> None:
        adapter, rpc, _broker = _make_adapter(
            {"ok": True, "session_id": "vs-1", "viewer_token": "tok-1",
             "ingest_host": "relay.example.com", "ingest_port": 7910}
        )

        await adapter.start_live(
            device_id="device-1",
            camera_id="camera-1",
            terminal_id="00000000013800138000",
            channel_no=2,
            reference="vs-1",
        )

        self.assertEqual(len(rpc.calls), 1)
        command, payload = rpc.calls[0]
        self.assertEqual(command, "create_live_session")
        self.assertEqual(payload["session_id"], "vs-1")
        self.assertEqual(payload["correlation_id"], "vs-1")
        self.assertEqual(payload["terminal_id"], "00000000013800138000")
        self.assertEqual(payload["logical_channel"], 2)
        self.assertEqual(payload["device_id"], "device-1")

    async def test_returns_a_viewer_websocket_url_built_from_the_configured_base(self) -> None:
        adapter, _rpc, _broker = _make_adapter(
            {"ok": True, "session_id": "vs-1", "viewer_token": "tok-xyz",
             "ingest_host": "relay.example.com", "ingest_port": 7910}
        )

        stream_url = await adapter.start_live(
            device_id="d", camera_id="c", terminal_id="t", channel_no=1, reference="vs-1"
        )

        self.assertEqual(stream_url, "ws://relay.example.com:7911/viewer?token=tok-xyz")

    async def test_publishes_a_jt1078_signal_command_requested_event_matching_the_device_gateway_contract(
        self,
    ) -> None:
        adapter, _rpc, broker = _make_adapter(
            {"ok": True, "session_id": "vs-1", "viewer_token": "tok-1",
             "ingest_host": "10.0.0.5", "ingest_port": 7910}
        )

        await adapter.start_live(
            device_id="device-1",
            camera_id="camera-1",
            terminal_id="00000000013800138000",
            channel_no=3,
            reference="vs-1",
        )

        self.assertEqual(len(broker.published), 1)
        event = broker.published[0]
        self.assertIsInstance(event, DomainEvent)
        self.assertEqual(event.event_type, "Jt1078SignalCommandRequested")
        self.assertEqual(event.correlation_id, "vs-1")
        self.assertEqual(event.aggregate_type, "Device")
        self.assertEqual(event.aggregate_id, "00000000013800138000")
        # Exact payload shape `RedisVideoSignalingConsumer._process_one` (device-gateway) expects:
        # {terminal_id, correlation_id, command, fields: {...}}.
        self.assertEqual(event.payload["terminal_id"], "00000000013800138000")
        self.assertEqual(event.payload["correlation_id"], "vs-1")
        self.assertEqual(event.payload["command"], "live_video_request")
        fields = event.payload["fields"]
        self.assertEqual(fields["server_ip"], "10.0.0.5")
        self.assertEqual(fields["tcp_port"], 7910)
        self.assertEqual(fields["udp_port"], 0)
        self.assertEqual(fields["logical_channel"], 3)
        self.assertEqual(fields["data_type"], 0)
        self.assertEqual(fields["stream_type"], 0)

    async def test_device_signal_is_published_only_after_the_relay_confirms_the_session(
        self,
    ) -> None:
        """Ordering matters: signaling a device to stream to ingest coordinates the relay
        hasn't actually allocated yet would be a real bug."""
        adapter, rpc, broker = _make_adapter(
            {"ok": True, "session_id": "vs-1", "viewer_token": "tok-1",
             "ingest_host": "10.0.0.5", "ingest_port": 7910}
        )
        order: list[str] = []
        original_call = rpc.call

        async def tracking_call(command, payload):
            order.append("rpc")
            return await original_call(command, payload)

        rpc.call = tracking_call  # type: ignore[method-assign]

        class TrackingBroker(FakeBrokerPort):
            async def publish(self, event):
                order.append("signal")
                await super().publish(event)

        adapter._broker = TrackingBroker()

        await adapter.start_live(
            device_id="d", camera_id="c", terminal_id="t", channel_no=1, reference="vs-1"
        )

        self.assertEqual(order, ["rpc", "signal"])


class StartPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_create_playback_session_with_the_time_window(self) -> None:
        adapter, rpc, broker = _make_adapter(
            {"ok": True, "session_id": "vs-2", "viewer_token": "tok-2",
             "ingest_host": "10.0.0.5", "ingest_port": 7910}
        )
        start = datetime(2026, 8, 11, 8, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 8, 11, 9, 0, 0, tzinfo=timezone.utc)

        await adapter.start_playback(
            device_id="device-1",
            camera_id="camera-1",
            terminal_id="00000000013800138000",
            channel_no=1,
            window_start=start,
            window_end=end,
            reference="vs-2",
        )

        command, payload = rpc.calls[0]
        self.assertEqual(command, "create_playback_session")
        self.assertEqual(payload["window_start"], start.isoformat())
        self.assertEqual(payload["window_end"], end.isoformat())

        event = broker.published[0]
        self.assertEqual(event.payload["command"], "playback_request")
        self.assertEqual(event.payload["fields"]["start_time"], start.isoformat())
        self.assertEqual(event.payload["fields"]["end_time"], end.isoformat())
        self.assertEqual(event.payload["fields"]["playback_mode"], 0)


class StopTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_only_calls_the_relay_never_publishes_a_second_device_signal(self) -> None:
        """The relay's own SessionManager.end_session already publishes the device stop-signal
        (ADR-0024 §5 point 4) - this adapter must not duplicate it."""
        adapter, rpc, broker = _make_adapter({"ok": True})

        await adapter.stop(reference="vs-1")

        self.assertEqual(rpc.calls, [("end_session", {"session_id": "vs-1"})])
        self.assertEqual(broker.published, [])


if __name__ == "__main__":
    unittest.main()
