"""Fleet & Device infrastructure layer (Backend LLD §6.2/§7/§8; Database Design §5) —
Phase 7.3 scope. SQLAlchemy ORM models, ORM↔domain mappers, and the concrete
repositories/UnitOfWork that implement the domain's and application's interfaces. Importing
this package registers `VehicleModel`/`DeviceModel`/`CameraModel`/`DeviceAssignmentModel`
onto `core.db.base.Base.metadata` — not yet wired into `migrations/env.py` (deliberately
deferred to the dedicated migrations phase, mirroring IAM's 5.3 → 5.5 and organization's
6.3 → 6.5 splits). No HTTP/FastAPI, no new business rules — `domain/` and `application/` are
unchanged. Public surface of this package.

Note: the concrete UoW is named `SqlAlchemyFleetDeviceUnitOfWork` (not
`SqlAlchemyFleetUnitOfWork`) to match the module's exact bounded-context name, consistent
with `SqlAlchemyIamUnitOfWork`/`SqlAlchemyOrganizationUnitOfWork` (`.claude/rules/naming.md`:
modules match bounded-context names exactly).
"""

from raad.modules.fleet_device.infra.mappers import (
    assignment_to_model,
    camera_to_model,
    device_to_model,
    model_to_assignment,
    model_to_camera,
    model_to_device,
    model_to_vehicle,
    vehicle_to_model,
)
from raad.modules.fleet_device.infra.models import (
    CameraModel,
    DeviceAssignmentModel,
    DeviceModel,
    VehicleModel,
)
from raad.modules.fleet_device.infra.repositories import (
    SqlAlchemyDeviceAssignmentRepository,
    SqlAlchemyDeviceRepository,
    SqlAlchemyFleetDeviceUnitOfWork,
    SqlAlchemyVehicleRepository,
)

__all__ = [
    "CameraModel",
    "DeviceAssignmentModel",
    "DeviceModel",
    "SqlAlchemyDeviceAssignmentRepository",
    "SqlAlchemyDeviceRepository",
    "SqlAlchemyFleetDeviceUnitOfWork",
    "SqlAlchemyVehicleRepository",
    "VehicleModel",
    "assignment_to_model",
    "camera_to_model",
    "device_to_model",
    "model_to_assignment",
    "model_to_camera",
    "model_to_device",
    "model_to_vehicle",
    "vehicle_to_model",
]
