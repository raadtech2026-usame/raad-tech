"""`IngestServer` integration tests — real loopback TCP, a synthetic "device" client sending real
extended-RTP bytes, no hardware needed.
"""

import asyncio
import unittest

from src.events.publisher_port import LoggingSessionEventPublisher
from src.ingest.extended_rtp import (
    DATA_TYPE_AUDIO,
    DATA_TYPE_I_FRAME,
    FRAME_HEADER_MAGIC,
    SUBPACKAGE_ATOMIC,
)
from src.ingest.ingest_server import IngestServer
from src.session.session_manager import SessionManager
from src.session.uplink_registry import IngestConnectionRegistry
from src.session.video_session import VideoSessionKind, VideoSessionState


def _build_frame(
    *, sim_card: str, body: bytes, packet_sequence: int = 0, logical_channel: int = 1
) -> bytes:
    assert len(sim_card) == 12
    sim_bytes = bytes(
        ((int(sim_card[i]) << 4) | int(sim_card[i + 1])) for i in range(0, 12, 2)
    )
    header = (
        FRAME_HEADER_MAGIC.to_bytes(4, "big")
        + bytes([0b0010_0001])
        + bytes([0b1000_0001])
        + packet_sequence.to_bytes(2, "big")
        + sim_bytes
        + bytes([logical_channel])
        + bytes([(DATA_TYPE_I_FRAME << 4) | SUBPACKAGE_ATOMIC])
    )
    trailer = (1000).to_bytes(8, "big") + (0).to_bytes(2, "big") + (40).to_bytes(2, "big")
    return header + trailer + len(body).to_bytes(2, "big") + body


def _build_audio_frame(
    *, sim_card: str, body: bytes, packet_sequence: int = 0, logical_channel: int = 1
) -> bytes:
    """Audio's own shorter trailer (timestamp only, no I/P-frame-interval fields) - mirrors
    `test_relay.py`'s own `_build_device_audio_frame` helper exactly."""
    assert len(sim_card) == 12
    sim_bytes = bytes(
        ((int(sim_card[i]) << 4) | int(sim_card[i + 1])) for i in range(0, 12, 2)
    )
    header = (
        FRAME_HEADER_MAGIC.to_bytes(4, "big")
        + bytes([0b0010_0001])
        + bytes([0b1000_0001])
        + packet_sequence.to_bytes(2, "big")
        + sim_bytes
        + bytes([logical_channel])
        + bytes([(DATA_TYPE_AUDIO << 4) | SUBPACKAGE_ATOMIC])
    )
    trailer = (1000).to_bytes(8, "big")
    return header + trailer + len(body).to_bytes(2, "big") + body


class IngestServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session_manager = SessionManager(event_publisher=LoggingSessionEventPublisher())
        self.received: list[tuple[str, bytes]] = []

        async def on_frame(session_id, reassembled):
            self.received.append((session_id, reassembled.body))

        self.ingest = IngestServer(
            host="127.0.0.1", port=0, session_manager=self.session_manager, on_reassembled_frame=on_frame
        )
        await self.ingest.start()

    async def asyncTearDown(self) -> None:
        await self.ingest.stop()

    async def test_frame_from_a_terminal_with_a_requested_session_is_correlated_and_activates_it(
        self,
    ) -> None:
        session = self.session_manager.create_session(
            terminal_id="138001380000",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-1",
            logical_channel=1,
        )

        reader, writer = await asyncio.open_connection("127.0.0.1", self.ingest.bound_port)
        writer.write(_build_frame(sim_card="138001380000", body=b"VIDEO-DATA"))
        await writer.drain()
        await asyncio.sleep(0.1)

        self.assertEqual(self.received, [(session.session_id, b"VIDEO-DATA")])
        self.assertEqual(session.state, VideoSessionState.ACTIVE)
        writer.close()

    async def test_unsolicited_connection_from_an_unknown_terminal_is_rejected(self) -> None:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ingest.bound_port)
        writer.write(_build_frame(sim_card="999999999999", body=b"UNSOLICITED"))
        await writer.drain()
        await asyncio.sleep(0.1)

        self.assertEqual(self.received, [])
        data = await asyncio.wait_for(reader.read(1), timeout=2.0)
        self.assertEqual(data, b"")  # server closed the connection
        writer.close()

    async def test_multiple_frames_on_one_connection_all_reach_the_same_session(self) -> None:
        session = self.session_manager.create_session(
            terminal_id="138001380000",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-1",
            logical_channel=1,
        )
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ingest.bound_port)
        writer.write(_build_frame(sim_card="138001380000", body=b"F1", packet_sequence=0))
        writer.write(_build_frame(sim_card="138001380000", body=b"F2", packet_sequence=1))
        await writer.drain()
        await asyncio.sleep(0.1)

        self.assertEqual(
            self.received, [(session.session_id, b"F1"), (session.session_id, b"F2")]
        )
        writer.close()

    async def test_two_channels_of_the_same_device_ingest_independently_and_correctly(
        self,
    ) -> None:
        """Regression test for a real, live-found bug (2026-08-22, physical bench unit,
        multi-camera grid): two cameras on the same device are live-requested simultaneously,
        giving two `REQUESTED` sessions that share one `terminal_id` and differ only by
        `logical_channel`. Previously, an ingest frame was correlated to a session by
        `terminal_id` alone, so both physical ingest connections resolved to whichever session
        happened to be first in iteration order — this test proves each connection's frames now
        reach its own channel's session, never the other one's."""
        session_ch1 = self.session_manager.create_session(
            terminal_id="138001380000",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-1",
            logical_channel=1,
        )
        session_ch2 = self.session_manager.create_session(
            terminal_id="138001380000",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-2",
            logical_channel=2,
        )

        reader1, writer1 = await asyncio.open_connection("127.0.0.1", self.ingest.bound_port)
        reader2, writer2 = await asyncio.open_connection("127.0.0.1", self.ingest.bound_port)
        writer2.write(_build_frame(sim_card="138001380000", body=b"CH2-DATA", logical_channel=2))
        await writer2.drain()
        writer1.write(_build_frame(sim_card="138001380000", body=b"CH1-DATA", logical_channel=1))
        await writer1.drain()
        await asyncio.sleep(0.1)

        self.assertIn((session_ch1.session_id, b"CH1-DATA"), self.received)
        self.assertIn((session_ch2.session_id, b"CH2-DATA"), self.received)
        self.assertEqual(session_ch1.state, VideoSessionState.ACTIVE)
        self.assertEqual(session_ch2.state, VideoSessionState.ACTIVE)
        writer1.close()
        writer2.close()

    async def test_intercom_and_live_ingest_on_the_same_channel_correlate_to_the_right_session(
        self,
    ) -> None:
        """Bug 2 regression test — the real, live-reproduced production scenario production
        session `01M1EQZE1D1831D74MHXCTDGQP` exhibited: a LIVE session already `ACTIVE` on a
        device's channel 1 (an operator viewing the multi-camera grid) while an INTERCOM session
        is `REQUESTED` on that identical `(terminal_id, logical_channel)` (ADR-0036 §6's own
        default first-camera channel). Two independent, real TCP ingest connections for the same
        device/channel must each resolve to the session matching their own frame's `data_type` —
        never both silently landing on whichever session was created first."""
        live_session = self.session_manager.create_session(
            terminal_id="138001380000",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-live",
            logical_channel=1,
        )
        intercom_session = self.session_manager.create_session(
            terminal_id="138001380000",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="corr-intercom",
            logical_channel=1,
        )

        video_reader, video_writer = await asyncio.open_connection(
            "127.0.0.1", self.ingest.bound_port
        )
        video_writer.write(
            _build_frame(sim_card="138001380000", body=b"VIDEO-DATA", logical_channel=1)
        )
        await video_writer.drain()

        audio_reader, audio_writer = await asyncio.open_connection(
            "127.0.0.1", self.ingest.bound_port
        )
        audio_writer.write(
            _build_audio_frame(sim_card="138001380000", body=b"AUDIO-DATA", logical_channel=1)
        )
        await audio_writer.drain()
        await asyncio.sleep(0.1)

        self.assertIn((live_session.session_id, b"VIDEO-DATA"), self.received)
        self.assertIn((intercom_session.session_id, b"AUDIO-DATA"), self.received)
        self.assertEqual(live_session.state, VideoSessionState.ACTIVE)
        self.assertEqual(intercom_session.state, VideoSessionState.ACTIVE)
        video_writer.close()
        audio_writer.close()

    async def test_stop_closes_active_ingest_connections(self) -> None:
        self.session_manager.create_session(
            terminal_id="138001380000",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-1",
            logical_channel=1,
        )
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ingest.bound_port)
        writer.write(_build_frame(sim_card="138001380000", body=b"X"))
        await writer.drain()
        await asyncio.sleep(0.05)

        await self.ingest.stop()

        data = await asyncio.wait_for(reader.read(1), timeout=2.0)
        self.assertEqual(data, b"")
        writer.close()


class IngestDisconnectWiringTests(unittest.IsolatedAsyncioTestCase):
    """Proves the wiring end to end over a real loopback socket: the device closing its own
    media connection tears the session down immediately, instead of leaving it ACTIVE until the
    idle sweep notices ~60s later. Packet-captured live 2026-09-02 - after a radio-link outage
    the physical MDVR sends FIN on every JT/T 1078 connection rather than resuming."""

    async def asyncSetUp(self) -> None:
        self.session_manager = SessionManager(event_publisher=LoggingSessionEventPublisher())
        self.frames: list = []

        async def on_frame(session_id, frame) -> None:
            self.frames.append((session_id, frame))

        self.ingest = IngestServer(
            host="127.0.0.1", port=0, session_manager=self.session_manager,
            on_reassembled_frame=on_frame,
        )
        await self.ingest.start()

    async def asyncTearDown(self) -> None:
        await self.ingest.stop()

    async def test_device_closing_its_connection_ends_the_active_session(self) -> None:
        session = self.session_manager.create_session(
            terminal_id="138001380000",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-1",
            logical_channel=1,
        )
        _reader, writer = await asyncio.open_connection("127.0.0.1", self.ingest.bound_port)
        writer.write(_build_frame(sim_card="138001380000", body=b"F1", packet_sequence=0))
        await writer.drain()
        await asyncio.sleep(0.1)
        self.assertIsNotNone(self.session_manager.resolve(session.session_id))

        # The device hangs up - exactly what the bench unit does after a link outage.
        writer.close()
        await asyncio.sleep(0.2)

        self.assertIsNone(
            self.session_manager.resolve(session.session_id),
            "session should be torn down on the device's own close, not left for the idle sweep",
        )


class UplinkRegistryWiringTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0036 — `IngestServer` registers/unregisters a device's own live ingest socket with
    `IngestConnectionRegistry` at exactly the same moments it correlates/loses that connection."""

    async def asyncSetUp(self) -> None:
        self.session_manager = SessionManager(event_publisher=LoggingSessionEventPublisher())
        self.uplink_registry = IngestConnectionRegistry()

        async def on_frame(session_id, reassembled):
            pass

        self.ingest = IngestServer(
            host="127.0.0.1",
            port=0,
            session_manager=self.session_manager,
            on_reassembled_frame=on_frame,
            uplink_registry=self.uplink_registry,
        )
        await self.ingest.start()

    async def asyncTearDown(self) -> None:
        await self.ingest.stop()

    async def test_first_frame_registers_the_connection_for_uplink(self) -> None:
        session = self.session_manager.create_session(
            terminal_id="138001380000",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="corr-1",
            logical_channel=1,
        )
        _reader, writer = await asyncio.open_connection("127.0.0.1", self.ingest.bound_port)
        writer.write(_build_frame(sim_card="138001380000", body=b"AUDIO"))
        await writer.drain()
        await asyncio.sleep(0.1)

        ok = await self.uplink_registry.send_audio(session.session_id, b"\xd7\xd4" * 160)
        self.assertTrue(ok)
        writer.close()

    async def test_connection_close_unregisters_it(self) -> None:
        session = self.session_manager.create_session(
            terminal_id="138001380000",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="corr-1",
            logical_channel=1,
        )
        _reader, writer = await asyncio.open_connection("127.0.0.1", self.ingest.bound_port)
        writer.write(_build_frame(sim_card="138001380000", body=b"AUDIO"))
        await writer.drain()
        await asyncio.sleep(0.1)

        writer.close()
        await asyncio.sleep(0.1)

        ok = await self.uplink_registry.send_audio(session.session_id, b"x")
        self.assertFalse(ok)

    async def test_unsolicited_connection_never_registers(self) -> None:
        _reader, writer = await asyncio.open_connection("127.0.0.1", self.ingest.bound_port)
        writer.write(_build_frame(sim_card="999999999999", body=b"X"))
        await writer.drain()
        await asyncio.sleep(0.1)

        ok = await self.uplink_registry.send_audio("no-such-session", b"x")
        self.assertFalse(ok)
        writer.close()


if __name__ == "__main__":
    unittest.main()
