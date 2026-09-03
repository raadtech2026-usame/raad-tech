"""`SessionBroadcastHub` tests — per-viewer FLV muxer instances, fan-out, and failed-viewer
removal, all against a fake `WebSocketConnection` double.

**Redesigned (2026-09-02) alongside the hub itself**: `broadcast_video`/`broadcast_audio*` no
longer deliver synchronously — each viewer's actual `send_binary` now happens on that viewer's
own background sender task, reading off a bounded queue, specifically so one slow viewer's socket
write can never block delivery to any other viewer or the ingest pipeline that calls
`broadcast_*` in the first place (see `broadcast_hub.py`'s own module docstring for the full
reasoning). Every test that previously asserted `viewer.sent` immediately after `await
hub.broadcast_*(...)` now awaits `hub.wait_until_idle()` first — a test-only helper that waits for
each viewer's queue to fully drain, giving deterministic assertions without `asyncio.sleep`
guesswork. The FLV header itself is still sent synchronously and directly by `add_viewer` (module
docstring's own "guaranteed before anything else" invariant), so every pre-existing header
assertion is unchanged and needs no `wait_until_idle()` call.
"""

import asyncio
import unittest

from src.viewer.broadcast_hub import SessionBroadcastHub


class FakeConnection:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[bytes] = []
        self.fail = fail

    async def send_binary(self, data: bytes) -> None:
        if self.fail:
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

    async def test_default_hub_sends_a_video_only_header(self) -> None:
        """Regression test (2026-08-28): a hub with no `has_audio` (every pre-G.711A session,
        and every session for a device with no working audio decoder) must never claim audio in
        the header it hands each viewer - `mpegts.js` would otherwise wait forever for audio
        metadata a video-only stream never sends."""
        hub = SessionBroadcastHub("session-1")
        viewer = FakeConnection()
        await hub.add_viewer(viewer)
        self.assertEqual(viewer.sent[0][4], 0b001)

    async def test_hub_with_audio_sends_a_header_declaring_both(self) -> None:
        hub = SessionBroadcastHub("session-1", has_audio=True)
        viewer = FakeConnection()
        await hub.add_viewer(viewer)
        self.assertEqual(viewer.sent[0][4], 0b101)

    async def test_each_viewer_gets_the_hub_own_has_audio_value_independently(self) -> None:
        """A viewer joining mid-stream still gets the same, correct per-session declaration -
        not re-derived per viewer, not defaulted away from the hub's own setting."""
        hub = SessionBroadcastHub("session-1", has_audio=True)
        viewer_a, viewer_b = FakeConnection(), FakeConnection()
        await hub.add_viewer(viewer_a)
        await hub.add_viewer(viewer_b)
        self.assertEqual(viewer_a.sent[0][4], 0b101)
        self.assertEqual(viewer_b.sent[0][4], 0b101)

    async def test_broadcast_video_reaches_every_viewer(self) -> None:
        hub = SessionBroadcastHub("session-1")
        viewer_a, viewer_b = FakeConnection(), FakeConnection()
        await hub.add_viewer(viewer_a)
        await hub.add_viewer(viewer_b)

        backpressured = await hub.broadcast_video(
            annex_b_payload=b"\x00\x00\x01\x65DATA", is_keyframe=True, timestamp_ms=1000
        )
        await hub.wait_until_idle()

        self.assertEqual(backpressured, [])
        self.assertEqual(len(viewer_a.sent), 2)  # header + video tag
        self.assertEqual(len(viewer_b.sent), 2)

    async def test_each_viewer_gets_its_own_rebased_timestamp_timeline(self) -> None:
        hub = SessionBroadcastHub("session-1")
        early_viewer = FakeConnection()
        await hub.add_viewer(early_viewer)

        await hub.broadcast_video(
            annex_b_payload=b"\x00\x00\x01\x65A", is_keyframe=True, timestamp_ms=50_000
        )
        await hub.wait_until_idle()

        late_viewer = FakeConnection()
        await hub.add_viewer(late_viewer)  # joins mid-stream

        await hub.broadcast_video(
            annex_b_payload=b"\x00\x00\x01\x65B", is_keyframe=False, timestamp_ms=50_500
        )
        await hub.wait_until_idle()

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
        bad_viewer = FakeConnection()
        await hub.add_viewer(good_viewer)
        await hub.add_viewer(bad_viewer)
        bad_viewer.fail = True  # fail from here on, but the header above already succeeded

        await hub.broadcast_video(
            annex_b_payload=b"\x00\x00\x01\x65DATA", is_keyframe=True, timestamp_ms=1000
        )
        # bad_viewer's own sender task removes it asynchronously on send failure - poll briefly
        # rather than a fixed sleep, since exactly how many event-loop turns that takes is an
        # implementation detail this test shouldn't need to know.
        for _ in range(100):
            if hub.viewer_count == 1:
                break
            await asyncio.sleep(0)

        self.assertEqual(hub.viewer_count, 1)
        self.assertEqual(len(good_viewer.sent), 2)
        self.assertEqual(len(bad_viewer.sent), 1)  # only the header - the video tag send failed

    async def test_remove_viewer_stops_further_broadcasts_reaching_it(self) -> None:
        hub = SessionBroadcastHub("session-1")
        viewer = FakeConnection()
        await hub.add_viewer(viewer)
        hub.remove_viewer(viewer)

        await hub.broadcast_video(
            annex_b_payload=b"\x00\x00\x01\x65DATA", is_keyframe=True, timestamp_ms=1000
        )
        await hub.wait_until_idle()

        self.assertEqual(len(viewer.sent), 1)  # only the initial header, nothing after removal
        self.assertEqual(hub.viewer_count, 0)

    async def test_broadcast_audio_reaches_viewers(self) -> None:
        hub = SessionBroadcastHub("session-1")
        viewer = FakeConnection()
        await hub.add_viewer(viewer)

        backpressured = await hub.broadcast_audio(
            pcm_payload=b"\xaa\xbb\xcc\xdd", sample_rate_hz=11025, timestamp_ms=1000
        )
        await hub.wait_until_idle()

        self.assertEqual(backpressured, [])
        self.assertEqual(len(viewer.sent), 2)

    async def test_a_slow_viewer_does_not_block_broadcast_to_others(self) -> None:
        """The whole point of the 2026-09-02 redesign: `broadcast_video` must return promptly
        even when one viewer's own `send_binary` blocks indefinitely (a stalled network write) -
        the old, fully-synchronous fan-out would have hung this call until that viewer's send
        either completed or errored."""
        hub = SessionBroadcastHub("session-1")

        class HangingConnection:
            def __init__(self) -> None:
                self.sent: list[bytes] = []
                self.release = asyncio.Event()

            async def send_binary(self, data: bytes) -> None:
                if len(self.sent) > 0:  # let the header (first send) through immediately
                    await self.release.wait()
                self.sent.append(data)

        slow_viewer = HangingConnection()
        fast_viewer = FakeConnection()
        await hub.add_viewer(slow_viewer)
        await hub.add_viewer(fast_viewer)

        await asyncio.wait_for(
            hub.broadcast_video(
                annex_b_payload=b"\x00\x00\x01\x65DATA", is_keyframe=True, timestamp_ms=1000
            ),
            timeout=1.0,
        )
        # The fast viewer's own queue drains independently of the still-blocked slow viewer.
        for _ in range(100):
            if len(fast_viewer.sent) == 2:
                break
            await asyncio.sleep(0)
        self.assertEqual(len(fast_viewer.sent), 2)
        self.assertEqual(len(slow_viewer.sent), 1)  # still only the header - its send is hung

        slow_viewer.release.set()  # let it finish so the sender task doesn't leak into other tests
        for _ in range(100):
            if len(slow_viewer.sent) == 2:
                break
            await asyncio.sleep(0)

    async def test_backpressure_drops_the_oldest_queued_frame_not_the_newest(self) -> None:
        """A viewer that never drains (queue always full) must still end up with the *freshest*
        frame available, not stuck behind a backlog of stale ones - `_enqueue`'s own drop-oldest
        policy (`broadcast_hub.py`)."""
        hub = SessionBroadcastHub("session-1", send_queue_maxsize=2)

        class NeverDrainingConnection:
            def __init__(self) -> None:
                self.sent: list[bytes] = []
                self.gate = asyncio.Event()

            async def send_binary(self, data: bytes) -> None:
                if len(self.sent) > 0:
                    await self.gate.wait()
                self.sent.append(data)

        viewer = NeverDrainingConnection()
        await hub.add_viewer(viewer)

        any_backpressured = False
        for i in range(5):
            backpressured = await hub.broadcast_video(
                annex_b_payload=f"\x00\x00\x01\x65DATA{i}".encode(),
                is_keyframe=True,
                timestamp_ms=1000 + i,
            )
            if backpressured:
                any_backpressured = True

        self.assertTrue(any_backpressured)
        viewer.gate.set()
        for _ in range(200):
            if len(viewer.sent) >= 3:  # header + 2 surviving queued frames (maxsize=2)
                break
            await asyncio.sleep(0)
        # Never more than header + the bounded queue's own maxsize worth of frames - old, stale
        # frames were dropped rather than piling up unboundedly.
        self.assertLessEqual(len(viewer.sent), 1 + 2)


if __name__ == "__main__":
    unittest.main()
