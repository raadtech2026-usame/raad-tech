"""`DeviceGateway` — the single process entrypoint for every device-plane vendor adapter
(device-gateway multi-vendor architecture, `docs/architecture/adr/
0010-device-gateway-multi-vendor-architecture.md`). Starts and stops each configured
`DeviceProtocolAdapter` (currently `vendors.jt808.server.Jt808Server` and `vendors.lsz.server.
MdvrServer`) under one shared signal handler, so operating this deployable no longer means
picking one vendor's own `server.py`/`main()` — this is the module that actually gets run.

**Adding a new vendor never touches this file's own orchestration logic** — only the list built
in `_build_adapters()` grows by one line, constructing that vendor's own adapter class (itself
implementing `src.adapter.DeviceProtocolAdapter`) with whatever config/ports it needs. Every
adapter receives the *same* `EventPublisher` instance (so `DevicePositionReported`/`DeviceOnline`/
`DeviceOffline`/`DeviceAlarmRaised` from every vendor flow through one shared publish mechanism,
per this refactor's own "vendor-agnostic event bus" requirement) — the Business Plane consuming
those events downstream has no way to tell, and no need to know, which vendor adapter published
any given one.

**Redis wiring (device-gateway Redis integration) — conditional on `BrokerConfig`, the same
"fail loudly, don't fake it" pattern the Business API's own `core/di/bootstrap.py` already
applies to every broker-dependent binding:** when a broker URL is configured (or a `redis_client`
is injected directly, the seam tests use), this gateway constructs one shared `RedisEventPublisher`
(passed to every adapter) and **one shared `DeviceRegistryProjection`** fed by a
`RedisDeviceRegistryConsumer` background task — vendor-agnostic by design (indexed by both
`terminal_id` and `serial_number`), so the same projection instance backs **both** the LSZ
adapter's real `ProjectionBackedMdvrProvisioningPort` **and** the JT808 adapter's real
`ProjectionBackedJt808ProvisioningPort` (JT808 device-plane integration gap — closes the identity/
provisioning half; `0x0102` authentication verification itself remains deliberately unresolved,
see `vendors/jt808/handlers/provisioning_port.py`'s own docstring). Without a broker configured,
every adapter falls back to exactly what it already defaulted to (`LoggingEventPublisher`,
`NullMdvrDeviceProvisioningPort`/`NullDeviceProvisioningPort`) — nothing about the unconfigured
path changes.

Each adapter's own `serve_forever()` remains for standalone single-adapter use (its own tests, or
running just one adapter in isolation) — this composition root calls `start()`/`stop()` on each
adapter directly instead, since letting every adapter install its own `SIGINT`/`SIGTERM` handler
would conflict once more than one runs in the same process (`src/adapter.py`'s own docstring).

**`RedisVideoSignalingConsumer` (JT/T 1078 video-signaling forwarding phase, ADR-0024 §8) — a
third broker participant, symmetric with `RedisDeviceRegistryConsumer` but in the opposite
direction:** the registry consumer reads *facts about devices* from the broker; this one reads
*commands to send devices* from the broker (Business API -> device-gateway) and forwards them
through `Jt808Server.command_sender` on the JT808 adapter's already-open, already-authenticated
connection for that terminal. Bound only when a broker is configured, mirroring every other
Redis-dependent binding in this file's own conditional pattern — `Jt808Server` itself always
constructs a real `CommandSender` regardless (see that class's own module docstring), so nothing
about the JT808 adapter's own behavior changes when no broker is configured; only the *inbound*
route for triggering it (a real broker event vs. a direct method call, e.g. from a test) differs.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from redis.asyncio import Redis

from src.adapter import DeviceProtocolAdapter
from src.broker_config import BrokerConfig
from src.events.publisher_port import EventPublisher, LoggingEventPublisher
from src.events.redis_event_publisher import RedisEventPublisher
from src.latest_position.redis_latest_position_writer import RedisLatestPositionWriter
from src.latest_position.writer_port import LatestPositionWriter, LoggingLatestPositionWriter
from src.logging_setup import configure_logging, get_logger, log_with_fields
from src.registry.device_registry_projection import DeviceRegistryProjection
from src.registry.redis_device_registry_consumer import RedisDeviceRegistryConsumer
from src.vendors.jt808.commands.redis_video_signaling_consumer import (
    RedisVideoSignalingConsumer,
)
from src.vendors.jt808.config import ServerConfig as Jt808Config
from src.vendors.jt808.handlers.provisioning_port import ProjectionBackedJt808ProvisioningPort
from src.vendors.jt808.server import Jt808Server
from src.vendors.lsz.config import MdvrServerConfig as LszConfig
from src.vendors.lsz.handlers.provisioning_port import ProjectionBackedMdvrProvisioningPort
from src.vendors.lsz.server import MdvrServer

logger = get_logger("device_gateway.gateway")


class DeviceGateway:
    def __init__(
        self,
        *,
        event_publisher: EventPublisher | None = None,
        jt808_config: Jt808Config | None = None,
        lsz_config: LszConfig | None = None,
        broker_config: BrokerConfig | None = None,
        redis_client: Redis | None = None,
    ) -> None:
        self._broker_config = broker_config or BrokerConfig.from_env()
        self._redis_client = redis_client or self._build_redis_client()

        self._registry_projection: DeviceRegistryProjection | None = None
        self._registry_consumer: RedisDeviceRegistryConsumer | None = None
        self._registry_consumer_task: asyncio.Task | None = None
        self._video_signaling_consumer: RedisVideoSignalingConsumer | None = None
        self._video_signaling_consumer_task: asyncio.Task | None = None

        self._event_publisher = event_publisher or self._build_event_publisher()
        self._latest_position_writer = self._build_latest_position_writer()
        jt808_provisioning = self._build_jt808_provisioning()
        lsz_provisioning = self._build_lsz_provisioning()

        self._jt808_server = Jt808Server(
            jt808_config,
            device_provisioning=jt808_provisioning,
            event_publisher=self._event_publisher,
        )
        self._adapters: list[DeviceProtocolAdapter] = [
            self._jt808_server,
            MdvrServer(
                lsz_config,
                device_provisioning=lsz_provisioning,
                event_publisher=self._event_publisher,
                latest_position_writer=self._latest_position_writer,
            ),
        ]
        if self._redis_client is not None:
            self._video_signaling_consumer = RedisVideoSignalingConsumer(
                self._redis_client, command_sender=self._jt808_server.command_sender
            )

    def _build_redis_client(self) -> Redis | None:
        if not self._broker_config.url:
            return None
        return Redis.from_url(self._broker_config.url, decode_responses=True)

    def _build_event_publisher(self) -> EventPublisher:
        if self._redis_client is not None:
            return RedisEventPublisher(self._redis_client)
        return LoggingEventPublisher()

    def _build_latest_position_writer(self) -> LatestPositionWriter:
        """`vehicle:{id}:last` snapshot writer (roadmap A2) — same shared Redis client and same
        conditional-on-broker-config pattern as `_build_event_publisher` above. Only wired into
        `MdvrServer` (the LSZ adapter, the currently-integrated hardware) — `Jt808Server` stays
        untouched per CLAUDE.md's "kept, untouched, dormant" posture for the JT/T 808 code."""
        if self._redis_client is not None:
            return RedisLatestPositionWriter(self._redis_client)
        return LoggingLatestPositionWriter()

    def _build_registry_projection(self) -> DeviceRegistryProjection | None:
        """The shared, vendor-agnostic device-registry read-model (device-gateway Redis
        integration) — built once and handed to every vendor's own `ProjectionBacked*
        ProvisioningPort`, since `DeviceRegistryProjection` has always indexed by both
        `terminal_id` (JT808) and `serial_number` (LSZ) for exactly this reason. `None` when no
        broker is configured (see `_build_lsz_provisioning`'s original docstring, now shared)."""
        if self._redis_client is None:
            return None
        if self._registry_projection is None:
            self._registry_projection = DeviceRegistryProjection()
            self._registry_consumer = RedisDeviceRegistryConsumer(
                self._redis_client, projection=self._registry_projection
            )
        return self._registry_projection

    def _build_jt808_provisioning(self):
        projection = self._build_registry_projection()
        if projection is None:
            return None  # Jt808Server falls back to its own NullDeviceProvisioningPort default
        return ProjectionBackedJt808ProvisioningPort(projection)

    def _build_lsz_provisioning(self):
        projection = self._build_registry_projection()
        if projection is None:
            return None  # MdvrServer falls back to its own NullMdvrDeviceProvisioningPort default
        return ProjectionBackedMdvrProvisioningPort(projection)

    @property
    def adapters(self) -> tuple[DeviceProtocolAdapter, ...]:
        return tuple(self._adapters)

    @property
    def registry_projection(self) -> DeviceRegistryProjection | None:
        """`None` unless a broker is configured — see class docstring."""
        return self._registry_projection

    def adapter(self, name: str) -> DeviceProtocolAdapter:
        for adapter in self._adapters:
            if adapter.name == name:
                return adapter
        raise LookupError(f"No adapter registered under name {name!r}.")

    async def start(self) -> None:
        # A real, production-blocking gap found live (2026-08-19): `DeviceRegistryProjection`
        # is in-memory only, but the consumer *group* backing it is durable Redis state — a
        # bare restart previously left every already-provisioned device unresolvable
        # (`terminal_not_found`) until some unrelated new event happened to touch it again. Must
        # run to completion *before* any adapter below starts accepting connections, so a device
        # can never race a still-empty projection — see `RedisDeviceRegistryConsumer.
        # replay_from_start`'s own docstring for the full incident and why this is safe to run
        # unconditionally on every startup, not just after a crash.
        if self._registry_consumer is not None:
            await self._registry_consumer.replay_from_start()
        for adapter in self._adapters:
            await adapter.start()
            log_with_fields(
                logger,
                20,
                "adapter_started",
                adapter=adapter.name,
                bound_port=adapter.bound_port,
            )
        if self._registry_consumer is not None:
            self._registry_consumer_task = asyncio.create_task(
                self._registry_consumer.run_forever()
            )
            log_with_fields(logger, 20, "device_registry_consumer_started")
        if self._video_signaling_consumer is not None:
            self._video_signaling_consumer_task = asyncio.create_task(
                self._video_signaling_consumer.run_forever()
            )
            log_with_fields(logger, 20, "video_signaling_consumer_started")

    async def stop(self) -> None:
        if self._registry_consumer_task is not None:
            self._registry_consumer_task.cancel()
            try:
                await self._registry_consumer_task
            except asyncio.CancelledError:
                pass
            self._registry_consumer_task = None
            log_with_fields(logger, 20, "device_registry_consumer_stopped")
        if self._video_signaling_consumer_task is not None:
            self._video_signaling_consumer_task.cancel()
            try:
                await self._video_signaling_consumer_task
            except asyncio.CancelledError:
                pass
            self._video_signaling_consumer_task = None
            log_with_fields(logger, 20, "video_signaling_consumer_stopped")
        for adapter in self._adapters:
            await adapter.stop()
            log_with_fields(logger, 20, "adapter_stopped", adapter=adapter.name)

    async def serve_forever(self) -> None:
        await self.start()
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _handle_signal() -> None:
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except NotImplementedError:
                pass  # Windows: add_signal_handler isn't supported for these signals

        await stop_event.wait()
        await self.stop()


async def main() -> None:
    configure_logging(level=logging.INFO)
    gateway = DeviceGateway()
    await gateway.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
