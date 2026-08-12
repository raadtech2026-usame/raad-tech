"""`SessionBroadcastHub` tests — per-viewer FLV muxer instances, fan-out, and failed-viewer
removal, all against a fake `WebSocketConnection` double."""

import unittest

from src.viewer.broadcast_hub import SessionBroadcastHub


class FakeConnection:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[bytes] = []
        self._fail = fail

    async def send_binary(self, data: bytes) -> None:
        if self._fail:
            raise ConnectionResetError("simulated disconnect")
        self.sent.append(data)


class SessionBroadcastHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_viewer_sends_the_flv_header_immediately(self) -> None:
        hub = SessionBroadcastHub("session-1")
        viewer = FakeConnection()
        await hub.add_viewer(viewer)
        self.assertEqual(len(viewer.sent), 1)
        self.assertTrue(viewer.sent[0].startswith(b"FLV"))
        self.assertEqual(hub.viewer_count, 1)

    async def test_broadcast_video_reaches_every_viewer(self) -> None:
        hub = SessionBroadcastHub("session-1")
        viewer_a, viewer_b = FakeConnection(), FakeConnection()
        await hub.add_viewer(viewer_a)
        await hub.add_viewer(viewer_b)

        failed = await hub.broadcast_video(
            annex_b_payload=b"\x00\x00\x01\x65DATA", is_keyframe=True, timestamp_ms=1000
        )

        self.assertEqual(failed, [])
        self.assertEqual(len(viewer_a.sent), 2)  # header + video tag
        self.assertEqual(len(viewer_b.sent), 2)

    async def test_each_viewer_gets_its_own_rebased_timestamp_timeline(self) -> None:
        hub = SessionBroadcastHub("session-1")
        early_viewer = FakeConnection()
        await hub.add_viewer(early_viewer)

        await hub.broadcast_video(
            annex_b_payload=b"\x00\x00\x01\x65A", is_keyframe=True, timestamp_ms=50_000
        )

        late_viewer = FakeConnection()
        await hub.add_viewer(late_viewer)  # joins mid-stream

        await hub.broadcast_video(
            annex_b_payload=b"\x00\x00\x01\x65B", is_keyframe=False, timestamp_ms=50_500
        )

        # early_viewer's second video tag is 500ms after its own first frame (base 50_000)
        early_second_tag = early_viewer.sent[2]
        early_ts = int.from_bytes(early_second_tag[4:7], "big")
        self.assertEqual(early_ts, 500)

        # late_viewer's first video tag rebases to 0, since it joined right before this frame
        late_first_tag = late_viewer.sent[1]
        late_ts = int.from_bytes(late_first_tag[4:7], "big")
        self.assertEqual(late_ts, 0)

    async def test_a_failing_viewer_is_dropped_without_affecting_others(self) -> None:
        hub = SessionBroadcastHub("session-1")
        good_viewer = FakeConnection()
        bad_viewer = FakeConnection(fail=True)
        await hub.add_viewer(good_viewer)
        hub._viewers[bad_viewer] = hub._viewers[good_viewer].__class__()  # bypass add_viewer's own send

        failed = await hub.broadcast_video(
            annex_b_payload=b"\x00\x00\x01\x65DATA", is_keyframe=True, timestamp_ms=1000
        )

        self.assertEqual(failed, [bad_viewer])
        self.assertEqual(hub.viewer_count, 1)
        self.assertEqual(len(good_viewer.sent), 2)

    async def test_remove_viewer_stops_further_broadcasts_reaching_it(self) -> None:
        hub = SessionBroadcastHub("session-1")
        viewer = FakeConnection()
        await hub.add_viewer(viewer)
        hub.remove_viewer(viewer)

        await hub.broadcast_video(
            annex_b_payload=b"\x00\x00\x01\x65DATA", is_keyframe=True, timestamp_ms=1000
        )

        self.assertEqual(len(viewer.sent), 1)  # only the initial header, nothing after removal
        self.assertEqual(hub.viewer_count, 0)

    async def test_broadcast_audio_reaches_viewers(self) -> None:
        hub = SessionBroadcastHub("session-1")
        viewer = FakeConnection()
        await hub.add_viewer(viewer)

        failed = await hub.broadcast_audio(aac_payload=b"\xaa\xbb", timestamp_ms=1000)

        self.assertEqual(failed, [])
        self.assertEqual(len(viewer.sent), 2)


if __name__ == "__main__":
    unittest.main()
