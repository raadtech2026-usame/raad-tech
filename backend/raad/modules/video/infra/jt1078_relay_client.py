"""`Jt1078RelayRpcClient` — the Business API's own caller of `services/jt1078`'s
`SessionRequestServer` (JT1078 backend-integration phase). A Redis list-based RPC: push a JSON
request, `BLPOP` a per-request response key — the standard, race-free "Redis as synchronous RPC"
idiom (a request always exists in the list *before* the caller starts waiting on its own response
key, unlike Pub/Sub's subscribe-after-publish race). Chosen over extending the existing
`BrokerPort`/`raad:events` Stream because that mechanism is *fire-and-forget* (no caller ever
waits for a specific reply) — exactly the shape already reused, unchanged, for the *other* half
of this integration: signaling the device to start (`Jt1078RelayAdapter._signal_device_start`
publishes onto `raad:events` via the existing `BrokerPort`, the same stream/consumer
`device-gateway`'s `RedisVideoSignalingConsumer` already reads).

**Wire contract — must match `services/jt1078/src/session/session_request_server.py`'s own
documented contract exactly**; that module's docstring is the reference definition, this is the
client side of the identical shape. `raad:jt1078:session_requests` (request list) and
`raad:jt1078:session_responses:<request_id>` (one response list key per request) are plain
constants, not settings — mirrors `redis_streams.DEFAULT_STREAM_NAME`'s own "wire contract, not
configuration" treatment.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from redis.asyncio import Redis

DEFAULT_REQUEST_LIST_KEY = "raad:jt1078:session_requests"
DEFAULT_RESPONSE_KEY_PREFIX = "raad:jt1078:session_responses"
DEFAULT_RPC_TIMEOUT_SECONDS = 10.0


class Jt1078RelayTimeoutError(Exception):
    """No response arrived from the relay within the configured timeout — it may be down,
    unreachable, or simply overloaded; this is distinct from `Jt1078RelayError` (the relay *did*
    respond, but rejected the request)."""


class Jt1078RelayError(Exception):
    """The relay responded with `{"ok": false, "error": "..."}`."""


class Jt1078RelayRpcClient:
    def __init__(
        self,
        redis_client: Redis,
        *,
        request_list_key: str = DEFAULT_REQUEST_LIST_KEY,
        response_key_prefix: str = DEFAULT_RESPONSE_KEY_PREFIX,
        timeout_seconds: float = DEFAULT_RPC_TIMEOUT_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._request_list_key = request_list_key
        self._response_key_prefix = response_key_prefix
        self._timeout_seconds = timeout_seconds

    async def call(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Raises `Jt1078RelayTimeoutError`/`Jt1078RelayError` on failure; returns the relay's
        own response dict (already confirmed `ok: true`) on success."""
        request_id = str(uuid.uuid4())
        request = {"request_id": request_id, "command": command, **payload}
        await self._redis.rpush(self._request_list_key, json.dumps(request))

        response_key = f"{self._response_key_prefix}:{request_id}"
        # BLPOP's own timeout is a non-negative integer number of seconds - round up so a
        # sub-second configured timeout still waits at least one full second rather than
        # truncating to an immediate no-wait poll.
        blpop_timeout = max(1, int(self._timeout_seconds + 0.999))
        result = await self._redis.blpop([response_key], timeout=blpop_timeout)
        if result is None:
            raise Jt1078RelayTimeoutError(
                f"No response from the JT1078 relay within {self._timeout_seconds}s "
                f"for command {command!r} (request_id={request_id})."
            )
        _key, raw = result
        response: dict[str, Any] = json.loads(raw)
        if not response.get("ok"):
            raise Jt1078RelayError(response.get("error") or "Unknown JT1078 relay error.")
        return response
