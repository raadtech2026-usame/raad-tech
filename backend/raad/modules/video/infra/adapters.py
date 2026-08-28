"""`Jt1078RelayAdapter` — the real, native `VideoProviderPort` implementation (JT1078 backend-
integration phase), closing the gap the prior JT1078 implementation phases' own reports flagged:
"no Business-API-side publisher of these events was built... no approved document specifies the
backend<->relay transport." Connects the already-built pieces end to end:

`VideoApplicationService` -> `Jt1078RelayAdapter` -> `services/jt1078` (session creation, over
`Jt1078RelayRpcClient`) -> `device-gateway` (device-start signal, over the existing `BrokerPort`/
`raad:events`, consumed by the already-built `RedisVideoSignalingConsumer`) -> the MDVR.

**Two distinct Redis-mediated calls per `start_live`/`start_playback`, deliberately not one:**
1. `Jt1078RelayRpcClient.call(...)` — a synchronous-style RPC to the relay (its own dedicated
   Redis list pair, `infra/jt1078_relay_client.py`'s own docstring), returning the relay's ingest
   host/port and a signed viewer token. The relay does not signal the device itself (ADR-0024 §6
   step 3/§8 — that remains this adapter's own job, unchanged by this phase).
2. A `Jt1078SignalCommandRequested` `DomainEvent`, published via the **existing** `BrokerPort`
   (`core/events/ports.py`) onto the **existing** `raad:events` stream — no new broker mechanism,
   direct reuse of the wire contract `device-gateway`'s `RedisVideoSignalingConsumer` already
   consumes (`services/device-gateway/src/vendors/jt808/commands/
   redis_video_signaling_consumer.py`'s own module docstring is the reference definition this
   payload shape matches exactly).

**`stop` only calls the relay** — `SessionManager.end_session` (relay-side) already publishes its
own device stop-signal onto the same stream (ADR-0024 §5 point 4, already implemented in the
prior JT1078 relay phase); duplicating that call here would send the device two redundant stop
commands for one teardown.

**No media byte ever reaches this adapter, this module, or the FastAPI process it runs in** — the
returned `stream_url` is a `ws://.../viewer?token=...` URL pointing directly at the relay; the
viewer (the React frontend) connects to it directly, never through the Business API
(`.claude/rules/architecture.md` #2/#3, this phase's own explicit "do not put media bytes through
the FastAPI backend" instruction).

**`organization_id`/`vehicle_id` are not threaded through to the relay** — `VideoProviderPort`'s
signature carries neither (see `application/ports.py`'s own docstring for why only `terminal_id`/
`channel_no` were added), and both are optional, enrichment-only fields on the relay's own
`VideoSession` (`services/jt1078/src/session/video_session.py`) used solely for published-event
observability, never for correctness — omitting them is a disclosed simplification, not a
functional gap.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from raad.core.events.base import DomainEvent
from raad.core.events.ports import BrokerPort
from raad.modules.video.application.ports import VideoProviderPort
from raad.modules.video.infra.jt1078_relay_client import Jt1078RelayRpcClient

_SIGNAL_EVENT_TYPE = "Jt1078SignalCommandRequested"


class Jt1078RelayAdapter(VideoProviderPort):
    def __init__(
        self,
        *,
        rpc_client: Jt1078RelayRpcClient,
        broker: BrokerPort,
        viewer_base_url: str,
    ) -> None:
        self._rpc = rpc_client
        self._broker = broker
        self._viewer_base_url = viewer_base_url.rstrip("/")

    async def start_live(
        self,
        *,
        device_id: str,
        camera_id: str,
        terminal_id: str,
        channel_no: int,
        reference: str,
        audio_codec: int | None = None,
    ) -> str:
        response = await self._rpc.call(
            "create_live_session",
            {
                "session_id": reference,
                "correlation_id": reference,
                "terminal_id": terminal_id,
                "logical_channel": channel_no,
                "device_id": device_id,
                "audio_codec": audio_codec,
            },
        )
        await self._signal_device_start(
            command="live_video_request",
            terminal_id=terminal_id,
            correlation_id=reference,
            fields={
                "server_ip": response["ingest_host"],
                "tcp_port": response["ingest_port"],
                "udp_port": 0,
                "logical_channel": channel_no,
                "data_type": 0,  # 0 = A/V, spec Table 6.2
                "stream_type": 0,  # 0 = main stream
            },
        )
        return self._viewer_url(response["viewer_token"])

    async def start_playback(
        self,
        *,
        device_id: str,
        camera_id: str,
        terminal_id: str,
        channel_no: int,
        window_start: datetime,
        window_end: datetime,
        reference: str,
        audio_codec: int | None = None,
    ) -> str:
        response = await self._rpc.call(
            "create_playback_session",
            {
                "session_id": reference,
                "correlation_id": reference,
                "terminal_id": terminal_id,
                "logical_channel": channel_no,
                "device_id": device_id,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "audio_codec": audio_codec,
            },
        )
        await self._signal_device_start(
            command="playback_request",
            terminal_id=terminal_id,
            correlation_id=reference,
            fields={
                "server_ip": response["ingest_host"],
                "tcp_port": response["ingest_port"],
                "udp_port": 0,
                "logical_channel": channel_no,
                "av_type": 0,  # 0 = A/V, spec Table 6.10
                "stream_type": 0,
                "storage_type": 0,
                "playback_mode": 0,  # 0 = normal playback
                "start_time": window_start.isoformat(),
                "end_time": window_end.isoformat(),
            },
        )
        return self._viewer_url(response["viewer_token"])

    async def stop(self, *, reference: str) -> None:
        await self._rpc.call("end_session", {"session_id": reference})

    def _viewer_url(self, viewer_token: str) -> str:
        return f"{self._viewer_base_url}/viewer?token={viewer_token}"

    async def _signal_device_start(
        self, *, command: str, terminal_id: str, correlation_id: str, fields: dict
    ) -> None:
        now = datetime.now(timezone.utc)
        await self._broker.publish(
            DomainEvent(
                event_id=str(uuid.uuid4()),
                event_type=_SIGNAL_EVENT_TYPE,
                version=1,
                occurred_at=now,
                org_id=None,
                correlation_id=correlation_id,
                payload={
                    "terminal_id": terminal_id,
                    "correlation_id": correlation_id,
                    "command": command,
                    "fields": fields,
                },
                aggregate_type="Device",
                aggregate_id=terminal_id,
            )
        )
