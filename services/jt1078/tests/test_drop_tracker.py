"""`ViewerDropTracker` (2026-09-19): relay-side viewer drops must be visible in the logs, without
flooding them, so a relay drop can be told apart from a device-side gap."""

import unittest

from src.viewer.drop_tracker import ViewerDropTracker

_LOGGER = "jt1078.viewer.drop_tracker"


class _FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _fields(records):
    return [record.extra_fields for record in records]


class ViewerDropTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _FakeClock()
        self.tracker = ViewerDropTracker(log_interval_seconds=5.0, clock=self.clock)

    def test_no_drops_logs_nothing_and_totals_zero(self) -> None:
        with self.assertNoLogs(_LOGGER):
            self.tracker.record("s1", dropped=0, kind="video")
        self.assertEqual(self.tracker.pop_total("s1"), 0)

    def test_first_drop_is_logged_immediately(self) -> None:
        with self.assertLogs(_LOGGER, level="WARNING") as captured:
            self.tracker.record("s1", dropped=1, kind="video")
        self.assertEqual(
            _fields(captured.records),
            [{"session_id": "s1", "video_dropped": 1, "audio_dropped": 0, "dropped_total": 1}],
        )

    def test_drops_within_the_interval_are_aggregated_into_the_next_line(self) -> None:
        with self.assertLogs(_LOGGER, level="WARNING") as captured:
            self.tracker.record("s1", dropped=1, kind="video")
            self.clock.now += 1
            self.tracker.record("s1", dropped=2, kind="video")
            self.tracker.record("s1", dropped=1, kind="audio")
            self.clock.now += 5
            self.tracker.record("s1", dropped=1, kind="video")
        self.assertEqual(len(captured.records), 2)
        self.assertEqual(
            captured.records[1].extra_fields,
            {"session_id": "s1", "video_dropped": 3, "audio_dropped": 1, "dropped_total": 5},
        )

    def test_pop_total_reports_the_whole_session_and_forgets_it(self) -> None:
        with self.assertLogs(_LOGGER, level="WARNING"):
            self.tracker.record("s1", dropped=2, kind="video")
            self.tracker.record("s1", dropped=3, kind="audio")
        self.assertEqual(self.tracker.pop_total("s1"), 5)
        self.assertEqual(self.tracker.pop_total("s1"), 0)

    def test_sessions_are_rate_limited_independently(self) -> None:
        with self.assertLogs(_LOGGER, level="WARNING") as captured:
            self.tracker.record("s1", dropped=1, kind="video")
            self.tracker.record("s2", dropped=1, kind="video")
        self.assertEqual([f["session_id"] for f in _fields(captured.records)], ["s1", "s2"])


if __name__ == "__main__":
    unittest.main()
