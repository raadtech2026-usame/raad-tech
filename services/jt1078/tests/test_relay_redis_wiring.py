"""`Jt1078Relay` Redis-wiring tests — mirrors `device-gateway`'s own `test_gateway.py`
`DeviceGatewayRedisWiringTests` precedent: injecting a fake Redis client is enough to prove the
conditional-binding path picks the real `RedisSessionEventPublisher`/`RedisSingleUseTokenGuard`
instead of the logging/in-memory defaults, without a real Redis connection.
"""

import json
import unittest

from src.config import RelayConfig
from src.events.publisher_port import LoggingSessionEventPublisher
from src.events.redis_session_event_publisher import RedisSessionEventPublisher
from src.relay import Jt1078Relay
from src.session.viewer_token import InMemorySingleUseTokenGuard, RedisSingleUseTokenGuard


class FakeRedis:
    """Also backs `SessionRequestServer`'s `blpop`/`rpush`/`expire` calls (its background task
    starts for real the instant `relay.start()` runs with a Redis client wired) - without these,
    that task would hit a silent `AttributeError` on its very first poll and die unnoticed,
    masking a broken background task rather than genuinely proving it runs cleanly."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, dict[str, str]]] = []
        self.lists: dict[str, list[str]] = {}

    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool = False,
    ) -> str:
        # `maxlen`/`approximate` mirror redis-py's own `XADD` kwargs — accepted (and
        # recorded) so this fake stays call-compatible with the stream-trimming fix
        # (2026-09-02); trimming itself is asserted in the publisher's own unit tests.
        self.last_xadd_kwargs = {"maxlen": maxlen, "approximate": approximate}
        message_id = str(len(self.entries) + 1)
        self.entries.append((message_id, fields))
        return message_id

    async def set(self, key, value, *, nx=False, ex=None):
        # Every claim succeeds for this fake - `RedisSingleUseTokenGuard`'s real single-use
        # semantics (the `SET NX` atomicity) need a real Redis to prove, out of scope for this
        # file's own conditional-binding focus; `test_viewer_token.py` covers the in-memory
        # guard's single-use logic instead.
        return True

    async def blpop(self, keys, timeout: int = 0):
        for key in keys:
            values = self.lists.get(key)
            if values:
                return key, values.pop(0)
        return None

    async def rpush(self, name: str, *values: str) -> int:
        self.lists.setdefault(name, []).extend(values)
        return len(self.lists[name])

    async def expire(self, name: str, time: int) -> bool:
        return True


def _config() -> RelayConfig:
    return RelayConfig(
        ingest_host="127.0.0.1",
        ingest_port=0,
        viewer_host="127.0.0.1",
        viewer_port=0,
        viewer_token_secret=b"secret",
    )


class Jt1078RelayRedisWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_without_a_broker_falls_back_to_logging_and_in_memory_defaults(self) -> None:
        relay = Jt1078Relay(config=_config())
        self.assertIsInstance(relay._event_publisher, LoggingSessionEventPublisher)
        self.assertIsInstance(relay._token_guard, InMemorySingleUseTokenGuard)

    async def test_a_redis_client_wires_the_real_redis_backed_implementations(self) -> None:
        redis = FakeRedis()
        relay = Jt1078Relay(config=_config(), redis_client=redis)
        self.assertIsInstance(relay._event_publisher, RedisSessionEventPublisher)
        self.assertIsInstance(relay._token_guard, RedisSingleUseTokenGuard)
        self.assertIsNotNone(relay.session_request_server)

    async def test_without_a_broker_no_session_request_server_is_built(self) -> None:
        relay = Jt1078Relay(config=_config())
        self.assertIsNone(relay.session_request_server)

    async def test_ending_a_session_with_redis_wired_publishes_onto_the_shared_stream(
        self,
    ) -> None:
        redis = FakeRedis()
        relay = Jt1078Relay(config=_config(), redis_client=redis)
        await relay.start()
        try:
            session, _token = relay.create_live_session(
                terminal_id="T1", correlation_id="corr-1", logical_channel=1
            )
            await relay.session_manager.end_session(session.session_id, reason="explicit_stop")

            event_types = [
                json.loads(fields["data"])["event_type"] for _msg_id, fields in redis.entries
            ]
            self.assertIn("VideoSessionEnded", event_types)
            self.assertIn("Jt1078SignalCommandRequested", event_types)  # the device stop-signal
        finally:
            await relay.stop()


if __name__ == "__main__":
    unittest.main()
