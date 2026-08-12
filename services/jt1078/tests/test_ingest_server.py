"""`IngestServer` integration tests — real loopback TCP, a synthetic "device" client sending real
extended-RTP bytes, no hardware needed.
"""

import asyncio
import unittest

from src.events.publisher_port import LoggingSessionEventPublisher
from src.ingest.extended_rtp import DATA_TYPE_I_FRAME, FRAME_HEADER_MAGIC, SUBPACKAGE_ATOMIC
from src.ingest.ingest_server import IngestServer
from src.session.session_manager import SessionManager
from src.session.video_session import VideoSessionKind, VideoSessionState


def _build_frame(*, sim_card: str, body: bytes, packet_sequence: int = 0) -> bytes:
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
        + bytes([1])
        + bytes([(DATA_TYPE_I_FRAME << 4) | SUBPACKAGE_ATOMIC])
    )
    trailer = (1000).to_bytes(8, "big") + (0).to_bytes(2, "big") + (40).to_bytes(2, "big")
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


if __name__ == "__main__":
    unittest.main()
