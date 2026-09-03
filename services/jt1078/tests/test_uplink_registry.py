"""`IngestConnectionRegistry`/`IngestConnection` tests (`session/uplink_registry.py`, ADR-0036) —
the relay's own new uplink (operator mic audio -> device) bridge. Fakes `asyncio.StreamWriter`
(only `write`/`drain`/`is_closing` are ever used) so no real socket is needed.
"""

from __future__ import annotations

import unittest

from src.ingest.extended_rtp import DATA_TYPE_AUDIO, parse_one_frame
from src.session.uplink_registry import IngestConnection, IngestConnectionRegistry


class FakeStreamWriter:
    def __init__(self, *, closing: bool = False) -> None:
        self.written: list[bytes] = []
        self.drained = 0
        self._closing = closing

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        self.drained += 1

    def is_closing(self) -> bool:
        return self._closing


class IngestConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_audio_writes_a_valid_extended_rtp_audio_frame(self) -> None:
        writer = FakeStreamWriter()
        connection = IngestConnection(
            writer=writer, sim_card_number="014482607571", logical_channel=1
        )

        ok = await connection.send_audio(b"\xd7\xd4" * 160)

        self.assertTrue(ok)
        self.assertEqual(len(writer.written), 1)
        self.assertEqual(writer.drained, 1)
        frame, _consumed = parse_one_frame(writer.written[0])
        self.assertEqual(frame.data_type, DATA_TYPE_AUDIO)
        self.assertEqual(frame.sim_card_number, "014482607571")
        self.assertEqual(frame.logical_channel, 1)
        self.assertEqual(frame.body, b"\xd7\xd4" * 160)

    async def test_sequence_number_increments_per_frame(self) -> None:
        writer = FakeStreamWriter()
        connection = IngestConnection(
            writer=writer, sim_card_number="014482607571", logical_channel=1
        )
        await connection.send_audio(b"a")
        await connection.send_audio(b"b")
        frame_1, _ = parse_one_frame(writer.written[0])
        frame_2, _ = parse_one_frame(writer.written[1])
        self.assertEqual(frame_1.packet_sequence, 0)
        self.assertEqual(frame_2.packet_sequence, 1)

    async def test_send_audio_on_a_closing_connection_is_a_no_op_not_an_error(self) -> None:
        writer = FakeStreamWriter(closing=True)
        connection = IngestConnection(
            writer=writer, sim_card_number="014482607571", logical_channel=1
        )
        ok = await connection.send_audio(b"x")
        self.assertFalse(ok)
        self.assertEqual(writer.written, [])

    async def test_oversized_body_is_dropped_not_raised(self) -> None:
        """Defense-in-depth regression test (2026-09-02) — the real bug this closes: a browser
        bug (or any future non-conforming client) sending a >950-byte WS uplink message used to
        raise `MalformedExtendedRtpFrameError` straight out of `send_audio`, which
        `ViewerServer._pump_uplink_frames` had no per-message try/except around, killing the
        *whole* uplink WebSocket over one bad frame. `send_audio` must now swallow this, log it,
        and leave the connection fully usable for the next (correctly-sized) frame - this is the
        relay's own defense-in-depth layer, independent of the browser-side chunker fix
        (`frontend/src/shared/audio/g711a.pushAndDrainFrames`) that is this bug's primary fix."""
        writer = FakeStreamWriter()
        connection = IngestConnection(
            writer=writer, sim_card_number="014482607571", logical_channel=1
        )

        ok = await connection.send_audio(b"\x00" * 2048)  # the exact real-world bug shape

        self.assertFalse(ok)
        self.assertEqual(writer.written, [])  # nothing malformed ever reached the wire

        # The connection is not poisoned - a normal, correctly-sized frame right after still works.
        ok = await connection.send_audio(b"\xd7\xd4" * 160)
        self.assertTrue(ok)
        self.assertEqual(len(writer.written), 1)
        frame, _consumed = parse_one_frame(writer.written[0])
        self.assertEqual(frame.body, b"\xd7\xd4" * 160)
        # The sequence counter only advances for frames actually sent, not for the dropped one.
        self.assertEqual(frame.packet_sequence, 0)


class IngestConnectionRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_audio_for_an_unregistered_session_is_a_no_op_not_an_error(self) -> None:
        registry = IngestConnectionRegistry()
        ok = await registry.send_audio("no-such-session", b"x")
        self.assertFalse(ok)

    async def test_registered_session_receives_the_frame(self) -> None:
        registry = IngestConnectionRegistry()
        writer = FakeStreamWriter()
        registry.register(
            "session-1", writer=writer, sim_card_number="014482607571", logical_channel=1
        )

        ok = await registry.send_audio("session-1", b"\xd7\xd4" * 160)

        self.assertTrue(ok)
        self.assertEqual(len(writer.written), 1)

    async def test_unregister_stops_further_forwarding(self) -> None:
        registry = IngestConnectionRegistry()
        writer = FakeStreamWriter()
        registry.register(
            "session-1", writer=writer, sim_card_number="014482607571", logical_channel=1
        )
        registry.unregister("session-1")

        ok = await registry.send_audio("session-1", b"x")

        self.assertFalse(ok)
        self.assertEqual(writer.written, [])

    async def test_two_sessions_are_routed_independently(self) -> None:
        registry = IngestConnectionRegistry()
        writer_a, writer_b = FakeStreamWriter(), FakeStreamWriter()
        registry.register("a", writer=writer_a, sim_card_number="014482607571", logical_channel=1)
        registry.register("b", writer=writer_b, sim_card_number="014482607572", logical_channel=2)

        await registry.send_audio("a", b"for-a")
        await registry.send_audio("b", b"for-b")

        frame_a, _ = parse_one_frame(writer_a.written[0])
        frame_b, _ = parse_one_frame(writer_b.written[0])
        self.assertEqual(frame_a.body, b"for-a")
        self.assertEqual(frame_b.body, b"for-b")


if __name__ == "__main__":
    unittest.main()


def _fields(captured, message: str) -> dict:
    """`log_with_fields` attaches its structured fields as `record.extra_fields`, not to the
    formatted message — assert on those rather than on log text."""
    for record in captured.records:
        if record.getMessage() == message:
            return getattr(record, "extra_fields", {})
    raise AssertionError(f"no {message!r} record was logged")


class UplinkTelemetryTests(unittest.IsolatedAsyncioTestCase):
    """Live-driven (2026-09-03): a real bench press forwarded 135 frames of a silent microphone
    and logged nothing at all, because the only report fired at a flat 250 frames. The uplink's
    own diagnostic must speak up for a short press too, and must always leave one summary line."""

    def _connection(self):
        writer = FakeStreamWriter()
        registry = IngestConnectionRegistry()
        registry.register(
            "s1", writer=writer, sim_card_number="014482607571", logical_channel=1
        )
        return registry, writer

    async def test_first_report_arrives_after_a_short_press(self) -> None:
        registry, _ = self._connection()
        with self.assertLogs("jt1078_relay.session.uplink_registry", level="INFO") as captured:
            for _ in range(25):
                await registry.send_audio("s1", bytes([0xD5]) * 320)
        self.assertTrue(any("uplink_audio_forwarded" in line for line in captured.output))

    async def test_silent_microphone_is_flagged(self) -> None:
        """0xD5 is A-law zero; it decodes to magnitude 8, far below the silence threshold."""
        registry, _ = self._connection()
        with self.assertLogs("jt1078_relay.session.uplink_registry", level="INFO") as captured:
            for _ in range(25):
                await registry.send_audio("s1", bytes([0xD5]) * 320)
        fields = _fields(captured, "uplink_audio_forwarded")
        self.assertTrue(fields["silent"])
        self.assertLess(fields["mean_amplitude"], 32)
        self.assertEqual(fields["payload_type"], 6)

    async def test_real_audio_is_not_flagged_silent(self) -> None:
        registry, _ = self._connection()
        loud = bytes([0x2A, 0xAA] * 160)  # large-segment A-law values, well above the floor
        with self.assertLogs("jt1078_relay.session.uplink_registry", level="INFO") as captured:
            for _ in range(25):
                await registry.send_audio("s1", loud)
        fields = _fields(captured, "uplink_audio_forwarded")
        self.assertFalse(fields["silent"])
        self.assertGreater(fields["mean_amplitude"], 32)

    async def test_unregister_emits_exactly_one_session_summary(self) -> None:
        registry, _ = self._connection()
        for _ in range(5):  # too short to reach the first periodic report
            await registry.send_audio("s1", bytes([0xD5]) * 320)
        with self.assertLogs("jt1078_relay.session.uplink_registry", level="INFO") as captured:
            registry.unregister("s1")
        summaries = [l for l in captured.output if "uplink_audio_session_summary" in l]
        self.assertEqual(len(summaries), 1)

    async def test_unregister_without_any_audio_logs_no_summary(self) -> None:
        registry, _ = self._connection()
        with self.assertNoLogs("jt1078_relay.session.uplink_registry", level="INFO"):
            registry.unregister("s1")
