"""`Jt1078RelayRpcClient` tests (JT1078 backend-integration phase) — the Redis list-based RPC to
`services/jt1078`'s `SessionRequestServer`. A minimal in-memory fake Redis stands in for
`rpush`/`blpop` — no real Redis connection, mirroring this codebase's own established fake-Redis
test convention (e.g. `services/device-gateway/tests/test_redis_video_signaling_consumer.py`).
`blpop` genuinely polls (short-sleeps until data appears or its own timeout elapses) rather than
checking once, so it actually exercises the client's real "wait for a specific reply" behavior,
not just a lucky single-step interleaving.
"""

from __future__ import annotations

import asyncio
import json
import time
import unittest

from raad.modules.video.infra.jt1078_relay_client import (
    Jt1078RelayError,
    Jt1078RelayRpcClient,
    Jt1078RelayTimeoutError,
)


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    async def rpush(self, name: str, *values: str) -> int:
        self.lists.setdefault(name, []).extend(values)
        return len(self.lists[name])

    async def blpop(self, keys, timeout: int = 0):
        deadline = time.monotonic() + timeout
        while True:
            for key in keys:
                values = self.lists.get(key)
                if values:
                    return key, values.pop(0)
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.01)


async def _wait_for_request(redis: FakeRedis, key: str = "raad:jt1078:session_requests") -> dict:
    while not redis.lists.get(key):
        await asyncio.sleep(0.01)
    return json.loads(redis.lists[key][0])


class Jt1078RelayRpcClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_pushes_a_well_formed_request_and_returns_the_response(self) -> None:
        redis = FakeRedis()
        client = Jt1078RelayRpcClient(redis)

        task = asyncio.ensure_future(client.call("create_live_session", {"session_id": "sess-1"}))
        request = await _wait_for_request(redis)
        self.assertEqual(request["command"], "create_live_session")
        self.assertEqual(request["session_id"], "sess-1")
        self.assertIn("request_id", request)

        response_key = f"raad:jt1078:session_responses:{request['request_id']}"
        redis.lists[response_key] = [json.dumps({"ok": True, "session_id": "sess-1"})]

        response = await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual(response["session_id"], "sess-1")

    async def test_ok_false_response_raises_jt1078_relay_error(self) -> None:
        redis = FakeRedis()
        client = Jt1078RelayRpcClient(redis)

        task = asyncio.ensure_future(client.call("create_live_session", {}))
        request = await _wait_for_request(redis)
        response_key = f"raad:jt1078:session_responses:{request['request_id']}"
        redis.lists[response_key] = [json.dumps({"ok": False, "error": "terminal offline"})]

        with self.assertRaises(Jt1078RelayError) as ctx:
            await asyncio.wait_for(task, timeout=2.0)
        self.assertIn("terminal offline", str(ctx.exception))

    async def test_no_response_within_timeout_raises_jt1078_relay_timeout_error(self) -> None:
        redis = FakeRedis()
        client = Jt1078RelayRpcClient(redis, timeout_seconds=0.05)

        with self.assertRaises(Jt1078RelayTimeoutError):
            await client.call("create_live_session", {"session_id": "sess-2"})

    async def test_each_call_uses_a_distinct_request_id(self) -> None:
        redis = FakeRedis()
        client = Jt1078RelayRpcClient(redis)

        async def respond(command: str, session_id: str):
            task = asyncio.ensure_future(client.call(command, {"session_id": session_id}))
            while True:
                pending = [
                    json.loads(r)
                    for r in redis.lists.get("raad:jt1078:session_requests", [])
                    if json.loads(r)["session_id"] == session_id
                ]
                if pending:
                    break
                await asyncio.sleep(0.01)
            request_id = pending[0]["request_id"]
            redis.lists[f"raad:jt1078:session_responses:{request_id}"] = [
                json.dumps({"ok": True, "session_id": session_id})
            ]
            return await asyncio.wait_for(task, timeout=2.0)

        result_a, result_b = await asyncio.gather(
            respond("create_live_session", "sess-A"), respond("create_live_session", "sess-B")
        )
        self.assertEqual(result_a["session_id"], "sess-A")
        self.assertEqual(result_b["session_id"], "sess-B")


if __name__ == "__main__":
    unittest.main()
