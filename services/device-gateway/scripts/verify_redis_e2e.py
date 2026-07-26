"""End-to-end verification: LSZ MDVR device -> Redis (`raad:events`) -> Business API decode
(ADR-0012, `docs/architecture/adr/0012-development-redis-environment.md`); and (roadmap A2,
`docs/architecture/post-f7-production-readiness-roadmap.md`) LSZ MDVR device -> Redis
(`vehicle:{id}:last`) -> Business API `RedisLatestPositionPort.get_latest`.

Drives a real `MdvrServer` over a real loopback TCP socket with the same worked LSZ registration/
position frames `tests/test_mdvr_server_integration.py` already validates, through a real
`RedisEventPublisher`/`RedisLatestPositionWriter` against a real, reachable Redis (no fake/
in-memory client anywhere in this script — that is the entire point: existing unit tests already
prove the code against a fake client, this script proves the same code against a real
`redis-server`). The published Stream entry is then decoded with the Business API's own real
`raad.core.events.redis_streams._fields_to_event` and run through its own real
`DevicePositionReportedProcessor`; the `vehicle:{id}:last` key is read back through the Business
API's own real `RedisLatestPositionPort.get_latest` — proving the full cross-deployable wire
contract for both paths, not just "some bytes landed in Redis."

**Deliberate, scoped exception to `.claude/rules/architecture.md` #2** ("no dependency between
`backend/raad` and this deployable, even in tests"): this script imports backend code directly,
because verifying that exact cross-deployable compatibility is its only job — the same exception
ADR-0010 §6 already established for its own one-off check, made a committed, reusable script here
instead of a one-off. It is not part of either deployable's own package, runtime, or test suite
(deliberately outside both `src/` and `tests/`) and is never imported by production code on either
side.

**What this script does NOT verify** (out of scope, already covered elsewhere): actual PostgreSQL
persistence via `TrackingApplicationService.record_vehicle_position` — that has its own dedicated,
already-passing test coverage (`backend/tests/unit/test_tracking_subscribers.py`,
`backend/tests/integration/test_tracking_repository.py`). The processor is exercised here against
a fake, in-memory `TrackingApplicationService`/`TrackingUnitOfWork` (the same fake pattern
`test_tracking_subscribers.py` itself uses) precisely so this script's own dependency is Redis
alone, not also a live Postgres.

Usage:
    python scripts/verify_redis_e2e.py [--redis-url redis://localhost:6379/0]

Exits 0 and prints "PASS" on success; exits 1 and prints exactly what failed otherwise (a
connection failure to Redis is a real, reported FAIL here, never silently skipped).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_DEVICE_GATEWAY_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _DEVICE_GATEWAY_ROOT.parents[1]
_BACKEND_ROOT = _REPO_ROOT / "backend"

for _path in (_DEVICE_GATEWAY_ROOT, _BACKEND_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from redis.asyncio import Redis  # noqa: E402

from src.events.redis_event_publisher import RedisEventPublisher  # noqa: E402
from src.latest_position.redis_latest_position_writer import (  # noqa: E402
    RedisLatestPositionWriter,
)
from src.vendors.lsz.config import MdvrServerConfig  # noqa: E402
from src.vendors.lsz.handlers.provisioning_port import (  # noqa: E402
    InMemoryMdvrDeviceProvisioningPort,
)
from src.vendors.lsz.server import MdvrServer  # noqa: E402

from raad.core.di.container import Container  # noqa: E402
from raad.core.events.redis_streams import DEFAULT_STREAM_NAME, _fields_to_event  # noqa: E402
from raad.core.ids.generator import UlidGenerator  # noqa: E402
from raad.core.time.clock import SystemClock  # noqa: E402
from raad.modules.tracking.application.commands import (  # noqa: E402
    RecordVehiclePositionCommand,
)
from raad.modules.tracking.application.ports import TrackingUnitOfWork  # noqa: E402
from raad.modules.tracking.application.services import TrackingApplicationService  # noqa: E402
from raad.modules.tracking.events.subscribers import (  # noqa: E402
    DevicePositionReportedProcessor,
)
from raad.modules.tracking.infra.adapters import RedisLatestPositionPort  # noqa: E402
from raad.modules.tracking.domain.value_objects import VehicleId  # noqa: E402
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork  # noqa: E402
from raad.modules.transport_ops.application.services import TripApplicationService  # noqa: E402

_DEVICE_SERIAL_NUMBER = "00007"
_ORG_ID = "org-e2e-verify"
_VEHICLE_ID = "vehicle-e2e-verify"
_DEVICE_ID = "device-e2e-verify"

# Same worked device-00007 examples `tests/test_mdvr_server_integration.py` validates.
_REGISTRATION_FRAME = (
    b"$$dc0227,20,V101,00007,,180903 094112,A0010,114,3,341826000,22,40,236220000,0.00,7000,"
    b"000E00010101D383,0000000000000000,0.00,0.00,0.00,0,0.00,67,0|0.00|0|0|0|0|0|0|0,,V1.0.0.1,"
    b"4108,,0,0,0,123,2,,1,1,2,101,,D2017120781,V6.1.45 20160519,#"
)
_POSITION_FRAME = (
    b"$$dc0165,192,V114,00007,,180903 135949,A0010,114,3,338214000,22,40,220920000,0.00,1521000,"
    b"000E00010101D383,0000000000000000,0.00,0.00,0.00,0,0.00,2266,0|0.00|0|0|0|0|0|0|0,1#"
)


class _FakeUnitOfWork:
    """Mirrors `test_tracking_subscribers.py`'s own fake exactly — this script's own dependency
    is Redis, not Postgres; see module docstring."""


class _RecordingTrackingService:
    def __init__(self) -> None:
        self.recorded_positions: list[RecordVehiclePositionCommand] = []

    async def record_vehicle_position(self, command, *, uow):
        self.recorded_positions.append(command)

    async def record_backfill_position(self, command, *, uow):
        raise AssertionError("The verification position frame is not backfill-flagged.")


class _NoActiveTripService:
    """Roadmap A4: `DevicePositionReportedProcessor` now resolves the active trip via
    `TripApplicationService` on every live position - mirrors `test_tracking_subscribers.py`'s
    own `_FakeTripApplicationService` default (no active trip), keeping this script's own
    dependency Redis alone, not also a live Postgres (module docstring)."""

    async def get_active_trip_for_vehicle(self, query, *, uow):
        return None


async def _check_redis_reachable(redis_client: Redis) -> None:
    await redis_client.ping()


async def run(redis_url: str) -> bool:
    print(f"[1/6] Connecting to Redis at {redis_url} ...")
    redis_client = Redis.from_url(redis_url, decode_responses=True)
    try:
        await _check_redis_reachable(redis_client)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        print(f"FAIL: could not reach Redis at {redis_url}: {exc!r}")
        print(
            "This is expected in an environment with no Docker/redis-server running yet - "
            "see ADR-0012 for how to bring one up (docker/docker-compose.yml)."
        )
        await redis_client.aclose()
        return False
    print("      Redis reachable (PING succeeded).")

    print(
        "[2/7] Starting a real MdvrServer wired to a real RedisEventPublisher + "
        "RedisLatestPositionWriter ..."
    )
    provisioning = InMemoryMdvrDeviceProvisioningPort()
    provisioning.register_known_device(
        device_serial_number=_DEVICE_SERIAL_NUMBER,
        device_id=_DEVICE_ID,
        vehicle_id=_VEHICLE_ID,
        organization_id=_ORG_ID,
    )
    publisher = RedisEventPublisher(redis_client)
    latest_position_writer = RedisLatestPositionWriter(redis_client)
    server = MdvrServer(
        MdvrServerConfig(host="127.0.0.1", port=0),
        device_provisioning=provisioning,
        event_publisher=publisher,
        latest_position_writer=latest_position_writer,
    )
    await server.start()

    last_id = "0-0"
    entries = await redis_client.xrevrange(DEFAULT_STREAM_NAME, count=1)
    if entries:
        last_id = entries[0][0]

    try:
        print("[3/7] Sending a real LSZ registration frame over a real TCP socket ...")
        reader, writer = await asyncio.open_connection("127.0.0.1", server.bound_port)
        writer.write(_REGISTRATION_FRAME)
        await writer.drain()
        await asyncio.wait_for(reader.read(256), timeout=2.0)  # discard C100 ack

        print("[4/7] Sending a real LSZ position (V114) frame ...")
        writer.write(_POSITION_FRAME)
        await writer.drain()
        await asyncio.sleep(0.2)  # let the async dispatch/publish complete

        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
    finally:
        await server.stop()

    print(f"[5/7] Reading back {DEFAULT_STREAM_NAME!r} from Redis and decoding it ...")
    raw_entries = await redis_client.xrange(DEFAULT_STREAM_NAME, min=f"({last_id}", count=50)
    matching = None
    for _entry_id, fields in raw_entries:
        event = _fields_to_event(fields)
        if (
            event.event_type == "DevicePositionReported"
            and event.aggregate_type == "Vehicle"
            and event.aggregate_id == _VEHICLE_ID
        ):
            matching = event
            break

    if matching is None:
        print(
            f"FAIL: no DevicePositionReported event for vehicle {_VEHICLE_ID!r} found on "
            f"{DEFAULT_STREAM_NAME!r} after sending the position frame."
        )
        await redis_client.aclose()
        return False

    print(
        "      Decoded via the real backend raad.core.events.redis_streams._fields_to_event: "
        f"event_type={matching.event_type!r} aggregate_type={matching.aggregate_type!r} "
        f"aggregate_id={matching.aggregate_id!r} org_id={matching.org_id!r}"
    )

    print("[6/7] Running the decoded event through the real DevicePositionReportedProcessor ...")
    container = Container()
    service = _RecordingTrackingService()
    container.bind_singleton(TrackingApplicationService, service)
    container.bind_singleton(TrackingUnitOfWork, _FakeUnitOfWork())
    container.bind_singleton(TripApplicationService, _NoActiveTripService())
    container.bind_singleton(TransportOpsUnitOfWork, _FakeUnitOfWork())
    processor = DevicePositionReportedProcessor(container)
    await processor.process(matching)

    print(
        "[7/7] Reading back vehicle:{id}:last through the real "
        "RedisLatestPositionPort.get_latest ..."
    )
    latest_position_port = RedisLatestPositionPort(
        redis_client, clock=SystemClock(), id_generator=UlidGenerator()
    )
    latest = await latest_position_port.get_latest(VehicleId(_VEHICLE_ID))
    if latest is None:
        print(
            f"FAIL: RedisLatestPositionPort.get_latest returned None for vehicle "
            f"{_VEHICLE_ID!r} - vehicle:{{id}}:last was never written, or was written in a "
            f"shape this adapter could not parse."
        )
        await redis_client.aclose()
        return False
    if (
        str(latest.vehicle_id) != _VEHICLE_ID
        or str(latest.organization_id) != _ORG_ID
        or str(latest.device_id) != _DEVICE_ID
        or abs(latest.position.latitude - 22.672803) > 1e-4
        or abs(latest.position.longitude - 114.059395) > 1e-4
    ):
        print(f"FAIL: vehicle:{{id}}:last decoded to an unexpected snapshot: {latest!r}")
        await redis_client.aclose()
        return False
    print(
        "      RedisLatestPositionPort.get_latest matches the sent frame: "
        f"vehicle_id={latest.vehicle_id!r} lat={latest.position.latitude} "
        f"lng={latest.position.longitude}"
    )

    await redis_client.aclose()

    if len(service.recorded_positions) != 1:
        print(
            "FAIL: expected exactly one RecordVehiclePositionCommand, got "
            f"{len(service.recorded_positions)}."
        )
        return False

    command = service.recorded_positions[0]
    expected_lat, expected_lng = 22.672803, 114.059395
    if (
        command.vehicle_id != _VEHICLE_ID
        or command.device_id != _DEVICE_ID
        or command.organization_id != _ORG_ID
        or abs(command.latitude - expected_lat) > 1e-4
        or abs(command.longitude - expected_lng) > 1e-4
    ):
        print(f"FAIL: decoded command did not match the sent frame: {command!r}")
        return False

    print(
        "      RecordVehiclePositionCommand matches the sent frame: "
        f"vehicle_id={command.vehicle_id!r} lat={command.latitude} lng={command.longitude}"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("DEVICE_GATEWAY_BROKER_URL", "redis://localhost:6379/0"),
        help="Redis connection URL (default: $DEVICE_GATEWAY_BROKER_URL or redis://localhost:6379/0)",
    )
    args = parser.parse_args()

    ok = asyncio.run(run(args.redis_url))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
