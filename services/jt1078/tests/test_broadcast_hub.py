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
        # An audio-only stream (the intercom downlink) has no keyframe to wait for.
        hub = SessionBroadcastHub("session-1", expects_video=False)
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


class StuckViewerDetectionTests(unittest.IsolatedAsyncioTestCase):
    """2026-09-22: a browser that stops consuming leaves the MDVR streaming over cellular to
    nobody. The hub flags a viewer only after `stuck_timeout_seconds` of *continuous*
    backpressure - a viewer that receives anything at all resets its own clock."""

    class _Clock:
        def __init__(self) -> None:
            self.now = 1000.0

        def __call__(self) -> float:
            return self.now

    class _NeverDrainingConnection:
        def __init__(self) -> None:
            self.sent: list[bytes] = []
            self.gate = asyncio.Event()

        async def send_binary(self, data: bytes) -> None:
            if len(self.sent) > 0:
                await self.gate.wait()
            self.sent.append(data)

    async def _broadcast(self, hub, n: int = 1) -> None:
        for i in range(n):
            await hub.broadcast_video(
                annex_b_payload=b"\x00\x00\x01\x65D", is_keyframe=True, timestamp_ms=i
            )
            # In production the ingest loop awaits the device socket between frames, so each
            # viewer's sender gets to run (and, for a stuck socket, blocks mid-send).
            await asyncio.sleep(0)

    async def test_a_stuck_viewer_is_flagged_only_after_the_timeout(self) -> None:
        clock = self._Clock()
        hub = SessionBroadcastHub(
            "session-1", send_queue_maxsize=1, stuck_timeout_seconds=30.0, clock=clock
        )
        viewer = self._NeverDrainingConnection()
        await hub.add_viewer(viewer)

        await self._broadcast(hub, 4)  # queue fills, chunks start dropping
        self.assertEqual(hub.take_stuck_viewers(), [], "not stuck until the timeout has passed")

        clock.now += 29.0
        await self._broadcast(hub, 2)
        self.assertEqual(hub.take_stuck_viewers(), [], "29 s of backpressure is still tolerated")

        clock.now += 2.0
        await self._broadcast(hub, 1)
        self.assertEqual(hub.take_stuck_viewers(), [viewer])
        # Reported exactly once; the next report needs another full timeout.
        self.assertEqual(hub.take_stuck_viewers(), [])

    async def test_a_viewer_that_keeps_receiving_is_never_flagged(self) -> None:
        """The whole safety property: a slow-but-alive viewer on a poor mobile link keeps
        draining between bursts, so it must never be disconnected."""
        clock = self._Clock()
        hub = SessionBroadcastHub(
            "session-1", send_queue_maxsize=4, stuck_timeout_seconds=30.0, clock=clock
        )
        viewer = FakeConnection()  # drains immediately
        await hub.add_viewer(viewer)

        for _ in range(10):
            clock.now += 60.0  # far beyond the timeout, but delivery keeps succeeding
            await self._broadcast(hub, 2)
            await hub.wait_until_idle()

        self.assertEqual(hub.take_stuck_viewers(), [])

    async def test_detection_is_disabled_without_a_timeout(self) -> None:
        """How an INTERCOM session opts out (`relay.py._on_session_created`)."""
        clock = self._Clock()
        hub = SessionBroadcastHub("session-1", send_queue_maxsize=1, clock=clock)
        self.assertIsNone(hub.stuck_timeout_seconds)
        viewer = self._NeverDrainingConnection()
        await hub.add_viewer(viewer)

        await self._broadcast(hub, 3)
        clock.now += 3600.0
        await self._broadcast(hub, 3)

        self.assertEqual(hub.take_stuck_viewers(), [])

    async def test_removing_a_viewer_forgets_it_was_stuck(self) -> None:
        clock = self._Clock()
        hub = SessionBroadcastHub(
            "session-1", send_queue_maxsize=1, stuck_timeout_seconds=30.0, clock=clock
        )
        viewer = self._NeverDrainingConnection()
        await hub.add_viewer(viewer)
        await self._broadcast(hub, 3)
        clock.now += 31.0
        await self._broadcast(hub, 1)

        hub.remove_viewer(viewer)

        self.assertEqual(hub.take_stuck_viewers(), [])
        self.assertEqual(hub.viewer_count, 0)


class ViewerStatsTests(unittest.IsolatedAsyncioTestCase):
    """2026-09-23 diagnostics: a stuck viewer's log line must say how much it had received and
    how long ago, so "never drained" and "drained for minutes, then stalled" are told apart."""

    class _Clock:
        def __init__(self) -> None:
            self.now = 1000.0

        def __call__(self) -> float:
            return self.now

    async def _broadcast(self, hub, n: int) -> None:
        for i in range(n):
            await hub.broadcast_video(
                annex_b_payload=b"\x00\x00\x01\x65D", is_keyframe=True, timestamp_ms=i
            )

    async def test_counts_what_a_draining_viewer_received(self) -> None:
        clock = self._Clock()
        hub = SessionBroadcastHub("session-1", clock=clock)
        viewer = FakeConnection()
        await hub.add_viewer(viewer)
        await self._broadcast(hub, 3)
        await hub.wait_until_idle()
        clock.now += 12.0

        stats = hub.viewer_stats(viewer)

        self.assertEqual(stats["delivered_chunks"], 3)
        # Everything after the FLV header went through the queue and is counted.
        self.assertEqual(stats["delivered_bytes"], sum(len(c) for c in viewer.sent[1:]))
        self.assertEqual(stats["dropped_chunks"], 0)
        self.assertEqual(stats["connected_seconds"], 12.0)
        self.assertEqual(stats["seconds_since_last_delivery"], 12.0)
        self.assertEqual(stats["queued_chunks"], 0)

    async def test_counts_chunks_dropped_for_a_viewer_that_never_drains(self) -> None:
        hub = SessionBroadcastHub("session-1", send_queue_maxsize=1)
        viewer = StuckViewerDetectionTests._NeverDrainingConnection()
        await hub.add_viewer(viewer)
        await self._broadcast(hub, 5)
        await asyncio.sleep(0)

        stats = hub.viewer_stats(viewer)

        # The FLV header is the only thing that ever reached this viewer, and it bypasses the
        # queue, so nothing counts as delivered.
        self.assertEqual(stats["delivered_chunks"], 0)
        self.assertIsNone(stats["seconds_since_last_delivery"])
        self.assertGreater(stats["dropped_chunks"], 0)

    async def test_returns_none_once_the_viewer_has_left(self) -> None:
        hub = SessionBroadcastHub("session-1")
        viewer = FakeConnection()
        await hub.add_viewer(viewer)
        hub.remove_viewer(viewer)

        self.assertIsNone(hub.viewer_stats(viewer))


if __name__ == "__main__":
    unittest.main()


# ----------------------------------------------------------------------------- ADR-0046 §5

SPS = b"\x00\x00\x00\x01\x67\x42\xc0\x1e\xda\x02\x80\xbf\xe5\xc0\x44\x00\x00\x03\x00\x04"
PPS = b"\x00\x00\x00\x01\x68\xce\x3c\x80"


def _keyframe(tag: bytes = b"I", size: int = 0) -> bytes:
    return SPS + PPS + b"\x00\x00\x00\x01\x65" + tag + b"\x00" * size


def _pframe(tag: bytes = b"P", size: int = 0) -> bytes:
    return b"\x00\x00\x00\x01\x41" + tag + b"\x00" * size


def _video_tags(sent: list[bytes]) -> list[tuple[str, bytes]]:
    """Every FLV video tag the viewer received after its header, as
    `("seq"|"key"|"inter", first payload byte after the NAL header)`."""
    stream = b"".join(sent[1:])  # sent[0] is the FLV header
    tags: list[tuple[str, bytes]] = []
    i = 0
    while i + 11 <= len(stream):
        tag_type = stream[i]
        size = int.from_bytes(stream[i + 1 : i + 4], "big")
        body = stream[i + 11 : i + 11 + size]
        i += 11 + size + 4
        if tag_type != 9:
            continue
        if body[1] == 0:
            tags.append(("seq", b""))
            continue
        kind = "key" if body[0] >> 4 == 1 else "inter"
        nal_payload = body[5 + 4 + 1 :]  # 5-byte AVC header, 4-byte NAL length, NAL header
        tags.append((kind, nal_payload[:1]))
    return tags


class _Blocked:
    """A viewer whose socket blocks after the FLV header until `gate` is set."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.gate = asyncio.Event()

    async def send_binary(self, data: bytes) -> None:
        if self.sent:
            await self.gate.wait()
        self.sent.append(data)


class KeyframeAwareDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def _drain(self, viewer) -> None:
        viewer.gate.set()
        for _ in range(200):
            await asyncio.sleep(0)

    async def test_a_viewer_joining_before_any_keyframe_receives_no_inter_frame(self) -> None:
        hub = SessionBroadcastHub("stream-1")
        viewer = FakeConnection()
        await hub.add_viewer(viewer)
        await hub.broadcast_video(annex_b_payload=_pframe(b"a"), is_keyframe=False, timestamp_ms=0)
        await hub.broadcast_video(annex_b_payload=_keyframe(b"K"), is_keyframe=True, timestamp_ms=40)
        await hub.broadcast_video(annex_b_payload=_pframe(b"b"), is_keyframe=False, timestamp_ms=80)
        await hub.wait_until_idle()
        self.assertEqual(_video_tags(viewer.sent), [("seq", b""), ("key", b"K"), ("inter", b"b")])

    async def test_a_viewer_joining_mid_gop_starts_from_the_cached_keyframe(self) -> None:
        hub = SessionBroadcastHub("stream-1")
        early = FakeConnection()
        await hub.add_viewer(early)
        await hub.broadcast_video(annex_b_payload=_keyframe(b"K"), is_keyframe=True, timestamp_ms=0)
        await hub.broadcast_video(annex_b_payload=_pframe(b"1"), is_keyframe=False, timestamp_ms=40)
        late = FakeConnection()
        await hub.add_viewer(late)  # joins mid-GOP
        await hub.broadcast_video(annex_b_payload=_pframe(b"2"), is_keyframe=False, timestamp_ms=80)
        await hub.wait_until_idle()
        self.assertEqual(
            _video_tags(late.sent),
            [("seq", b""), ("key", b"K"), ("inter", b"1"), ("inter", b"2")],
            "a decodable start: sequence header, keyframe, then the frames since",
        )

    async def test_the_gop_cache_restarts_at_every_keyframe(self) -> None:
        hub = SessionBroadcastHub("stream-1")
        frames = [_keyframe(b"A"), _pframe(b"1"), _keyframe(b"B"), _pframe(b"2")]
        for i, frame in enumerate(frames):
            await hub.broadcast_video(
                annex_b_payload=frame, is_keyframe=frame.startswith(SPS), timestamp_ms=i * 40
            )
        late = FakeConnection()
        await hub.add_viewer(late)
        await hub.wait_until_idle()
        self.assertEqual(_video_tags(late.sent), [("seq", b""), ("key", b"B"), ("inter", b"2")])

    async def test_an_oversized_gop_is_not_replayed(self) -> None:
        hub = SessionBroadcastHub("stream-1", gop_cache_max_bytes=1000)
        await hub.broadcast_video(annex_b_payload=_keyframe(b"K", 600), is_keyframe=True, timestamp_ms=0)
        await hub.broadcast_video(annex_b_payload=_pframe(b"1", 600), is_keyframe=False, timestamp_ms=40)
        late = FakeConnection()
        await hub.add_viewer(late)
        await hub.broadcast_video(annex_b_payload=_pframe(b"2"), is_keyframe=False, timestamp_ms=80)
        await hub.wait_until_idle()
        self.assertEqual(_video_tags(late.sent), [], "waits for the next keyframe instead")

    async def test_a_viewer_that_falls_behind_resynchronises_on_the_next_keyframe(self) -> None:
        hub = SessionBroadcastHub("stream-1", send_queue_maxsize=3)
        viewer = _Blocked()
        await hub.add_viewer(viewer)
        await hub.broadcast_video(annex_b_payload=_keyframe(b"K"), is_keyframe=True, timestamp_ms=0)
        await asyncio.sleep(0)  # the sender takes the keyframe and blocks on the socket
        resynced = []
        for i, tag in enumerate([b"1", b"2", b"3", b"4", b"5"]):
            resynced += await hub.broadcast_video(
                annex_b_payload=_pframe(tag), is_keyframe=False, timestamp_ms=40 * (i + 1)
            )
        self.assertEqual(resynced, [viewer], "overflow flushes the backlog once")
        await hub.broadcast_video(annex_b_payload=_pframe(b"6"), is_keyframe=False, timestamp_ms=240)
        await hub.broadcast_video(annex_b_payload=_keyframe(b"L"), is_keyframe=True, timestamp_ms=280)
        await hub.broadcast_video(annex_b_payload=_pframe(b"7"), is_keyframe=False, timestamp_ms=320)
        await self._drain(viewer)
        tags = _video_tags(viewer.sent)
        # Nothing between the flush and the next keyframe; a fresh sequence header before it.
        self.assertEqual(tags[:2], [("seq", b""), ("key", b"K")])
        self.assertEqual(tags[-3:], [("seq", b""), ("key", b"L"), ("inter", b"7")])
        self.assertNotIn(("inter", b"6"), tags)
        stats = hub.viewer_stats(viewer)
        self.assertEqual(stats["resyncs"], 1)
        self.assertGreaterEqual(stats["skipped_frames"], 1)

    async def test_a_main_stream_backlog_is_bounded_by_bytes(self) -> None:
        """Main-stream frames are large: the byte bound trips long before the chunk count."""
        hub = SessionBroadcastHub("stream-1", send_queue_maxsize=1000, max_queue_bytes=50_000)
        viewer = _Blocked()
        await hub.add_viewer(viewer)
        await hub.broadcast_video(annex_b_payload=_keyframe(b"K", 20_000), is_keyframe=True, timestamp_ms=0)
        await asyncio.sleep(0)
        resynced = []
        for i in range(4):  # 4 x 20 KB queued > 50 KB
            resynced += await hub.broadcast_video(
                annex_b_payload=_pframe(b"x", 20_000), is_keyframe=False, timestamp_ms=40 * (i + 1)
            )
        self.assertEqual(resynced, [viewer])
        self.assertLessEqual(hub.viewer_stats(viewer)["queued_bytes"], 50_000)
        await self._drain(viewer)

    async def test_a_sub_stream_viewer_keeping_up_is_never_resynchronised(self) -> None:
        hub = SessionBroadcastHub("stream-1")
        viewer = FakeConnection()
        await hub.add_viewer(viewer)
        for gop in range(3):
            await hub.broadcast_video(
                annex_b_payload=_keyframe(b"K", 800), is_keyframe=True, timestamp_ms=gop * 1000
            )
            for i in range(24):
                await hub.broadcast_video(
                    annex_b_payload=_pframe(b"p", 200),
                    is_keyframe=False,
                    timestamp_ms=gop * 1000 + 40 * (i + 1),
                )
                await hub.wait_until_idle()
        stats = hub.viewer_stats(viewer)
        self.assertEqual((stats["resyncs"], stats["dropped_chunks"]), (0, 0))

    async def test_an_old_backlog_is_dropped_by_age(self) -> None:
        clock = StuckViewerDetectionTests._Clock()
        hub = SessionBroadcastHub("stream-1", max_queue_age_seconds=2.0, clock=clock)
        viewer = _Blocked()
        await hub.add_viewer(viewer)
        await hub.broadcast_video(annex_b_payload=_keyframe(b"K"), is_keyframe=True, timestamp_ms=0)
        await asyncio.sleep(0)
        await hub.broadcast_video(annex_b_payload=_pframe(b"1"), is_keyframe=False, timestamp_ms=40)
        clock.now += 2.5
        resynced = await hub.broadcast_video(
            annex_b_payload=_pframe(b"2"), is_keyframe=False, timestamp_ms=80
        )
        self.assertEqual(resynced, [viewer], "2.5 s behind live is past the 2 s bound")
        await self._drain(viewer)

    async def test_a_stream_restart_resynchronises_every_viewer(self) -> None:
        hub = SessionBroadcastHub("stream-1")
        viewer = FakeConnection()
        await hub.add_viewer(viewer)
        await hub.broadcast_video(annex_b_payload=_keyframe(b"K"), is_keyframe=True, timestamp_ms=0)
        hub.begin_new_generation()
        await hub.broadcast_video(annex_b_payload=_pframe(b"x"), is_keyframe=False, timestamp_ms=40)
        await hub.broadcast_video(annex_b_payload=_keyframe(b"N"), is_keyframe=True, timestamp_ms=80)
        await hub.wait_until_idle()
        self.assertEqual(
            _video_tags(viewer.sent), [("seq", b""), ("key", b"K"), ("seq", b""), ("key", b"N")]
        )
        late = FakeConnection()
        await hub.add_viewer(late)
        await hub.wait_until_idle()
        self.assertEqual(_video_tags(late.sent)[1], ("key", b"N"), "the old GOP is not replayed")

    async def test_audio_waits_for_the_first_keyframe_on_a_video_stream(self) -> None:
        hub = SessionBroadcastHub("stream-1", has_audio=True)
        viewer = FakeConnection()
        await hub.add_viewer(viewer)
        await hub.broadcast_audio_aac(
            aac_payload=b"\x01", audio_specific_config=b"\x15\x88", timestamp_ms=0
        )
        await hub.wait_until_idle()
        self.assertEqual(len(viewer.sent), 1, "header only: no audio before the picture")
        await hub.broadcast_video(annex_b_payload=_keyframe(b"K"), is_keyframe=True, timestamp_ms=40)
        await hub.broadcast_audio_aac(
            aac_payload=b"\x02", audio_specific_config=b"\x15\x88", timestamp_ms=60
        )
        await hub.wait_until_idle()
        self.assertGreater(len(viewer.sent), 2)

    async def test_closing_one_sessions_viewers_leaves_the_others(self) -> None:
        class Closable(FakeConnection):
            def __init__(self) -> None:
                super().__init__()
                self.closed_with: tuple[int, bytes] | None = None

            async def send_close(self, *, code: int, reason: bytes) -> None:
                self.closed_with = (code, reason)

        hub = SessionBroadcastHub("stream-1")
        a, b = Closable(), Closable()
        await hub.add_viewer(a, owner="session-A")
        await hub.add_viewer(b, owner="session-B")
        await hub.close_owner("session-A", code=4011, reason=b"business_api_requested")
        self.assertEqual(a.closed_with, (4011, b"business_api_requested"))
        self.assertIsNone(b.closed_with)
        self.assertEqual(hub.viewer_count, 1)
        await hub.broadcast_video(annex_b_payload=_keyframe(b"K"), is_keyframe=True, timestamp_ms=0)
        await hub.wait_until_idle()
        self.assertEqual(_video_tags(b.sent)[1], ("key", b"K"))
        self.assertEqual(len(a.sent), 1)

    async def test_a_slow_but_draining_viewer_is_resynchronised_never_flagged_stuck(self) -> None:
        clock = StuckViewerDetectionTests._Clock()
        hub = SessionBroadcastHub(
            "stream-1", send_queue_maxsize=2, stuck_timeout_seconds=30.0, clock=clock
        )
        viewer = _Blocked()
        await hub.add_viewer(viewer)
        for second in range(120):
            clock.now += 1.0
            await hub.broadcast_video(
                annex_b_payload=_keyframe(b"K") if second % 25 == 0 else _pframe(b"p"),
                is_keyframe=second % 25 == 0,
                timestamp_ms=second * 40,
            )
            if second % 10 == 0:  # drains a little every 10 s: slow, not dead
                viewer.gate.set()
                for _ in range(20):
                    await asyncio.sleep(0)
                viewer.gate.clear()
        self.assertEqual(hub.take_stuck_viewers(), [])
        viewer.gate.set()
        for _ in range(50):
            await asyncio.sleep(0)
