"""Unit tests for `core.security.login_rate_limiter.LoginRateLimiter` (Priority 1 Item 3,
`PROJECT_STATUS.md`). Stdlib `unittest` — no `pytest` (not an approved dependency). A minimal
fake standing in for `redis.asyncio.Redis` (only the two methods the limiter actually calls,
`incr`/`expire`), mirroring `test_tracking_redis_latest_position.py`'s established `FakeRedis`
pattern — no real Redis connection.

Covers: the fixed-window `INCR`+`EXPIRE` counting/threshold logic and per-client-IP key
isolation. Does **not** cover a real Redis server round trip or `RateLimitMiddleware`'s own
`RedisError` fail-open behavior when Redis is configured but unreachable — that path was
live-verified manually against this sandbox's actual (confirmed unreachable) `RAAD_REDIS__URL`,
see `PROJECT_STATUS.md`'s Item 3 entry for the disclosed scope of what was/wasn't live-tested.
"""

from __future__ import annotations

import unittest

from raad.core.config.settings import RateLimitSettings
from raad.core.security.login_rate_limiter import LoginRateLimiter


class FakeRedis:
    """Only `incr`/`expire` — the two calls `LoginRateLimiter.is_allowed` actually makes."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self.expire_calls: list[tuple[str, int]] = []

    async def incr(self, key: str) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.expire_calls.append((key, seconds))


def make_limiter(
    redis: FakeRedis, *, max_attempts: int = 3, window_seconds: int = 60
) -> LoginRateLimiter:
    return LoginRateLimiter(
        redis,
        settings=RateLimitSettings(
            max_attempts=max_attempts, window_seconds=window_seconds
        ),
    )


class LoginRateLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_request_is_allowed_and_sets_expiry(self) -> None:
        redis = FakeRedis()
        limiter = make_limiter(redis, max_attempts=3, window_seconds=60)
        allowed = await limiter.is_allowed("1.2.3.4")
        self.assertTrue(allowed)
        self.assertEqual(redis.expire_calls, [("ratelimit:login:1.2.3.4", 60)])

    async def test_requests_within_the_limit_are_allowed(self) -> None:
        redis = FakeRedis()
        limiter = make_limiter(redis, max_attempts=3, window_seconds=60)
        results = [await limiter.is_allowed("1.2.3.4") for _ in range(3)]
        self.assertEqual(results, [True, True, True])

    async def test_request_exceeding_the_limit_is_denied(self) -> None:
        redis = FakeRedis()
        limiter = make_limiter(redis, max_attempts=3, window_seconds=60)
        for _ in range(3):
            await limiter.is_allowed("1.2.3.4")
        allowed = await limiter.is_allowed("1.2.3.4")
        self.assertFalse(allowed)

    async def test_expire_is_only_set_on_the_first_increment_in_a_window(self) -> None:
        redis = FakeRedis()
        limiter = make_limiter(redis, max_attempts=5, window_seconds=60)
        for _ in range(3):
            await limiter.is_allowed("1.2.3.4")
        # EXPIRE called exactly once - a fixed window, not extended by every request.
        self.assertEqual(len(redis.expire_calls), 1)

    async def test_different_client_ips_are_counted_independently(self) -> None:
        redis = FakeRedis()
        limiter = make_limiter(redis, max_attempts=1, window_seconds=60)
        first_allowed = await limiter.is_allowed("1.2.3.4")
        second_ip_allowed = await limiter.is_allowed("5.6.7.8")
        first_ip_second_attempt = await limiter.is_allowed("1.2.3.4")
        self.assertTrue(first_allowed)
        self.assertTrue(second_ip_allowed)  # independent counter, not exhausted by the first
        self.assertFalse(first_ip_second_attempt)  # its own counter is now exhausted

    async def test_key_shape_is_scoped_by_client_ip(self) -> None:
        redis = FakeRedis()
        limiter = make_limiter(redis)
        await limiter.is_allowed("9.9.9.9")
        self.assertIn("ratelimit:login:9.9.9.9", redis._counts)


if __name__ == "__main__":
    unittest.main()
