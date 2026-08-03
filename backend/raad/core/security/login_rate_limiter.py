"""IP-based rate limiting for `/auth/login` (Priority 1 Item 3, `PROJECT_STATUS.md`), distinct
from and complementary to account lockout (`modules.iam.domain.entities.User.
record_failed_login`): this limits *how fast* one source can attempt logins at all, regardless
of which account(s) it targets, where lockout limits *how many wrong guesses* one specific
account tolerates regardless of source. Configured by `RateLimitSettings`
(`core/config/settings.py`).

Deliberately the simplest correct primitive — a Redis `INCR`+`EXPIRE` fixed-window counter, not
a sliding-window/token-bucket algorithm. No requirement here justifies that extra complexity.
"""

from __future__ import annotations

from redis.asyncio import Redis

from raad.core.config.settings import RateLimitSettings


class LoginRateLimiter:
    """Bound only when `RedisSettings.url` is configured (`core/di/bootstrap.py`), the same
    "fail loudly, don't fake it" conditional-binding shape `RedisLatestPositionPort`/
    `GeofenceStatePort` already establish — reuses their same Redis client rather than opening a
    second connection (that file's own "reuse, don't duplicate" convention).

    Unlike those ports, an *unbound* rate limiter must not make the platform unusable: `/auth/
    login` itself must keep working even without Redis configured (e.g. before Priority 1 Item 4,
    Redis production hardening, actually lands) — callers resolve this via `container.
    try_resolve(...)` (`interfaces/http/middleware.RateLimitMiddleware`) and treat `None` as
    "not enforced," logging that once at app startup, never per-request.
    """

    def __init__(self, redis_client: Redis, *, settings: RateLimitSettings) -> None:
        self._redis = redis_client
        self._settings = settings

    async def is_allowed(self, client_ip: str) -> bool:
        """`True` if this request should proceed, `False` if the caller has exceeded
        `max_attempts` within the current `window_seconds` window. The window resets
        `window_seconds` after the *first* request in it (a fixed window, not a rolling one) —
        `EXPIRE` is set only when this key's count was just created (`count == 1`), so a
        request that arrives after the key has already expired starts a fresh window rather
        than extending a stale one indefinitely."""
        key = f"ratelimit:login:{client_ip}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, self._settings.window_seconds)
        return count <= self._settings.max_attempts
