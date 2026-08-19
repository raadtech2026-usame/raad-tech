"""`SessionRequestServer` tests — the Redis list-based RPC the Business API's own
`Jt1078RelayAdapter` uses to create/end relay sessions. A minimal in-memory fake Redis stands in
for `blpop`/`rpush`/`expire` — no real Redis connection, mirroring this codebase's own established
fake-Redis test convention.
"""

import asyncio
import json
import unittest

from src.events.publisher_port import LoggingSessionEventPublisher
from src.session.session_manager import SessionManager
from src.session.session_request_server import SessionRequestServer
from src.session.video_session import VideoSessionKind, VideoSessionState
from src.session.viewer_token import verify_token_signature

SECRET = b"test-secret"


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.expirations: dict[str, int] = {}

    async def blpop(self, keys, timeout: int = 0):
        # A real `redis.asyncio.Redis.blpop` always suspends back to the event loop (genuine
        # network I/O); this fake has no real I/O to await, so it must yield explicitly or a
        # consumer's `run_forever` `while True` loop would spin as a tight synchronous busy-loop
        # that never actually suspends, starving every other task on the loop (including a
        # test's own bounded polling wait) - the same lesson `services/device-gateway/tests/
        # test_gateway.py`'s own `FakeRedis.xreadgroup` already documents.
        await asyncio.sleep(0)
        for key in keys:
            values = self.lists.get(key)
            if values:
                return key, values.pop(0)
        return None

    async def rpush(self, name: str, *values: str) -> int:
        self.lists.setdefault(name, []).extend(values)
        return len(self.lists[name])

    async def expire(self, name: str, time: int) -> bool:
        self.expirations[name] = time
        return True


def _push_request(redis: FakeRedis, payload: dict) -> None:
    redis.lists.setdefault("raad:jt1078:session_requests", []).append(json.dumps(payload))


def _pop_response(redis: FakeRedis, request_id: str) -> dict:
    key = f"raad:jt1078:session_responses:{request_id}"
    values = redis.lists.get(key, [])
    assert values, f"no response pushed for {request_id}"
    return json.loads(values[0])


def _make_server(redis: FakeRedis) -> tuple[SessionRequestServer, SessionManager]:
    session_manager = SessionManager(event_publisher=LoggingSessionEventPublisher())
    server = SessionRequestServer(
        redis,
        session_manager=session_manager,
        viewer_token_secret=SECRET,
        public_ingest_host="relay.example.com",
        ingest_port=7910,
    )
    return server, session_manager


class SessionRequestServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_live_session_returns_ingest_coordinates_and_a_valid_token(self) -> None:
        redis = FakeRedis()
        server, session_manager = _make_server(redis)
        _push_request(
            redis,
            {
                "request_id": "req-1",
                "command": "create_live_session",
                "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "correlation_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "terminal_id": "00000000013800138000",
                "logical_channel": 1,
                "device_id": "device-1",
                "organization_id": "org-1",
            },
        )

        processed = await server.poll_once()

        self.assertTrue(processed)
        response = _pop_response(redis, "req-1")
        self.assertTrue(response["ok"])
        self.assertEqual(response["session_id"], "01ARZ3NDEKTSV4RRFFQ69G5FAV")
        self.assertEqual(response["ingest_host"], "relay.example.com")
        self.assertEqual(response["ingest_port"], 7910)
        self.assertEqual(
            verify_token_signature(response["viewer_token"], secret=SECRET),
            "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        )
        session = session_manager.resolve("01ARZ3NDEKTSV4RRFFQ69G5FAV")
        self.assertIsNotNone(session)
        self.assertEqual(session.state, VideoSessionState.REQUESTED)
        self.assertEqual(redis.expirations[f"raad:jt1078:session_responses:req-1"], 30)

    async def test_create_playback_session_uses_the_playback_kind(self) -> None:
        redis = FakeRedis()
        server, session_manager = _make_server(redis)
        _push_request(
            redis,
            {
                "request_id": "req-2",
                "command": "create_playback_session",
                "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
                "correlation_id": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
                "terminal_id": "00000000013800138000",
                "logical_channel": 1,
                "window_start": "2026-08-11T08:00:00+00:00",
                "window_end": "2026-08-11T09:00:00+00:00",
            },
        )

        await server.poll_once()

        session = session_manager.resolve("01ARZ3NDEKTSV4RRFFQ69G5FAW")
        self.assertEqual(session.kind, VideoSessionKind.PLAYBACK)
        response = _pop_response(redis, "req-2")
        self.assertTrue(response["ok"])

    async def test_end_session_tears_down_and_acks(self) -> None:
        redis = FakeRedis()
        server, session_manager = _make_server(redis)
        session_manager.create_session(
            session_id="sess-to-end",
            terminal_id="T1",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-1",
            logical_channel=1,
        )
        _push_request(redis, {"request_id": "req-3", "command": "end_session", "session_id": "sess-to-end"})

        await server.poll_once()

        self.assertIsNone(session_manager.resolve("sess-to-end"))
        response = _pop_response(redis, "req-3")
        self.assertEqual(response, {"ok": True})

    async def test_unknown_command_is_acked_as_a_failure_not_raised(self) -> None:
        redis = FakeRedis()
        server, _session_manager = _make_server(redis)
        _push_request(redis, {"request_id": "req-4", "command": "not_a_real_command"})

        await server.poll_once()

        response = _pop_response(redis, "req-4")
        self.assertFalse(response["ok"])
        self.assertIn("unknown command", response["error"])

    async def test_malformed_request_does_not_raise_and_produces_no_response(self) -> None:
        redis = FakeRedis()
        server, _session_manager = _make_server(redis)
        redis.lists["raad:jt1078:session_requests"] = ["not valid json"]

        processed = await server.poll_once()

        self.assertTrue(processed)  # a request was consumed, even though it couldn't be handled
        self.assertEqual(redis.lists.get("raad:jt1078:session_responses:None", []), [])

    async def test_missing_required_field_is_acked_as_a_failure(self) -> None:
        redis = FakeRedis()
        server, _session_manager = _make_server(redis)
        _push_request(
            redis, {"request_id": "req-5", "command": "create_live_session", "session_id": "x"}
        )  # missing terminal_id/logical_channel

        await server.poll_once()

        response = _pop_response(redis, "req-5")
        self.assertFalse(response["ok"])

    async def test_poll_once_returns_false_when_nothing_is_pending(self) -> None:
        redis = FakeRedis()
        server, _session_manager = _make_server(redis)
        processed = await server.poll_once()
        self.assertFalse(processed)


class FlakyRedis(FakeRedis):
    """Raises on its first N `blpop` calls (mirrors the live-reproduced `BusyLoadingError`),
    then behaves normally - the regression fixture for `run_forever`'s own resilience fix."""

    def __init__(self, *, fail_first_n_calls: int) -> None:
        super().__init__()
        self._remaining_failures = fail_first_n_calls
        self.blpop_call_count = 0

    async def blpop(self, keys, timeout: int = 0):
        self.blpop_call_count += 1
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise ConnectionError("simulated transient Redis failure")
        return await super().blpop(keys, timeout=timeout)


class RunForeverResilienceTests(unittest.IsolatedAsyncioTestCase):
    """**Regression test for a real, live-reproduced outage (2026-08-19):** `run_forever`
    previously had no protection at all - a single transient Redis error on its very first
    `poll_once` call permanently killed the task, silently, for the rest of the process's life.
    22+ real session-creation requests piled up unprocessed in `raad:jt1078:session_requests`
    before this was caught. This proves the fixed loop survives an early failure and goes on to
    process a request queued after it."""

    async def test_survives_a_transient_failure_and_keeps_processing(self) -> None:
        redis = FlakyRedis(fail_first_n_calls=1)
        server, session_manager = _make_server(redis)
        _push_request(
            redis,
            {
                "request_id": "req-after-failure",
                "command": "create_live_session",
                "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAZ",
                "correlation_id": "01ARZ3NDEKTSV4RRFFQ69G5FAZ",
                "terminal_id": "00000000013800138000",
                "logical_channel": 1,
            },
        )

        task = asyncio.create_task(server.run_forever())
        try:
            for _ in range(200):  # bounded polling, not an unconditional sleep
                if redis.lists.get("raad:jt1078:session_responses:req-after-failure"):
                    break
                await asyncio.sleep(0.01)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertGreaterEqual(redis.blpop_call_count, 2)  # the failure, then a real read
        response = _pop_response(redis, "req-after-failure")
        self.assertTrue(response["ok"])
        self.assertIsNotNone(session_manager.resolve("01ARZ3NDEKTSV4RRFFQ69G5FAZ"))


if __name__ == "__main__":
    unittest.main()
