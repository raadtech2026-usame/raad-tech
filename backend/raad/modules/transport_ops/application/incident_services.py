"""The incident log (ADR-0056): record, edit, move through its statuses, keep a timeline, and —
only when the Org Admin chooses — send a notice to the parents of the students involved.

Every link is checked to be in the incident's organization here: the trip, route, staff and
students through this module's own repositories, the bus through `VehicleDirectoryPort`. A
link to something elsewhere answers 404, as if it did not exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from raad.core.errors.exceptions import DomainError, NotFoundError, ValidationError
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork, VehicleDirectoryPort
from raad.modules.transport_ops.application.services import _enforce_own_organization
from raad.modules.transport_ops.domain.entities import Incident, IncidentNote
from raad.modules.transport_ops.domain.value_objects import (
    IncidentCategory,
    IncidentId,
    IncidentNoteId,
    IncidentNoteKind,
    IncidentSeverity,
    IncidentStatus,
    OrganizationId,
    RouteId,
    StudentId,
    TripId,
    VehicleId,
)

#: ADR-0056 §3: defaults for an incident created from a safety alert.
_ALERT_CATEGORY = {"collision": IncidentCategory.ACCIDENT, "rollover": IncidentCategory.ACCIDENT}
_ALERT_TITLE = {
    "sos": "SOS pressed on the bus",
    "collision": "Collision reported by the bus",
    "rollover": "Rollover reported by the bus",
    "overspeed": "Overspeed reported by the bus",
    "fatigue": "Driver fatigue reported by the bus",
    "power_cut": "Power cut on the bus",
    "camera_fault": "Camera fault on the bus",
    "illegal_door_open": "Door opened while moving",
}
_CRITICAL_ALERT_TYPES = frozenset({"sos", "collision", "rollover"})


# ---- commands and DTOs --------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordIncidentCommand:
    organization_id: str
    category: str
    severity: str
    occurred_at: datetime
    title: str
    actor: Principal
    description: str | None = None
    actions_taken: str | None = None
    vehicle_id: str | None = None
    trip_id: str | None = None
    route_id: str | None = None
    staff_ids: tuple[str, ...] = ()
    student_ids: tuple[str, ...] = ()
    source_alert_id: str | None = None


@dataclass(frozen=True)
class IncidentNoteDTO:
    id: str
    kind: str
    body: str
    author_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class IncidentDTO:
    """`title`, `description`, `actions_taken`, `resolution`, the people and the notes are
    Org Admin only; the API nulls them for other readers (ADR-0056 §5)."""

    id: str
    organization_id: str
    category: str
    severity: str
    status: str
    occurred_at: datetime
    vehicle_id: str | None
    trip_id: str | None
    route_id: str | None
    title: str
    description: str | None
    actions_taken: str | None
    resolution: str | None
    recorded_in_error: bool
    staff_ids: list[str]
    staff_names: list[str]
    student_ids: list[str]
    student_names: list[str]
    source_alert_id: str | None
    closed_at: datetime | None
    created_at: datetime
    notes: list[IncidentNoteDTO] = field(default_factory=list)


@dataclass(frozen=True)
class ParentNotice:
    organization_id: str
    incident_id: str
    message: str
    parent_user_ids: list[str]


def _enum(cls, value: str, what: str):
    try:
        return cls(value)
    except ValueError as exc:
        raise ValidationError(f"Unknown {what} {value!r}.") from exc


class IncidentApplicationService:
    def __init__(
        self, *, clock: Clock, id_generator: IdGenerator, vehicle_directory: VehicleDirectoryPort
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._vehicle_directory = vehicle_directory

    # ---- record and edit --------------------------------------------------------------------

    async def record(self, command: RecordIncidentCommand, *, uow: TransportOpsUnitOfWork) -> IncidentDTO:
        _enforce_own_organization(actor=command.actor, organization_id=command.organization_id)
        async with uow:
            values = await self._validated_values(
                uow,
                command.organization_id,
                dict(
                    category=_enum(IncidentCategory, command.category, "category"),
                    severity=_enum(IncidentSeverity, command.severity, "severity"),
                    occurred_at=command.occurred_at,
                    vehicle_id=command.vehicle_id,
                    trip_id=command.trip_id,
                    route_id=command.route_id,
                    title=command.title,
                    description=command.description,
                    actions_taken=command.actions_taken,
                    staff_ids=command.staff_ids,
                    student_ids=command.student_ids,
                ),
                fill_from_trip=True,
            )
            incident = Incident.record(
                id=IncidentId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                clock=self._clock,
                actor_id=command.actor.user_id,
                source_alert_id=command.source_alert_id,
                **values,
            )
            uow.incidents.add(incident)
            uow.record_events(incident.pull_domain_events())
            await uow.commit()
            return await self._dto(uow, incident, notes=[])

    async def record_from_alert(
        self, alert, *, actor: Principal, uow: TransportOpsUnitOfWork
    ) -> IncidentDTO:
        """ADR-0056 §3. `alert` is `tracking`'s `SafetyAlertDTO`, handed over by the route."""
        return await self.record(
            RecordIncidentCommand(
                organization_id=alert.organization_id,
                category=_ALERT_CATEGORY.get(alert.alarm_type, IncidentCategory.OTHER).value,
                severity=(IncidentSeverity.CRITICAL if alert.alarm_type in _CRITICAL_ALERT_TYPES else IncidentSeverity.MEDIUM).value,
                occurred_at=alert.raised_at,
                title=_ALERT_TITLE.get(alert.alarm_type, "Alarm reported by the bus"),
                vehicle_id=alert.vehicle_id,
                trip_id=alert.trip_id,
                source_alert_id=alert.id,
                actor=actor,
            ),
            uow=uow,
        )

    async def update(
        self, incident_id: str, changes: dict, *, actor: Principal, uow: TransportOpsUnitOfWork
    ) -> IncidentDTO:
        async with uow:
            incident = await self._get(uow, incident_id)
            converted = dict(changes)
            if "category" in converted:
                converted["category"] = _enum(IncidentCategory, converted["category"], "category")
            if "severity" in converted:
                converted["severity"] = _enum(IncidentSeverity, converted["severity"], "severity")
            values = await self._validated_values(uow, str(incident.organization_id), converted, fill_from_trip=False)
            incident.update(clock=self._clock, actor_id=actor.user_id, **values)
            uow.record_events(incident.pull_domain_events())
            await uow.commit()
            return await self._dto(uow, incident)

    async def change_status(
        self,
        incident_id: str,
        status: str,
        *,
        resolution: str | None,
        recorded_in_error: bool,
        actor: Principal,
        uow: TransportOpsUnitOfWork,
    ) -> IncidentDTO:
        new_status = _enum(IncidentStatus, status, "status")
        async with uow:
            incident = await self._get(uow, incident_id)
            previous = incident.status
            incident.change_status(
                new_status,
                resolution=resolution,
                recorded_in_error=recorded_in_error,
                clock=self._clock,
                actor_id=actor.user_id,
            )
            uow.record_events(incident.pull_domain_events())
            if incident.status is not previous:
                text = f"Status: {previous.value} → {incident.status.value}"
                if recorded_in_error:
                    text += " (recorded in error)"
                if resolution:
                    text += f". {resolution.strip()}"
                note = IncidentNote.add(
                    id=IncidentNoteId(self._id_generator.new_id()),
                    incident=incident,
                    kind=IncidentNoteKind.STATUS_CHANGE,
                    body=text,
                    clock=self._clock,
                    actor_id=actor.user_id,
                )
                uow.incident_notes.add(note)
                uow.record_events(note.pull_domain_events())
            await uow.commit()
            return await self._dto(uow, incident)

    async def add_note(
        self, incident_id: str, body: str, *, actor: Principal, uow: TransportOpsUnitOfWork
    ) -> IncidentDTO:
        async with uow:
            incident = await self._get(uow, incident_id)
            note = IncidentNote.add(
                id=IncidentNoteId(self._id_generator.new_id()),
                incident=incident,
                kind=IncidentNoteKind.NOTE,
                body=body,
                clock=self._clock,
                actor_id=actor.user_id,
            )
            uow.incident_notes.add(note)
            uow.record_events(note.pull_domain_events())
            await uow.commit()
            return await self._dto(uow, incident)

    async def notify_parents(
        self, incident_id: str, message: str, *, actor: Principal, uow: TransportOpsUnitOfWork
    ) -> IncidentDTO:
        """ADR-0056 §4: recorded on the timeline; the Notification Worker delivers it."""
        async with uow:
            incident = await self._get(uow, incident_id)
            if not incident.student_ids:
                raise DomainError("Link the students involved before notifying their parents.")
            note = IncidentNote.add(
                id=IncidentNoteId(self._id_generator.new_id()),
                incident=incident,
                kind=IncidentNoteKind.PARENT_NOTICE,
                body=message,
                clock=self._clock,
                actor_id=actor.user_id,
            )
            uow.incident_notes.add(note)
            uow.record_events(note.pull_domain_events())
            await uow.commit()
            return await self._dto(uow, incident)

    # ---- reads --------------------------------------------------------------------------------

    async def get(self, incident_id: str, *, uow: TransportOpsUnitOfWork) -> IncidentDTO:
        async with uow:
            return await self._dto(uow, await self._get(uow, incident_id))

    async def list_incidents(
        self,
        *,
        uow: TransportOpsUnitOfWork,
        statuses: list[str] | None = None,
        category: str | None = None,
        vehicle_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[IncidentDTO]:
        for s in statuses or []:
            _enum(IncidentStatus, s, "status")
        async with uow:
            incidents = await uow.incidents.list_filtered(
                statuses=statuses or None,
                category=category,
                vehicle_id=VehicleId(vehicle_id) if vehicle_id else None,
                start=start,
                end=end,
            )
            return [await self._dto(uow, i, notes=[]) for i in incidents]

    async def parent_notice(self, note_id: str, *, uow: TransportOpsUnitOfWork) -> ParentNotice | None:
        """For the Notification Worker: the message and the logins of the linked students'
        parents. `None` when the note is gone or is not a parent notice."""
        async with uow:
            note = await uow.incident_notes.get(IncidentNoteId(note_id))
            if note is None or note.kind is not IncidentNoteKind.PARENT_NOTICE:
                return None
            incident = await uow.incidents.get(note.incident_id)
            if incident is None:
                return None
            links = await uow.student_parents.list_by_students([StudentId(s) for s in incident.student_ids])
            parents = await uow.parents.list_by_ids([str(link.parent_id) for link in links])
            return ParentNotice(
                organization_id=str(incident.organization_id),
                incident_id=str(incident.id),
                message=note.body,
                parent_user_ids=sorted({str(p.user_id) for p in parents if p.user_id}),
            )

    # ---- helpers ------------------------------------------------------------------------------

    async def _validated_values(
        self, uow: TransportOpsUnitOfWork, organization_id: str, values: dict, *, fill_from_trip: bool
    ) -> dict:
        out = dict(values)
        trip = None
        if values.get("trip_id"):
            trip = await uow.trips.get(TripId(values["trip_id"]))
            if trip is None or str(trip.organization_id) != organization_id:
                raise NotFoundError(f"Trip {values['trip_id']} not found.")
            out["trip_id"] = trip.id
        elif "trip_id" in values:
            out["trip_id"] = None
        if fill_from_trip and trip is not None:
            out["vehicle_id"] = out.get("vehicle_id") or str(trip.vehicle_id)
            out["route_id"] = out.get("route_id") or str(trip.route_id)
            if not out.get("staff_ids"):
                driver = await uow.drivers.get(trip.driver_id)
                out["staff_ids"] = (str(driver.staff_id),) if driver is not None else ()
        if "vehicle_id" in out:
            if out["vehicle_id"]:
                if await self._vehicle_directory.organization_of_vehicle(str(out["vehicle_id"])) != organization_id:
                    raise NotFoundError(f"Vehicle {out['vehicle_id']} not found.")
                out["vehicle_id"] = VehicleId(str(out["vehicle_id"]))
            else:
                out["vehicle_id"] = None
        if "route_id" in out:
            if out["route_id"]:
                route = await uow.routes.get(RouteId(str(out["route_id"])))
                if route is None or str(route.organization_id) != organization_id:
                    raise NotFoundError(f"Route {out['route_id']} not found.")
                out["route_id"] = route.id
            else:
                out["route_id"] = None
        if "staff_ids" in out:
            ids = [str(i) for i in out["staff_ids"] or ()]
            found = {str(s.id) for s in await uow.staff.list_by_ids(ids) if str(s.organization_id) == organization_id}
            missing = [i for i in ids if i not in found]
            if missing:
                raise NotFoundError(f"Staff member {missing[0]} not found.")
            out["staff_ids"] = tuple(ids)
        if "student_ids" in out:
            ids = [str(i) for i in out["student_ids"] or ()]
            for student_id in ids:
                student = await uow.students.get(StudentId(student_id))
                if student is None or str(student.organization_id) != organization_id:
                    raise NotFoundError(f"Student {student_id} not found.")
            out["student_ids"] = tuple(ids)
        return out

    @staticmethod
    async def _get(uow: TransportOpsUnitOfWork, incident_id: str) -> Incident:
        incident = await uow.incidents.get(IncidentId(incident_id))
        if incident is None:
            raise NotFoundError(f"Incident {incident_id} not found.")
        return incident

    async def _dto(self, uow: TransportOpsUnitOfWork, incident: Incident, notes=None) -> IncidentDTO:
        if notes is None:
            notes = await uow.incident_notes.list_for_incident(incident.id)
        staff = {str(s.id): s.full_name for s in await uow.staff.list_by_ids(list(incident.staff_ids))}
        students = {}
        for student_id in incident.student_ids:
            student = await uow.students.get(StudentId(student_id))
            if student is not None:
                students[student_id] = student.full_name
        return IncidentDTO(
            id=str(incident.id),
            organization_id=str(incident.organization_id),
            category=incident.category.value,
            severity=incident.severity.value,
            status=incident.status.value,
            occurred_at=incident.occurred_at,
            vehicle_id=str(incident.vehicle_id) if incident.vehicle_id else None,
            trip_id=str(incident.trip_id) if incident.trip_id else None,
            route_id=str(incident.route_id) if incident.route_id else None,
            title=incident.title,
            description=incident.description,
            actions_taken=incident.actions_taken,
            resolution=incident.resolution,
            recorded_in_error=incident.recorded_in_error,
            staff_ids=list(incident.staff_ids),
            staff_names=[staff.get(i, i) for i in incident.staff_ids],
            student_ids=list(incident.student_ids),
            student_names=[students.get(i, i) for i in incident.student_ids],
            source_alert_id=incident.source_alert_id,
            closed_at=incident.closed_at,
            created_at=incident.created_at,
            notes=[
                IncidentNoteDTO(id=str(n.id), kind=n.kind.value, body=n.body, author_id=n.author_id, created_at=n.created_at)
                for n in notes
            ],
        )


__all__ = ["IncidentApplicationService", "RecordIncidentCommand", "IncidentDTO", "ParentNotice"]
