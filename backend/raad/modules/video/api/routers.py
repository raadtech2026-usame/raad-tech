"""HTTP surface of the `video` module (C6). Mounted at `/api/v1/video` (Backend LLD §16.1).
Thin controllers only (Backend LLD §16.2): parse the request, call exactly one application-
service method, return the response DTO. Mirrors `billing.api.routers`'s shape.

**Architecture Resolution (Backend Stabilization phase, High finding: D5/`VideoAccessPolicy`
never invoked anywhere).** Every route below resolves `device_organization_id` first (via
`fleet_device`'s own `DeviceApplicationService` — never a cross-module DB read,
`.claude/rules/backend.md` #3) and then calls `interfaces.http.policy_guards.enforce_d5` —
`.claude/rules/jt1078.md` #1: "Authorization is enforced in the Business API before any
signaling reaches this service" — **before** any `VideoApplicationService` call, so the Parent
role (and every other ineligible role/scope) never reaches a `VideoProviderPort` call or a
persisted `VideoSession` row at all, matching `.claude/rules/security.md` #5's "Video is
Org-Admin-only, by construction, not by a runtime flag."

Three routes, exactly API Contracts §4.5's documented table:
- `POST /video/live` — Org Admin (+ permitted RAAD staff).
- `POST /video/playback` — Org Admin.
- `POST /video/sessions/{id}/stop` — Org Admin, teardown.

**Camera-ownership cross-check, a defense-in-depth addition beyond the literal documented
behavior — flagged, not silently assumed.** `DeviceApplicationService.get_device_by_id` already
returns the device's own embedded `cameras` tuple (`fleet_device.application.queries.DeviceDTO`)
at no extra cross-module read; `request_live_video`/`request_playback_video` verify
`camera_id` actually belongs to the resolved `device_id` before ever calling the application
service, the same "no invented cross-module DB access, only already-loaded-DTO checks" posture
`interfaces/http/policy_guards.find_owned_student_id_for_vehicle` already establishes.

**With no `VideoProviderPort` bound this phase** (`core/di/bootstrap.py` — this phase's own
explicit instruction: "Native JT1078 implementation is intentionally postponed"), calling
`POST /video/live` or `POST /video/playback` **persists the `VideoSession` as `REQUESTED` and
then raises `NotImplementedError`** (500) at the activation step — see
`VideoApplicationService`'s own module docstring; this is the documented, intentional "fail
loudly, don't fake a stream" behavior, not a bug. `POST /video/sessions/{id}/stop` still
succeeds locally (ends the control record) even with no provider bound.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from raad.core.di.container import Container
from raad.core.errors.exceptions import NotFoundError
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import get_container, require_permission
from raad.interfaces.http.policy_guards import enforce_d5
from raad.modules.fleet_device.api.deps import get_device_service, get_fleet_device_uow
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.queries import DeviceDTO, GetDeviceByIdQuery
from raad.modules.fleet_device.application.services import DeviceApplicationService
from raad.modules.video.api.deps import get_video_service, get_video_uow
from raad.modules.video.api.schemas import (
    RequestLiveVideoRequest,
    RequestPlaybackVideoRequest,
    VideoSessionResponse,
)
from raad.modules.video.application.commands import (
    RequestLiveVideoCommand,
    RequestPlaybackVideoCommand,
    StopVideoSessionCommand,
)
from raad.modules.video.application.ports import VideoUnitOfWork
from raad.modules.video.application.queries import GetVideoSessionByIdQuery, VideoSessionDTO
from raad.modules.video.application.services import VideoApplicationService

video_router = APIRouter()


def _session_dto_to_response(session: VideoSessionDTO) -> VideoSessionResponse:
    return VideoSessionResponse(
        id=session.id,
        organization_id=session.organization_id,
        device_id=session.device_id,
        camera_id=session.camera_id,
        purpose=session.purpose,
        requested_by=session.requested_by,
        window_start=session.window_start,
        window_end=session.window_end,
        status=session.status,
        started_at=session.started_at,
        ended_at=session.ended_at,
        created_at=session.created_at,
        stream_url=session.stream_url,
    )


async def _resolve_device_or_raise(
    device_id: str,
    *,
    device_service: DeviceApplicationService,
    device_uow: FleetDeviceUnitOfWork,
) -> DeviceDTO:
    return await device_service.get_device_by_id(
        GetDeviceByIdQuery(device_id=device_id), uow=device_uow
    )


def _ensure_camera_belongs_to_device(device: DeviceDTO, camera_id: str) -> None:
    if not any(camera.id == camera_id for camera in device.cameras):
        raise NotFoundError(f"Camera {camera_id} not found on device {device.id}.")


@video_router.post(
    "/live",
    response_model=VideoSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a live video stream",
    description=(
        "Org Admin (+ permitted RAAD) (API Contracts §4.5 line 152). D5-enforced "
        "(`VideoAccessPolicy`) before any session is created. With no `VideoProviderPort` "
        "bound this phase, persists the `VideoSession` as `REQUESTED` and then raises "
        "`NotImplementedError` (500) — see this file's module docstring."
    ),
)
async def request_live_video(
    request: Request,
    body: RequestLiveVideoRequest,
    principal: Principal = Depends(require_permission(Permission("video.live.start"))),
    video_service: VideoApplicationService = Depends(get_video_service),
    uow: VideoUnitOfWork = Depends(get_video_uow),
    device_service: DeviceApplicationService = Depends(get_device_service),
    device_uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> VideoSessionResponse:
    device = await _resolve_device_or_raise(
        body.device_id, device_service=device_service, device_uow=device_uow
    )
    _ensure_camera_belongs_to_device(device, body.camera_id)

    container: Container = get_container(request)
    await enforce_d5(
        principal=principal,
        device_organization_id=device.organization_id,
        container=container,
    )

    command = RequestLiveVideoCommand(
        organization_id=device.organization_id,
        device_id=body.device_id,
        camera_id=body.camera_id,
        actor=principal,
    )
    session = await video_service.request_live_video(command, uow=uow)
    return _session_dto_to_response(session)


@video_router.post(
    "/playback",
    response_model=VideoSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a playback video stream",
    description=(
        "Org Admin (API Contracts §4.5 line 153). D5-enforced before any session is created. "
        "Same `VideoProviderPort`-unbound posture as `POST /video/live`."
    ),
)
async def request_playback_video(
    request: Request,
    body: RequestPlaybackVideoRequest,
    principal: Principal = Depends(require_permission(Permission("video.playback.start"))),
    video_service: VideoApplicationService = Depends(get_video_service),
    uow: VideoUnitOfWork = Depends(get_video_uow),
    device_service: DeviceApplicationService = Depends(get_device_service),
    device_uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> VideoSessionResponse:
    device = await _resolve_device_or_raise(
        body.device_id, device_service=device_service, device_uow=device_uow
    )
    _ensure_camera_belongs_to_device(device, body.camera_id)

    container: Container = get_container(request)
    await enforce_d5(
        principal=principal,
        device_organization_id=device.organization_id,
        container=container,
    )

    command = RequestPlaybackVideoCommand(
        organization_id=device.organization_id,
        device_id=body.device_id,
        camera_id=body.camera_id,
        window_start=body.window_start,
        window_end=body.window_end,
        actor=principal,
    )
    session = await video_service.request_playback_video(command, uow=uow)
    return _session_dto_to_response(session)


@video_router.post(
    "/sessions/{session_id}/stop",
    response_model=VideoSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop a video session",
    description="Org Admin, teardown (API Contracts §4.5 line 154). D5-enforced.",
)
async def stop_video_session(
    request: Request,
    session_id: str,
    principal: Principal = Depends(require_permission(Permission("video.sessions.stop"))),
    video_service: VideoApplicationService = Depends(get_video_service),
    uow: VideoUnitOfWork = Depends(get_video_uow),
) -> VideoSessionResponse:
    existing = await video_service.get_video_session_by_id(
        GetVideoSessionByIdQuery(video_session_id=session_id), uow=uow
    )

    container: Container = get_container(request)
    await enforce_d5(
        principal=principal,
        device_organization_id=existing.organization_id,
        container=container,
    )

    command = StopVideoSessionCommand(video_session_id=session_id, actor=principal)
    session = await video_service.stop_video_session(command, uow=uow)
    return _session_dto_to_response(session)
