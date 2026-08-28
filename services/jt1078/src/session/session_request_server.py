"""`SessionRequestServer` — the Business API's own entry point into this relay, closing the
gap this codebase's own prior implementation report flagged: "no approved document specifies the
backend<->relay transport, so no `VideoProviderPort` adapter binds this relay yet." Resolved here
as a **Redis list-based RPC**, reusing the same broker Redis instance every other device-plane
coordination in this platform already shares (ADR-0024 §8/§9) — chosen over a second broker-
Stream-consumer-group (the pattern `commands/redis_video_signaling_consumer.py` on the
device-gateway side already uses) because that pattern fits *fire-and-forget* commands, not a
call that must return a real value (`viewer_token`, ingest coordinates) to a specific waiting
caller; `BLPOP` on a per-request response key is the standard, race-free "Redis as synchronous
RPC" idiom (a request always exists in the list before the caller starts waiting, so this is
correct even though the two operations aren't atomic together, unlike Pub/Sub's own
subscribe-after-publish race).

**Wire contract — the reference definition, matching what `backend/raad/modules/video/infra/
jt1078_relay_client.py` publishes:**

Request, `RPUSH raad:jt1078:session_requests <json>`:
```json
{
  "request_id": "<uuid4>",
  "command": "create_live_session" | "create_playback_session" | "end_session",
  "session_id": "<the Business API's own VideoSession.id - this relay's session_id too>",
  "correlation_id": "<same as session_id>",
  "terminal_id": "<JT/T 808 terminal phone>",
  "logical_channel": <int>,
  "device_id": "<opaque>", "vehicle_id": "<opaque>|null", "organization_id": "<opaque>",
  "window_start": "<ISO 8601>|null", "window_end": "<ISO 8601>|null",
  "audio_codec": <int>|null
}
```

`audio_codec` (added for the G.711A audio fix, `codec/g711a.py`): the device's own real
`0x1003`-reported `input_audio_codec` (Table 6.21), sourced from `AudioCapability.codec`
(ADR-0033) - the raw wire byte, optional and defaulting to `None`/absent for an older backend
build or a device with no captured `AudioCapability` yet. `relay.py`'s own audio-decoder
dispatch table treats `None` and any unrecognized value identically: no audio tags are ever
built for that session - this relay never guesses a codec it hasn't been told, or invents
support for one it hasn't implemented.

Response, `RPUSH raad:jt1078:session_responses:<request_id> <json>`:
```json
{"ok": true, "session_id": "...", "viewer_token": "...", "ingest_host": "...", "ingest_port": 7910}
```
or `{"ok": false, "error": "<reason>"}`. `end_session` omits `viewer_token`/ingest fields on
success.

**Does not itself signal the device to start** — mirrors `Jt1078Relay.create_live_session`'s own
already-documented division of responsibility (ADR-0024 §6 step 3/§8: the Business API signals
the device via `device-gateway`, after this call returns ingest coordinates it needs to build
that signal). `end_session` *does* trigger the device stop-signal, because that already happens
inside `SessionManager.end_session` itself (ADR-0024 §5 point 4), unchanged by this server.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from redis.asyncio import Redis

from src.logging_setup import get_logger, log_with_fields
from src.session.session_manager import SessionManager
from src.session.video_session import VideoSessionKind
from src.session.viewer_token import mint_token

logger = get_logger("jt1078_relay.session.request_server")

DEFAULT_REQUEST_LIST_KEY = "raad:jt1078:session_requests"
DEFAULT_RESPONSE_KEY_PREFIX = "raad:jt1078:session_responses"
_BLPOP_TIMEOUT_SECONDS = 1  # must be a whole number of seconds - redis BLPOP's own contract


class SessionRequestServer:
    def __init__(
        self,
        redis_client: Redis,
        *,
        session_manager: SessionManager,
        viewer_token_secret: bytes,
        public_ingest_host: str,
        ingest_port: int,
        request_list_key: str = DEFAULT_REQUEST_LIST_KEY,
        response_key_prefix: str = DEFAULT_RESPONSE_KEY_PREFIX,
        response_ttl_seconds: int = 30,
    ) -> None:
        self._redis = redis_client
        self._session_manager = session_manager
        self._viewer_token_secret = viewer_token_secret
        self._public_ingest_host = public_ingest_host
        self._ingest_port = ingest_port
        self._request_list_key = request_list_key
        self._response_key_prefix = response_key_prefix
        self._response_ttl_seconds = response_ttl_seconds

    async def poll_once(self) -> bool:
        """One read pass. Returns `True` if a request was processed, `False` if the poll simply
        timed out with nothing pending (the normal, expected common case)."""
        result = await self._redis.blpop([self._request_list_key], timeout=_BLPOP_TIMEOUT_SECONDS)
        if result is None:
            return False
        _key, raw = result
        await self._process_one(raw)
        return True

    async def _process_one(self, raw: str) -> None:
        try:
            data: dict[str, Any] = json.loads(raw)
            request_id = data["request_id"]
            command = data["command"]
        except (ValueError, KeyError, TypeError) as exc:
            log_with_fields(
                logger, 30, "session_request_malformed", error=str(exc)
            )
            return

        try:
            response = await self._handle(command, data)
        except Exception as exc:  # noqa: BLE001 - a bad request must not crash this loop
            log_with_fields(
                logger, 30, "session_request_failed", command=command, error=str(exc)
            )
            response = {"ok": False, "error": str(exc)}

        await self._respond(request_id, response)

    async def _handle(self, command: str, data: dict[str, Any]) -> dict[str, Any]:
        if command == "create_live_session":
            return self._create_session(VideoSessionKind.LIVE, data)
        if command == "create_playback_session":
            return self._create_session(VideoSessionKind.PLAYBACK, data)
        if command == "end_session":
            await self._session_manager.end_session(
                data["session_id"], reason="business_api_requested"
            )
            return {"ok": True}
        return {"ok": False, "error": f"unknown command: {command!r}"}

    def _create_session(self, kind: VideoSessionKind, data: dict[str, Any]) -> dict[str, Any]:
        session = self._session_manager.create_session(
            session_id=data["session_id"],
            terminal_id=data["terminal_id"],
            kind=kind,
            correlation_id=data.get("correlation_id") or data["session_id"],
            logical_channel=data["logical_channel"],
            device_id=data.get("device_id"),
            vehicle_id=data.get("vehicle_id"),
            organization_id=data.get("organization_id"),
            audio_codec=data.get("audio_codec"),
        )
        token = mint_token(session_id=session.session_id, secret=self._viewer_token_secret)
        return {
            "ok": True,
            "session_id": session.session_id,
            "viewer_token": token,
            "ingest_host": self._public_ingest_host,
            "ingest_port": self._ingest_port,
        }

    async def _respond(self, request_id: str, response: dict[str, Any]) -> None:
        response_key = f"{self._response_key_prefix}:{request_id}"
        await self._redis.rpush(response_key, json.dumps(response))
        await self._redis.expire(response_key, self._response_ttl_seconds)

    async def run_forever(self) -> None:
        """**The exact root cause of a real, live-reproduced outage (2026-08-19).** This loop
        had no protection at all: a `redis.exceptions.BusyLoadingError` (Redis reloading its
        dataset - observed live, but any transient Redis error would do the same) on this task's
        very first `poll_once` call propagated straight out of `while True`, permanently killing
        the `asyncio.Task` for the rest of the process's life. Nothing ever awaits or logs a
        fire-and-forget task's result until shutdown, so this was completely invisible - the
        Business API's own `Jt1078RelayRpcClient.call` kept `RPUSH`-ing real requests onto
        `raad:jt1078:session_requests` (confirmed live: 22+ piled up, unread), every one of them
        silently timing out from the caller's side with no indication the relay itself was the
        problem, until this process was actually restarted and `stop()`'s own `await
        self._session_request_task` finally surfaced the buried exception. Matches the fix
        already applied to the two structurally identical loops on the device-gateway side
        (`RedisDeviceRegistryConsumer`/`RedisVideoSignalingConsumer.run_forever`) and this
        platform's own established resilient-loop shape (`backend/raad/core/workers/base.py
        Worker._tick`: catch, log, never let one bad iteration kill the loop) - `poll_once`'s own
        request/response shape (nothing is acked or removed from the list until a response is
        pushed) already makes a retried poll safe to repeat."""
        while True:
            try:
                await self.poll_once()
            except Exception as exc:  # noqa: BLE001 - a transient Redis error must not kill this loop
                log_with_fields(logger, 40, "session_request_poll_failed", error=str(exc))
                await asyncio.sleep(1.0)
