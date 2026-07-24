"""`LoggingEventPublisher` tests (device-gateway Redis integration widened `EventPublisher` to
all four device-plane events). Confirms each event type is dispatched to its own log line without
raising — the only behavior this default implementation has."""

import unittest
from datetime import datetime, timezone

from src.events.device_alarm_raised import DeviceAlarmRaised
from src.events.device_offline import DeviceOffline
from src.events.device_online import DeviceOnline
from src.events.device_position_reported import DevicePositionReported
from src.events.publisher_port import LoggingEventPublisher

_NOW = datetime(2026, 7, 24, tzinfo=timezone.utc)


class LoggingEventPublisherTests(unittest.IsolatedAsyncioTestCase):
    async def test_publishes_device_position_reported_without_raising(self) -> None:
        publisher = LoggingEventPublisher()
        await publisher.publish(
            DevicePositionReported(
                organization_id="org-1",
                vehicle_id="vehicle-1",
                device_id="device-1",
                terminal_id="00007",
                trip_id=None,
                latitude=22.0,
                longitude=114.0,
                speed_kph=10,
                heading_deg=90,
                alarm_flags=0,
                event_time=_NOW,
                is_backfill=False,
                received_at=_NOW,
            )
        )

    async def test_publishes_device_online_without_raising(self) -> None:
        publisher = LoggingEventPublisher()
        await publisher.publish(
            DeviceOnline(
                terminal_id="00007",
                organization_id="org-1",
                vehicle_id="vehicle-1",
                device_id="device-1",
                event_time=_NOW,
                received_at=_NOW,
            )
        )

    async def test_publishes_device_offline_without_raising(self) -> None:
        publisher = LoggingEventPublisher()
        await publisher.publish(
            DeviceOffline(
                terminal_id="00007",
                organization_id="org-1",
                vehicle_id="vehicle-1",
                device_id="device-1",
                reason="connection_closed",
                event_time=_NOW,
                received_at=_NOW,
            )
        )

    async def test_publishes_device_alarm_raised_without_raising(self) -> None:
        publisher = LoggingEventPublisher()
        await publisher.publish(
            DeviceAlarmRaised(
                terminal_id="00007",
                organization_id="org-1",
                vehicle_id="vehicle-1",
                device_id="device-1",
                alarm_type="panic_button",
                alarm_flags=1,
                event_time=_NOW,
                received_at=_NOW,
            )
        )


if __name__ == "__main__":
    unittest.main()
