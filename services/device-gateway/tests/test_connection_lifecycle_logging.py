"""ADR-0045 regression: the container's own healthcheck must not drown out real device events.

The Docker healthcheck dials `localhost` and disconnects immediately, emitting
`connection_accepted` + `connection_closing` + `connection_closed` every interval — ~26,000
lines/day at the previous 10s cadence. These are now logged at DEBUG *only* when the peer is
loopback; every real terminal (which necessarily arrives from outside the container) still logs
at INFO.

The second test is the one that actually matters: JT/T 808 MDVR behaviour is under active
investigation, so a fix that quietened genuine device connections would be worse than the noise
it removed.
"""

import asyncio  # noqa: F401  (kept: the lambdas below return coroutines)
import logging
import unittest

from src.connection.connection import Connection


class _StubWriter:
    """Minimal `asyncio.StreamWriter` stand-in — `Connection.__init__` only reads `peername`."""

    def __init__(self, peername):
        self._peername = peername

    def get_extra_info(self, name):
        return self._peername if name == "peername" else None


def _connection(peername) -> Connection:
    # `reader` is only stored by `__init__`; a real `asyncio.StreamReader` would need a running
    # event loop, which these tests deliberately do not need.
    return Connection(
        connection_id="c-1",
        reader=object(),
        writer=_StubWriter(peername),
        read_chunk_size=4096,
        on_frame=lambda _cid, _frame: asyncio.sleep(0),
        on_activity=lambda: None,
        on_close=lambda _cid: asyncio.sleep(0),
        frame_buffer=object(),
    )


class ConnectionLifecycleLogLevelTests(unittest.TestCase):
    def test_loopback_healthcheck_connection_logs_at_debug(self):
        for peername in (
            ("127.0.0.1", 54321),
            ("::1", 54321, 0, 0),
            ("::ffff:127.0.0.1", 54321),
        ):
            with self.subTest(peername=peername):
                self.assertEqual(
                    _connection(peername)._lifecycle_log_level,
                    logging.DEBUG,
                    "healthcheck connections must not log at INFO",
                )

    def test_real_device_connection_still_logs_at_info(self):
        # A terminal reaching this process through Docker's published port presents either the
        # bridge gateway address or its own public address — never loopback.
        for peername in (
            ("172.16.2.1", 40302),  # docker bridge gateway
            ("41.78.74.79", 18645),  # a real cellular peer
            ("10.0.0.5", 5000),
        ):
            with self.subTest(peername=peername):
                self.assertEqual(
                    _connection(peername)._lifecycle_log_level,
                    logging.INFO,
                    "real device connections must remain visible at INFO",
                )

    def test_unknown_peername_shape_defaults_to_info(self):
        # `get_extra_info("peername")` can return None on an already-dead transport. Defaulting
        # to INFO keeps the fix fail-safe: it can never silence something it failed to classify.
        for peername in (None, "", ()):
            with self.subTest(peername=peername):
                self.assertEqual(_connection(peername)._lifecycle_log_level, logging.INFO)


if __name__ == "__main__":
    unittest.main()
