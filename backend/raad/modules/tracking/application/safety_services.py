"""Safety alerts from device alarms (ADR-0055) and SOS confirmation on the terminal (ADR-0057).

The device plane publishes one `DeviceAlarmRaised` per alarm that *starts*; this service turns it
into a `SafetyAlert`. A repeat of the same type on the same bus while an alert is open updates
that alert instead of creating another, so a flapping bit is one alert and one notification.
"""

from __future__ import annotations

from datetime import timezone

from raad.core.errors.exceptions import NotFoundError, ValidationError
from raad.core.ids.generator import IdGenerator
from raad.core.logging.setup import get_logger
from raad.core.tenancy.principal import Principal
from raad.core.time.clock import Clock
from raad.modules.tracking.application.commands import RecordDeviceAlarmCommand
from raad.modules.tracking.application.ports import (
    ActiveTripPort,
    DeviceCommandPort,
    TrackingUnitOfWork,
)
from raad.modules.tracking.application.queries import ListSafetyAlertsQuery, SafetyAlertDTO
from raad.modules.tracking.domain.entities import SafetyAlert
from raad.modules.tracking.domain.value_objects import (
    ALARM_TYPES,
    DeviceConfirmation,
    OrganizationId,
    SafetyAlertId,
    SafetyAlertStatus,
    VehicleId,
)

logger = get_logger("raad.tracking.safety_alerts")

#: JT/T 808 `0x8203` alarm-type mask for the emergency (SOS) bit (ADR-0057).
_SOS_CONFIRMATION_MASK = 1 << 0


def safety_alert_to_dto(alert: SafetyAlert) -> SafetyAlertDTO:
    return SafetyAlertDTO(
        id=str(alert.id),
        organization_id=str(alert.organization_id),
        vehicle_id=str(alert.vehicle_id),
        device_id=str(alert.device_id) if alert.device_id else None,
        alarm_type=alert.alarm_type,
        is_critical=alert.is_critical,
        status=alert.status.value,
        raised_at=alert.raised_at,
        last_raised_at=alert.last_raised_at,
        received_at=alert.received_at,
        is_late=alert.is_late,
        occurrences=alert.occurrences,
        latitude=alert.latitude,
        longitude=alert.longitude,
        speed_kph=alert.speed_kph,
        trip_id=alert.trip_id,
        driver_id=alert.driver_id,
        incident_id=alert.incident_id,
        device_confirmation=alert.device_confirmation.value if alert.device_confirmation else None,
        acknowledged_at=alert.acknowledged_at,
        closed_at=alert.closed_at,
    )


class SafetyAlertApplicationService:
    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        active_trips: ActiveTripPort,
        device_commands: DeviceCommandPort | None,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._active_trips = active_trips
        self._device_commands = device_commands

    async def record_device_alarm(
        self, command: RecordDeviceAlarmCommand, *, uow: TrackingUnitOfWork
    ) -> SafetyAlertDTO | None:
        """Returns the alert, or `None` for an alarm type RAAD does not know (logged)."""
        if command.alarm_type not in ALARM_TYPES:
            logger.warning("device_alarm_unknown_type_ignored", extra={"alarm_type": command.alarm_type})
            return None
        # Read before any `add()`: a query after `add()` autoflushes (CLAUDE.md, Phase 2 lesson).
        active = await self._active_trips.active_trip_for_vehicle(command.vehicle_id)
        async with uow:
            existing = await uow.safety_alerts.find_open(VehicleId(command.vehicle_id), command.alarm_type)
            if existing is not None:
                existing.repeat(raised_at=command.event_time, clock=self._clock)
                alert = existing
            else:
                alert = SafetyAlert.raise_alarm(
                    id=SafetyAlertId(self._id_generator.new_id()),
                    organization_id=OrganizationId(command.organization_id),
                    vehicle_id=VehicleId(command.vehicle_id),
                    device_id=command.device_id,
                    terminal_id=command.terminal_id,
                    alarm_type=command.alarm_type,
                    raised_at=command.event_time,
                    received_at=command.received_at,
                    latitude=command.latitude,
                    longitude=command.longitude,
                    speed_kph=command.speed_kph,
                    trip_id=active.trip_id if active else None,
                    driver_id=active.driver_id if active else None,
                    clock=self._clock,
                )
                uow.safety_alerts.add(alert)
                uow.record_events(alert.pull_domain_events())
            await uow.commit()
            return safety_alert_to_dto(alert)

    async def list_alerts(
        self, query: ListSafetyAlertsQuery, *, uow: TrackingUnitOfWork
    ) -> list[SafetyAlertDTO]:
        valid = {s.value for s in SafetyAlertStatus}
        if any(s not in valid for s in query.statuses):
            raise ValidationError("Unknown alert status.")
        async with uow:
            alerts = await uow.safety_alerts.list_filtered(
                statuses=query.statuses or None,
                vehicle_id=VehicleId(query.vehicle_id) if query.vehicle_id else None,
                alarm_type=query.alarm_type,
                start=query.start.astimezone(timezone.utc) if query.start and query.start.tzinfo else query.start,
                end=query.end.astimezone(timezone.utc) if query.end and query.end.tzinfo else query.end,
            )
            return [safety_alert_to_dto(a) for a in alerts]

    async def get_alert(self, alert_id: str, *, uow: TrackingUnitOfWork) -> SafetyAlertDTO:
        async with uow:
            return safety_alert_to_dto(await self._get(uow, alert_id))

    async def acknowledge(
        self, alert_id: str, *, actor: Principal, uow: TrackingUnitOfWork
    ) -> SafetyAlertDTO:
        """ADR-0057: acknowledging an SOS also asks the terminal to clear it. Best effort: the
        alert is acknowledged in RAAD whatever the device does."""
        async with uow:
            alert = await self._get(uow, alert_id)
            alert.acknowledge(clock=self._clock, actor_id=actor.user_id)
            if alert.alarm_type == "sos":
                sent = False
                if self._device_commands is not None:
                    try:
                        sent = await self._device_commands.confirm_alarm(
                            terminal_id=alert.terminal_id, alarm_type_mask=_SOS_CONFIRMATION_MASK
                        )
                    except Exception:  # noqa: BLE001 - the acknowledgement stands regardless
                        logger.exception("sos_confirmation_request_failed", extra={"alert_id": alert_id})
                alert.record_device_confirmation(
                    DeviceConfirmation.REQUESTED if sent else DeviceConfirmation.UNAVAILABLE,
                    clock=self._clock,
                )
            uow.record_events(alert.pull_domain_events())
            await uow.commit()
            return safety_alert_to_dto(alert)

    async def resolve(
        self,
        alert_id: str,
        *,
        actor: Principal,
        uow: TrackingUnitOfWork,
        incident_id: str | None = None,
    ) -> SafetyAlertDTO:
        async with uow:
            alert = await self._get(uow, alert_id)
            alert.resolve(clock=self._clock, actor_id=actor.user_id, incident_id=incident_id)
            uow.record_events(alert.pull_domain_events())
            await uow.commit()
            return safety_alert_to_dto(alert)

    async def mark_false_alarm(
        self, alert_id: str, *, actor: Principal, uow: TrackingUnitOfWork
    ) -> SafetyAlertDTO:
        async with uow:
            alert = await self._get(uow, alert_id)
            alert.mark_false_alarm(clock=self._clock, actor_id=actor.user_id)
            uow.record_events(alert.pull_domain_events())
            await uow.commit()
            return safety_alert_to_dto(alert)

    @staticmethod
    async def _get(uow: TrackingUnitOfWork, alert_id: str) -> SafetyAlert:
        alert = await uow.safety_alerts.get(SafetyAlertId(alert_id))
        if alert is None:
            raise NotFoundError(f"Safety alert {alert_id} not found.")
        return alert
