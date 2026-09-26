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
from raad.modules.video.application.ports import LiveStreamType
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
        self.assertEqual(fields["stream_type"], 0)  # default: main stream (ADR-0043)

    async def test_sub_stream_is_signalled_as_stream_type_one(self) -> None:
        """ADR-0043: `LiveStreamType.SUB` maps to JT/T 1078 Table 6.2 stream type 1."""
        adapter, _rpc, broker = _make_adapter(
            {"ok": True, "session_id": "vs-sub", "viewer_token": "tok-sub",
             "ingest_host": "10.0.0.5", "ingest_port": 7910}
        )

        await adapter.start_live(
            device_id="device-1",
            camera_id="camera-1",
            terminal_id="00000000013800138000",
            channel_no=2,
            reference="vs-sub",
            stream_type=LiveStreamType.SUB,
        )

        self.assertEqual(broker.published[0].payload["fields"]["stream_type"], 1)

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


class StartIntercomTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0036 — the only real caller anywhere in this codebase that passes `data_type=2`."""

    async def test_calls_create_intercom_session_and_signals_data_type_two(self) -> None:
        adapter, rpc, broker = _make_adapter(
            {
                "ok": True,
                "session_id": "vs-1",
                "viewer_token": "tok-viewer",
                "uplink_token": "tok-uplink",
                "ingest_host": "10.0.0.5",
                "ingest_port": 7910,
            }
        )

        urls = await adapter.start_intercom(
            device_id="device-1",
            camera_id="camera-1",
            terminal_id="00000000013800138000",
            channel_no=1,
            reference="vs-1",
        )

        self.assertEqual(len(rpc.calls), 1)
        command, payload = rpc.calls[0]
        self.assertEqual(command, "create_intercom_session")
        self.assertEqual(payload["terminal_id"], "00000000013800138000")
        self.assertEqual(payload["logical_channel"], 1)

        self.assertEqual(urls.downlink_url, "ws://relay.example.com:7911/viewer?token=tok-viewer")
        self.assertEqual(urls.uplink_url, "ws://relay.example.com:7911/viewer?token=tok-uplink")

        self.assertEqual(len(broker.published), 1)
        event = broker.published[0]
        self.assertEqual(event.payload["command"], "live_video_request")
        fields = event.payload["fields"]
        self.assertEqual(fields["server_ip"], "10.0.0.5")
        self.assertEqual(fields["tcp_port"], 7910)
        self.assertEqual(fields["logical_channel"], 1)
        self.assertEqual(fields["data_type"], 2)  # two-way intercom, spec Table 6.2

    async def test_start_live_still_hardcodes_data_type_zero_unchanged(self) -> None:
        """ADR-0035's own explicit decision, unchanged by this feature: ordinary live video
        must never regress to requesting intercom by accident."""
        adapter, _rpc, broker = _make_adapter(
            {"ok": True, "session_id": "vs-1", "viewer_token": "tok-1",
             "ingest_host": "10.0.0.5", "ingest_port": 7910}
        )
        await adapter.start_live(
            device_id="d", camera_id="c", terminal_id="t", channel_no=1, reference="vs-1"
        )
        self.assertEqual(broker.published[0].payload["fields"]["data_type"], 0)


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


class SearchRecordingsTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0044 §2. Every field name below is read by name in `device-gateway`'s own
    `_build_query_resource_list`; a rename on either side makes the consumer drop the command
    and log it, which looks exactly like a device that never answered."""

    async def test_publishes_query_resource_list_with_no_relay_rpc(self) -> None:
        """A search starts no media session, so there is nothing to allocate on the relay -
        calling it would consume a session slot for a question."""
        adapter, rpc, broker = _make_adapter({"ok": True})
        start = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)
        end = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)

        await adapter.search_recordings(
            terminal_id="00000000013800138000",
            channel_no=3,
            window_start=start,
            window_end=end,
            reference="search-1",
        )

        self.assertEqual(rpc.calls, [])
        self.assertEqual(len(broker.published), 1)
        event = broker.published[0]
        self.assertEqual(event.payload["command"], "query_resource_list")
        self.assertEqual(event.payload["terminal_id"], "00000000013800138000")
        # The search id travels as the correlation id and comes back on the device's own
        # 0x1205 - this is the only link between the question and its answer.
        self.assertEqual(event.payload["correlation_id"], "search-1")
        fields = event.payload["fields"]
        self.assertEqual(fields["logical_channel"], 3)
        self.assertEqual(fields["start_time"], start.isoformat())
        self.assertEqual(fields["end_time"], end.isoformat())
        for required in ("alarm_flag_filter", "resource_type", "stream_type", "storage_type"):
            self.assertIn(required, fields)


class ControlPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_publishes_playback_control_with_the_gateways_own_field_names(self) -> None:
        adapter, rpc, broker = _make_adapter({"ok": True})

        await adapter.control_playback(
            terminal_id="00000000013800138000",
            channel_no=1,
            reference="vs-1",
            control=1,
        )

        self.assertEqual(rpc.calls, [])
        event = broker.published[0]
        self.assertEqual(event.payload["command"], "playback_control")
        fields = event.payload["fields"]
        # `av_channel`, not `logical_channel`: `_build_playback_control` reads this exact name
        # (spec Table 6.11 calls it the audio/video channel).
        self.assertEqual(fields["av_channel"], 1)
        self.assertEqual(fields["control"], 1)
        self.assertEqual(fields["speed_multiplier"], 0)
        self.assertNotIn("seek_position", fields)

    async def test_seek_position_is_sent_under_the_name_the_gateway_reads(self) -> None:
        adapter, _rpc, broker = _make_adapter({"ok": True})
        position = datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc)

        await adapter.control_playback(
            terminal_id="00000000013800138000",
            channel_no=1,
            reference="vs-1",
            control=5,
            position=position,
        )

        fields = broker.published[0].payload["fields"]
        self.assertEqual(fields["seek_position"], position.isoformat())

    async def test_speed_multiplier_is_forwarded(self) -> None:
        adapter, _rpc, broker = _make_adapter({"ok": True})

        await adapter.control_playback(
            terminal_id="00000000013800138000",
            channel_no=1,
            reference="vs-1",
            control=3,
            speed_multiplier=4,
        )

        self.assertEqual(broker.published[0].payload["fields"]["speed_multiplier"], 4)


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


class RelaySignalledStartTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0046 §3: the relay is the single publisher of a stream's device commands. This adapter
    asks it to be (`relay_signals_device`) and publishes a start itself only for a relay that
    does not confirm it did (rolling-deploy compatibility)."""

    _SIGNALLED = {
        "ok": True,
        "session_id": "vs-1",
        "viewer_token": "tok-1",
        "uplink_token": "up-1",
        "ingest_host": "relay.example.com",
        "ingest_port": 7910,
        "device_signaled": True,
        "stream_id": "s-1",
        "stream_type": "sub",
    }

    async def test_live_asks_the_relay_to_signal_and_passes_the_stream_type(self) -> None:
        adapter, rpc, broker = _make_adapter(self._SIGNALLED)
        await adapter.start_live(
            device_id="device-1",
            camera_id="camera-1",
            terminal_id="00000000013800138000",
            channel_no=3,
            reference="vs-1",
            stream_type=LiveStreamType.SUB,
        )
        _command, payload = rpc.calls[0]
        self.assertTrue(payload["relay_signals_device"])
        self.assertEqual(payload["stream_type"], "sub")
        self.assertEqual(broker.published, [], "the relay already started the device")

    async def test_intercom_and_playback_publish_nothing_when_the_relay_signalled(self) -> None:
        adapter, rpc, broker = _make_adapter(self._SIGNALLED)
        await adapter.start_intercom(
            device_id="device-1",
            camera_id="camera-1",
            terminal_id="00000000013800138000",
            channel_no=1,
            reference="vs-2",
        )
        await adapter.start_playback(
            device_id="device-1",
            camera_id="camera-1",
            terminal_id="00000000013800138000",
            channel_no=1,
            window_start=datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 9, 25, 10, 5, tzinfo=timezone.utc),
            reference="vs-3",
        )
        self.assertTrue(all(payload["relay_signals_device"] for _c, payload in rpc.calls))
        self.assertEqual(broker.published, [])

    async def test_an_older_relay_still_gets_the_start_published_here(self) -> None:
        legacy = {k: v for k, v in self._SIGNALLED.items() if k not in ("device_signaled", "stream_id", "stream_type")}
        adapter, _rpc, broker = _make_adapter(legacy)
        await adapter.start_live(
            device_id="device-1",
            camera_id="camera-1",
            terminal_id="00000000013800138000",
            channel_no=3,
            reference="vs-1",
            stream_type=LiveStreamType.SUB,
        )
        self.assertEqual(len(broker.published), 1)
        self.assertEqual(broker.published[0].payload["fields"]["stream_type"], 1)
