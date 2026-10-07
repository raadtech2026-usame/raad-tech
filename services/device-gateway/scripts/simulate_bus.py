"""Development only: play the part of one bus terminal reporting positions.

For testing the Parent app's live tracking and the stop notifications without a bus on the
road. It does not open a JT808 socket: it calls the gateway's own `RedisLatestPositionWriter`
and `RedisEventPublisher` with a `DevicePositionReported`, exactly what `LocationHandler` does
after parsing a real `0x0200`, so the wire formats cannot drift from the real ones.

    python scripts/simulate_bus.py --cache-url redis://:pw@localhost:6379/0 \
        --broker-url redis://:pw@localhost:6379/1 --organization-id <id> --vehicle-id <id> \
        --points "2.0300,45.3000;2.0328,45.3038;2.0390,45.3120" --interval 5 --steps 10

`--points` are waypoints; the bus moves between consecutive ones in `--steps` equal steps, one
report every `--interval` seconds. The positions are invented. Never point this at production.

Use exactly the Redis URLs the backend uses (`RAAD_REDIS__URL`, `RAAD_BROKER__URL`). On a machine
with a second Redis installed, `127.0.0.1` and `localhost` can be different servers, and the
script then reports success while the backend sees nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redis.asyncio import Redis  # noqa: E402

from src.events.device_position_reported import DevicePositionReported  # noqa: E402
from src.events.redis_event_publisher import RedisEventPublisher  # noqa: E402
from src.latest_position.redis_latest_position_writer import (  # noqa: E402
    RedisLatestPositionWriter,
)

#: A fixed, obviously synthetic device id (26 characters, like a ULID).
SIMULATED_DEVICE_ID = "01SMVLATEDDEV1CE0000000000"


def _heading(a: tuple[float, float], b: tuple[float, float]) -> int:
    d_lng = math.radians(b[1] - a[1])
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    y = math.sin(d_lng) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lng)
    return int((math.degrees(math.atan2(y, x)) + 360) % 360)


def _path(points: list[tuple[float, float]], steps: int):
    for start, end in zip(points, points[1:]):
        for i in range(steps):
            t = i / steps
            yield (
                start[0] + (end[0] - start[0]) * t,
                start[1] + (end[1] - start[1]) * t,
                _heading(start, end),
            )
    yield (*points[-1], _heading(points[-2], points[-1]) if len(points) > 1 else 0)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cache-url", required=True)
    parser.add_argument("--broker-url", required=True)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--vehicle-id", required=True)
    parser.add_argument("--points", required=True, help="lat,lng;lat,lng;...")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument("--speed-kph", type=int, default=30)
    args = parser.parse_args()

    points = [tuple(float(v) for v in p.split(",")) for p in args.points.split(";")]
    cache = Redis.from_url(args.cache_url, decode_responses=True)
    broker = Redis.from_url(args.broker_url, decode_responses=True)
    writer = RedisLatestPositionWriter(cache)
    publisher = RedisEventPublisher(broker)

    try:
        for latitude, longitude, heading in _path(points, args.steps):
            now = datetime.now(timezone.utc)
            event = DevicePositionReported(
                organization_id=args.organization_id,
                vehicle_id=args.vehicle_id,
                device_id=SIMULATED_DEVICE_ID,
                terminal_id="SIMULATED",
                trip_id=None,  # the device plane does not know trips; neither does this
                latitude=round(latitude, 6),
                longitude=round(longitude, 6),
                speed_kph=args.speed_kph,
                heading_deg=heading,
                alarm_flags=0,
                event_time=now,
                is_backfill=False,
                received_at=now,
            )
            await writer.write(event)
            await publisher.publish(event)
            print(f"{now:%H:%M:%S} {event.latitude:.5f},{event.longitude:.5f} heading {heading}")
            await asyncio.sleep(args.interval)
    finally:
        await cache.aclose()
        await broker.aclose()


if __name__ == "__main__":
    asyncio.run(main())
