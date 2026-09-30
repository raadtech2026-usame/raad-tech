"""Cross-module adapters for safety alerts (ADR-0055, ADR-0057), in the composition root for the
same reason as `erp_adapters.py`: neither module imports the other.

* `TransportOpsActiveTripAdapter` — `tracking` -> `transport_ops`: the trip, and its driver, in
  progress on a bus when an alarm started.
* `BrokerDeviceCommandAdapter` — `tracking` -> the device plane: publishes a command request on
  the existing `raad:events` stream in the `Jt1078SignalCommandRequested` shape the device
  gateway's command consumer already reads (ADR-0057), exactly as the video adapter does.
"""

from __future__ import annotations

from datetime import datetime, timezone

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.core.events.ports import BrokerPort
from raad.core.ids.generator import generate_ulid
from raad.core.logging.setup import get_logger
from raad.modules.tracking.application.ports import ActiveTrip, ActiveTripPort, DeviceCommandPort
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import GetActiveTripForVehicleQuery
from raad.modules.transport_ops.application.services import TripApplicationService

logger = get_logger("raad.safety.adapters")


class TransportOpsActiveTripAdapter(ActiveTripPort):
    """A lookup failure never stops an alert being recorded: the alert simply carries no trip."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def active_trip_for_vehicle(self, vehicle_id: str) -> ActiveTrip | None:
        try:
            service: TripApplicationService = self._container.resolve(TripApplicationService)
            trip = await service.get_active_trip_for_vehicle(
                GetActiveTripForVehicleQuery(vehicle_id=vehicle_id),
                uow=self._container.resolve(TransportOpsUnitOfWork),
            )
        except Exception:  # noqa: BLE001 - see class docstring
            logger.exception("active_trip_lookup_failed", extra={"vehicle_id": vehicle_id})
            return None
        return ActiveTrip(trip_id=trip.id, driver_id=trip.driver_id) if trip is not None else None


class BrokerDeviceCommandAdapter(DeviceCommandPort):
    def __init__(self, broker: BrokerPort) -> None:
        self._broker = broker

    async def confirm_alarm(self, *, terminal_id: str, alarm_type_mask: int) -> bool:
        correlation_id = generate_ulid()
        await self._broker.publish(
            DomainEvent(
                event_id=generate_ulid(),
                event_type="Jt1078SignalCommandRequested",
                version=1,
                occurred_at=datetime.now(timezone.utc),
                org_id=None,
                correlation_id=correlation_id,
                payload={
                    "terminal_id": terminal_id,
                    "correlation_id": correlation_id,
                    "command": "confirm_alarm",
                    "fields": {"alarm_serial_no": 0, "alarm_type_mask": alarm_type_mask},
                },
                aggregate_type="Device",
                aggregate_id=terminal_id,
            )
        )
        return True
