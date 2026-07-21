"""Fleet & Device aggregate roots (Backend LLD §5.2; Database Design §5; Phase 2 §19/§21).
Framework-free — no SQLAlchemy/Pydantic/FastAPI, no I/O. Behavior methods mutate state,
enforce invariants, and buffer the resulting `DomainEvent`s, matching the same shape as
`modules.organization.domain.entities` (`Clock` passed in, never called internally, so
behavior stays deterministic and unit-testable with a fake clock).

Aggregates (per Backend LLD §5.2's contract skeletons and Database Design §5's tables):
- `Vehicle` (§5.1) — the bus as a fleet asset.
- `Device` (§5.2) — the GPS/MDVR terminal, with its `Camera` child entities (§5.3): camera
  channel uniqueness (`ux_cameras__device_channel`) is an intra-aggregate invariant, so
  cameras are owned by the `Device` root rather than being their own aggregate.
- `DeviceAssignment` (§5.4) — the device↔vehicle binding history, exactly the LLD §5.2
  `DeviceAssignment` skeleton. **Driver is deliberately absent** (device ≠ driver,
  Phase 2 §19.1): changing a driver never touches this aggregate, by construction.

Cross-aggregate invariants stay out of these classes, per the LLD's own placement notes:
"one active binding per device & per vehicle" is enforced by an application-layer repository
guard (LLD §5.2's `Trip` note establishes the pattern) plus the two generated-column unique
indexes (Database Design §5.4); per-tenant plate uniqueness and global terminal-id uniqueness
are likewise repository-backed pre-conditions (application layer) over DB-enforced `UX`
constraints.

Connectivity (`Online`/`Offline`, Phase 2 §21.1) is deliberately **not** modeled here: it is
runtime state owned by the JT808 service's session manager (device plane), orthogonal to the
business lifecycle this module owns (Phase 2 §21.2, §19.3). `devices.last_seen_at` is a
durable *mirror* of that runtime state (Database Design §5.2), written by an event consumer
in a later phase — not a domain behavior of `Device`.
"""

from __future__ import annotations

from datetime import datetime

from raad.core.errors.exceptions import ConflictError, DomainError, RuleViolationError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.fleet_device.domain import events as fleet_events
from raad.modules.fleet_device.domain.value_objects import (
    AssignmentId,
    CameraId,
    CameraPosition,
    DeviceId,
    DeviceLifecycleState,
    Msisdn,
    OrganizationId,
    TerminalId,
    VehicleId,
    VehicleStatus,
)


class _AggregateRoot:
    """Shared "raise and buffer domain events" mechanics (LLD §8.1), identical to
    `iam.domain.entities._AggregateRoot` / `organization.domain.entities._AggregateRoot`.
    Duplicated per module deliberately — `.claude/rules/backend.md` #1 forbids one module
    reaching into another's internals, and no approved doc calls for a shared-kernel
    package."""

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _record(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events = self._domain_events
        self._domain_events = []
        return events


class Vehicle(_AggregateRoot):
    """The bus as a fleet asset (Database Design §5.1). No status state machine is documented
    for vehicles (unlike devices, §19.2), so — exactly like `Organization.status` — the three
    enum values are treated as directly settable states with idempotent same-state no-ops,
    not an invented transition graph."""

    def __init__(
        self,
        *,
        id: VehicleId,
        organization_id: OrganizationId,
        plate_no: str,
        label: str | None,
        capacity: int | None,
        status: VehicleStatus,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        if not plate_no:
            raise DomainError("Vehicle plate_no must not be empty")
        self.id = id
        self.organization_id = organization_id
        self.plate_no = plate_no
        self.label = label
        self.capacity = capacity
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Vehicle) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def register(
        cls,
        *,
        id: VehicleId,
        organization_id: OrganizationId,
        plate_no: str,
        label: str | None = None,
        capacity: int | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Vehicle":
        now = clock.now()
        vehicle = cls(
            id=id,
            organization_id=organization_id,
            plate_no=plate_no,
            label=label,
            capacity=capacity,
            status=VehicleStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        vehicle._record(
            fleet_events.vehicle_registered(
                vehicle_id=str(id),
                organization_id=str(organization_id),
                plate_no=plate_no,
                label=label,
                capacity=capacity,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return vehicle

    def activate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == VehicleStatus.ACTIVE:
            return
        self.status = VehicleStatus.ACTIVE
        self.updated_at = clock.now()
        self._record(
            fleet_events.vehicle_activated(
                vehicle_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def deactivate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == VehicleStatus.INACTIVE:
            return
        self.status = VehicleStatus.INACTIVE
        self.updated_at = clock.now()
        self._record(
            fleet_events.vehicle_deactivated(
                vehicle_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def mark_under_maintenance(
        self, *, clock: Clock, actor_id: str | None = None
    ) -> None:
        if self.status == VehicleStatus.MAINTENANCE:
            return
        self.status = VehicleStatus.MAINTENANCE
        self.updated_at = clock.now()
        self._record(
            fleet_events.vehicle_marked_under_maintenance(
                vehicle_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


class Camera:
    """Child entity of the `Device` aggregate (Database Design §5.3) — identity + fields
    only; all mutation goes through `Device.register_camera`, the aggregate root
    (LLD §5.1: "aggregate roots are the only entry points for mutation")."""

    def __init__(
        self,
        *,
        id: CameraId,
        channel_no: int,
        position: CameraPosition,
        label: str | None,
    ) -> None:
        self.id = id
        self.channel_no = channel_no
        self.position = position
        self.label = label

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Camera) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


class Device(_AggregateRoot):
    """The GPS/MDVR terminal (Database Design §5.2), owning its `Camera` children (§5.3).

    Lifecycle edges enforced here are exactly Phase 2 §19.2's state machine, expressed over
    the Database Design's 5-value enum (see `DeviceLifecycleState`'s docstring for the
    documented reconciliation of the diagram's `Unassigned`/`Reassigned`):

        registered ──activate()──► activated ◄──suspend()/reactivate()──► suspended
        activated ──mark_assigned()──► assigned ──mark_unassigned()──► activated
        assigned | activated ──retire()──► retired (terminal)

    §19.2 draws `Suspended` reachable only from `Activated` (not from `Assigned`) and
    `Retired` reachable only from `Assigned`/`Unassigned` (not from `Registered` or
    `Suspended`) — those edges are enforced as documented rather than loosened. Illegal
    transitions raise `RuleViolationError` ("illegal status transition", `core.errors`);
    same-state calls are idempotent no-ops, matching `Organization`'s established precedent.

    `mark_assigned`/`mark_unassigned` mutate lifecycle state only and emit **no** event:
    the business fact ("this device is now bound to that vehicle") is emitted exactly once,
    by the `DeviceAssignment` aggregate whose open/close *is* that fact — two events for one
    fact would force every consumer to dedupe.

    `auth_key_hash` is stored, never verified here — device authentication happens in the
    JT808 service against the device-registry projection (Phase 2 §12.7, Phase 3.4 §4).
    """

    def __init__(
        self,
        *,
        id: DeviceId,
        organization_id: OrganizationId,
        terminal_id: TerminalId,
        model: str | None,
        vendor: str | None,
        sim_msisdn: Msisdn | None,
        lifecycle_state: DeviceLifecycleState,
        auth_key_hash: str | None,
        last_seen_at: datetime | None,
        created_at: datetime,
        updated_at: datetime,
        cameras: list[Camera] | None = None,
    ) -> None:
        super().__init__()
        self.id = id
        self.organization_id = organization_id
        self.terminal_id = terminal_id
        self.model = model
        self.vendor = vendor
        self.sim_msisdn = sim_msisdn
        self.lifecycle_state = lifecycle_state
        self.auth_key_hash = auth_key_hash
        self.last_seen_at = last_seen_at
        self.created_at = created_at
        self.updated_at = updated_at
        self._cameras: list[Camera] = list(cameras) if cameras else []

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Device) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def cameras(self) -> tuple[Camera, ...]:
        """Read-only view — mutation only via `register_camera` (aggregate-root rule)."""
        return tuple(self._cameras)

    @classmethod
    def register(
        cls,
        *,
        id: DeviceId,
        organization_id: OrganizationId,
        terminal_id: TerminalId,
        model: str | None = None,
        vendor: str | None = None,
        sim_msisdn: Msisdn | None = None,
        auth_key_hash: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Device":
        """Onboarding factory (Phase 2 §19.2: "[*] --> Registered: device onboarded")."""
        now = clock.now()
        device = cls(
            id=id,
            organization_id=organization_id,
            terminal_id=terminal_id,
            model=model,
            vendor=vendor,
            sim_msisdn=sim_msisdn,
            lifecycle_state=DeviceLifecycleState.REGISTERED,
            auth_key_hash=auth_key_hash,
            last_seen_at=None,
            created_at=now,
            updated_at=now,
        )
        device._record(
            fleet_events.device_registered(
                device_id=str(id),
                organization_id=str(organization_id),
                terminal_id=str(terminal_id),
                model=model,
                vendor=vendor,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return device

    def activate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Registered → Activated (Phase 2 §19.2). Reactivation from Suspended is
        `reactivate()` — kept separate because the two edges are distinct in the documented
        machine and emit distinct facts."""
        if self.lifecycle_state == DeviceLifecycleState.ACTIVATED:
            return
        if self.lifecycle_state != DeviceLifecycleState.REGISTERED:
            self._raise_illegal_transition("activate")
        self.lifecycle_state = DeviceLifecycleState.ACTIVATED
        self.updated_at = clock.now()
        self._record(
            fleet_events.device_activated(
                device_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def suspend(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Activated → Suspended (Phase 2 §19.2 — the diagram's only edge into Suspended;
        an `assigned` device must be unassigned first)."""
        if self.lifecycle_state == DeviceLifecycleState.SUSPENDED:
            return
        if self.lifecycle_state != DeviceLifecycleState.ACTIVATED:
            self._raise_illegal_transition("suspend")
        self.lifecycle_state = DeviceLifecycleState.SUSPENDED
        self.updated_at = clock.now()
        self._record(
            fleet_events.device_suspended(
                device_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def reactivate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Suspended → Activated (Phase 2 §19.2)."""
        if self.lifecycle_state == DeviceLifecycleState.ACTIVATED:
            return
        if self.lifecycle_state != DeviceLifecycleState.SUSPENDED:
            self._raise_illegal_transition("reactivate")
        self.lifecycle_state = DeviceLifecycleState.ACTIVATED
        self.updated_at = clock.now()
        self._record(
            fleet_events.device_reactivated(
                device_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def retire(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Assigned/Activated → Retired (Phase 2 §19.2: `Assigned --> Retired`,
        `Unassigned --> Retired`; terminal). The application-layer retire use-case closes any
        active assignment in the same transaction (an `assigned` device retired here leaves
        the assignment row to that orchestration — this aggregate cannot see it)."""
        if self.lifecycle_state == DeviceLifecycleState.RETIRED:
            return
        if self.lifecycle_state not in (
            DeviceLifecycleState.ASSIGNED,
            DeviceLifecycleState.ACTIVATED,
        ):
            self._raise_illegal_transition("retire")
        self.lifecycle_state = DeviceLifecycleState.RETIRED
        self.updated_at = clock.now()
        self._record(
            fleet_events.device_retired(
                device_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def mark_assigned(self, *, clock: Clock) -> None:
        """Activated → Assigned. State-sync only, invoked by the application layer's
        assign/reassign use-case alongside `DeviceAssignment.open(...)` — the event for this
        fact is the assignment's (see class docstring)."""
        if self.lifecycle_state != DeviceLifecycleState.ACTIVATED:
            self._raise_illegal_transition("mark_assigned")
        self.lifecycle_state = DeviceLifecycleState.ASSIGNED
        self.updated_at = clock.now()

    def mark_unassigned(self, *, clock: Clock) -> None:
        """Assigned → Activated (the §19.2 diagram's `Unassigned`, per the documented enum
        reconciliation). State-sync only — the event is the assignment close's."""
        if self.lifecycle_state != DeviceLifecycleState.ASSIGNED:
            self._raise_illegal_transition("mark_unassigned")
        self.lifecycle_state = DeviceLifecycleState.ACTIVATED
        self.updated_at = clock.now()

    def register_camera(
        self,
        *,
        id: CameraId,
        channel_no: int,
        position: CameraPosition,
        label: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> Camera:
        """Adds a camera on a free channel (Database Design §5.3:
        `ux_cameras__device_channel (device_id, channel_no)` — an intra-aggregate uniqueness
        invariant, enforced here without I/O)."""
        if any(camera.channel_no == channel_no for camera in self._cameras):
            raise ConflictError(
                f"Device {self.id} already has a camera on channel {channel_no}."
            )
        camera = Camera(id=id, channel_no=channel_no, position=position, label=label)
        self._cameras.append(camera)
        self._record(
            fleet_events.camera_registered(
                camera_id=str(id),
                device_id=str(self.id),
                organization_id=str(self.organization_id),
                channel_no=channel_no,
                position=position.value,
                label=label,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return camera

    def _raise_illegal_transition(self, operation: str) -> None:
        raise RuleViolationError(
            f"Illegal device lifecycle transition: cannot {operation} a device in state "
            f"{self.lifecycle_state.value!r} (Phase 2 §19.2)."
        )


class DeviceAssignment(_AggregateRoot):
    """The device↔vehicle binding, exactly the Backend LLD §5.2 skeleton:
    `{assignment_id, device_id, vehicle_id, assigned_at, unassigned_at?}` plus the Database
    Design §5.4 columns (`organization_id`, `assigned_by`). Active while
    `unassigned_at IS NULL`; history rows are retained for audit and reporting
    (Phase 2 §19.2).

    The "one active binding per device & per vehicle" invariant spans *other* assignment
    rows this aggregate cannot see — enforced by the application-layer repository guard
    (`active_for_device`/`active_for_vehicle`, LLD §7.2) plus the two generated-column
    unique indexes (Database Design §5.4), the same dual enforcement the LLD prescribes for
    the one-active-trip invariant."""

    def __init__(
        self,
        *,
        id: AssignmentId,
        organization_id: OrganizationId,
        device_id: DeviceId,
        vehicle_id: VehicleId,
        assigned_by: str | None,
        assigned_at: datetime,
        unassigned_at: datetime | None,
    ) -> None:
        super().__init__()
        self.id = id
        self.organization_id = organization_id
        self.device_id = device_id
        self.vehicle_id = vehicle_id
        self.assigned_by = assigned_by
        self.assigned_at = assigned_at
        self.unassigned_at = unassigned_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, DeviceAssignment) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def is_active(self) -> bool:
        """`unassigned_at IS NULL` = active (Database Design §5.4)."""
        return self.unassigned_at is None

    @classmethod
    def open(
        cls,
        *,
        id: AssignmentId,
        organization_id: OrganizationId,
        device_id: DeviceId,
        vehicle_id: VehicleId,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "DeviceAssignment":
        assignment = cls(
            id=id,
            organization_id=organization_id,
            device_id=device_id,
            vehicle_id=vehicle_id,
            assigned_by=actor_id,
            assigned_at=clock.now(),
            unassigned_at=None,
        )
        assignment._record(
            fleet_events.device_assigned_to_vehicle(
                assignment_id=str(id),
                device_id=str(device_id),
                vehicle_id=str(vehicle_id),
                organization_id=str(organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return assignment

    def close(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Ends the binding (`unassigned_at` set). Closing an already-closed assignment is a
        no-op — reassignment retries must be safe."""
        if self.unassigned_at is not None:
            return
        self.unassigned_at = clock.now()
        self._record(
            fleet_events.device_unassigned_from_vehicle(
                assignment_id=str(self.id),
                device_id=str(self.device_id),
                vehicle_id=str(self.vehicle_id),
                organization_id=str(self.organization_id),
                occurred_at=self.unassigned_at,
                actor_id=actor_id,
            )
        )
