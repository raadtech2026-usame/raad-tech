"""HTTP surface of the `notifications` module (C7). Mounted at `/api/v1/notifications`; the
realtime `/ws/notifications` WebSocket endpoint lives in `api/ws.py` (Backend LLD §16.1, §1) —
still a docstring-only scaffold this phase, see that file for why. Thin controllers only
(Backend LLD §16.2): parse the request DTO, call exactly one `NotificationApplicationService`
method, return the response DTO — every error already maps to the standard `ErrorEnvelope` via
the global exception handlers. Mirrors `billing.api.routers`'s shape.

**Five routes, matching API Contracts §4.6's table exactly (lines 161-164) plus one uniform-CRUD
addition — no more, no less:**

- `GET /notifications` — list (line 161, "any authenticated", "own in-app notifications
  (paginated)"). Scoped to the caller's own `recipient_user_id` (`principal.user_id`), **not**
  `organization_id`/`TenantRegionScope` — the first list endpoint in this codebase scoped by
  personal ownership rather than tenant. **Cursor-paginated** (`?limit&cursor`, API Contracts
  §7) as of the Pagination/Filtering/Sorting phase — the first of the two documented "(paginated)"
  routes (alongside `GET /tracking/trips/{id}/positions`) to actually get it, closing what this
  docstring used to describe as the same pre-existing gap `list_students`/`list_parents`/etc.
  still carry. Supports `filter[type]=...`/`filter[trip_id]=...` (§8) — whitelisted, narrowing-only
  on top of the caller's own mandatory `recipient_user_id` scope (`domain/repositories.py`'s
  `list_for_recipient_page` docstring). `status` is deliberately NOT filterable — it is a
  domain-derived property (`read_at`-based), not a persisted column, see `infra/repositories.py`'s
  `SqlAlchemyNotificationRepository.filterable_fields` docstring. No `sort` parameter — cursor
  mode paginates over a single fixed `(created_at, id)` keyset, newest-first, not a client-chosen
  sort (`core/pagination`'s own module docstring).
- `GET /notifications/{notification_id}` — get by id. Not itemized in §4.6's compact table, but
  every sibling resource in this codebase gets this uniform-CRUD route — built for the same
  reason `Trip`'s/`StudentAssignment`'s equivalent were, flagged here rather than silently
  assumed. Ownership-scoped identically to the list route (`NotFoundError` on a non-owner
  request — see `application/queries.py`'s `GetNotificationByIdQuery` docstring for why 404,
  not 403).
- `POST /notifications/{notification_id}/read` — line 162, "recipient", mark read. Ownership
  enforced directly (not RBAC-deferred) — see `application/services.py`'s module docstring.
- `POST /notifications/tokens` — line 163, "Parent/Driver", register FCM token. No documented
  request/response body shape (§4.6 gives only the route row); `RegisterDeviceTokenRequest`
  mirrors the `DeviceToken.register()` factory's own fields 1:1, the established convention
  every other module's create-request schema already follows.
- `DELETE /notifications/tokens/{device_token_id}` — line 164, "owner", revoke token. A soft
  revoke (`revoked_at` set), not a row deletion — see `domain/entities.py`'s `DeviceToken.revoke`
  docstring for why. Ownership enforced directly, same posture as the notification routes.

**Route registration order:** the literal `/tokens`/`/tokens/{device_token_id}` paths are
registered before the parameterized `/{notification_id}` routes, avoiding any path-matching
ambiguity between a bare path segment and a path parameter (no such ambiguity actually exists
here — no `GET /notifications/tokens` route is documented — but the ordering is deliberate,
not incidental).

**Not exposed this phase** (flagged, not silently dropped): a generic `POST /notifications`
(no document names one — `application/commands.py`'s own docstring); `GET/DELETE` for
individual `DeviceToken`s beyond the documented revoke; any `notification_preferences`
(§7.7) read/write route (no document names one, and no `NotificationPreference` aggregate is
built this phase at all — see `domain/entities.py`'s module docstring for the full gap).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from raad.core.pagination import CursorPageRequest, FilterCondition
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import (
    get_cursor_page_request,
    get_filter_conditions,
    require_permission,
)
from raad.interfaces.http.pagination import CursorPageResponse, to_cursor_page_response
from raad.modules.notifications.api.deps import (
    get_notification_service,
    get_notifications_uow,
)
from raad.modules.notifications.api.schemas import (
    DeviceTokenResponse,
    NotificationResponse,
    RegisterDeviceTokenRequest,
)
from raad.modules.notifications.application.commands import (
    MarkNotificationReadCommand,
    RegisterDeviceTokenCommand,
    RevokeDeviceTokenCommand,
)
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.queries import (
    DeviceTokenDTO,
    GetNotificationByIdQuery,
    ListNotificationsForRecipientQuery,
    NotificationDTO,
)
from raad.modules.notifications.application.services import NotificationApplicationService

notifications_router = APIRouter()


def _notification_dto_to_response(notification: NotificationDTO) -> NotificationResponse:
    return NotificationResponse(
        id=notification.id,
        organization_id=notification.organization_id,
        recipient_user_id=notification.recipient_user_id,
        type=notification.type,
        title=notification.title,
        body=notification.body,
        data=notification.data,
        trip_id=notification.trip_id,
        status=notification.status,
        created_at=notification.created_at,
        read_at=notification.read_at,
    )


def _device_token_dto_to_response(device_token: DeviceTokenDTO) -> DeviceTokenResponse:
    return DeviceTokenResponse(
        id=device_token.id,
        user_id=device_token.user_id,
        fcm_token=device_token.fcm_token,
        platform=device_token.platform,
        created_at=device_token.created_at,
        revoked_at=device_token.revoked_at,
    )


@notifications_router.post(
    "/tokens",
    response_model=DeviceTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register an FCM device token",
    description=(
        "Parent/Driver (API Contracts §4.6 line 163). Rejects a token already registered "
        "(`ConflictError`, `ux_device_tokens__token` defense-in-depth — "
        "`application/validators.py`'s `ensure_fcm_token_available`). Authorization resolves "
        "against the real seeded RBAC permission matrix (ADR-0004)."
    ),
)
async def register_device_token(
    body: RegisterDeviceTokenRequest,
    principal: Principal = Depends(
        require_permission(Permission("notifications.tokens.create"))
    ),
    notification_service: NotificationApplicationService = Depends(get_notification_service),
    uow: NotificationsUnitOfWork = Depends(get_notifications_uow),
) -> DeviceTokenResponse:
    command = RegisterDeviceTokenCommand(
        fcm_token=body.fcm_token, platform=body.platform, actor=principal
    )
    device_token = await notification_service.register_device_token(command, uow=uow)
    return _device_token_dto_to_response(device_token)


@notifications_router.delete(
    "/tokens/{device_token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an FCM device token",
    description=(
        "Owner (API Contracts §4.6 line 164). A soft revoke, not a row deletion — see "
        "`domain/entities.py`'s `DeviceToken.revoke` docstring. Ownership enforced directly: a "
        "non-owner request raises `NotFoundError` (404), not `AuthorizationError` — see "
        "`application/queries.py`'s `GetNotificationByIdQuery` docstring for the 404-over-403 "
        "reasoning applied uniformly across this module. Authorization resolves against the "
        "real seeded RBAC permission matrix."
    ),
)
async def revoke_device_token(
    device_token_id: str,
    principal: Principal = Depends(
        require_permission(Permission("notifications.tokens.delete"))
    ),
    notification_service: NotificationApplicationService = Depends(get_notification_service),
    uow: NotificationsUnitOfWork = Depends(get_notifications_uow),
) -> None:
    command = RevokeDeviceTokenCommand(device_token_id=device_token_id, actor=principal)
    await notification_service.revoke_device_token(command, uow=uow)


@notifications_router.get(
    "",
    response_model=CursorPageResponse[NotificationResponse],
    status_code=status.HTTP_200_OK,
    summary="List the caller's own notifications",
    description=(
        "Any authenticated (API Contracts §4.6 line 161: \"own in-app notifications "
        "(paginated)\"). Scoped to `recipient_user_id = principal.user_id` — the first list "
        "endpoint in this codebase scoped by personal ownership rather than tenant. "
        "Cursor-paginated (`?limit&cursor`, §7) as of the Pagination/Filtering/Sorting phase — "
        "returns most-recent-first (`created_at` descending), this route's own flagged "
        "interpretive choice (no document specifies ordering). Accepts "
        "`filter[type]=...`/`filter[trip_id]=...` (§8), narrowing-only on top of the caller's "
        "own mandatory scope — `status` is not filterable (domain-derived, not a persisted "
        "column). Authorization resolves against the real seeded RBAC permission matrix."
    ),
)
async def list_notifications(
    principal: Principal = Depends(
        require_permission(Permission("notifications.notifications.list"))
    ),
    cursor_request: CursorPageRequest = Depends(get_cursor_page_request),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    notification_service: NotificationApplicationService = Depends(get_notification_service),
    uow: NotificationsUnitOfWork = Depends(get_notifications_uow),
) -> CursorPageResponse[NotificationResponse]:
    page = await notification_service.list_notifications_for_recipient(
        ListNotificationsForRecipientQuery(
            recipient_user_id=principal.user_id,
            cursor_request=cursor_request,
            filters=filters,
        ),
        uow=uow,
    )
    return to_cursor_page_response(page, _notification_dto_to_response)


@notifications_router.get(
    "/{notification_id}",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a notification by id",
    description=(
        "Not itemized in API Contracts §4.6's compact table — uniform-CRUD addition, see "
        "`routers.py`'s module docstring. Ownership-scoped identically to `list_notifications`; "
        "a non-owner request raises `NotFoundError` (404). Authorization resolves against "
        "the real seeded RBAC permission matrix."
    ),
)
async def get_notification(
    notification_id: str,
    principal: Principal = Depends(
        require_permission(Permission("notifications.notifications.read"))
    ),
    notification_service: NotificationApplicationService = Depends(get_notification_service),
    uow: NotificationsUnitOfWork = Depends(get_notifications_uow),
) -> NotificationResponse:
    notification = await notification_service.get_notification_by_id(
        GetNotificationByIdQuery(
            notification_id=notification_id, recipient_user_id=principal.user_id
        ),
        uow=uow,
    )
    return _notification_dto_to_response(notification)


@notifications_router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark a notification read",
    description=(
        "Recipient (API Contracts §4.6 line 162). Ownership enforced directly — see "
        "`application/services.py`'s module docstring. Idempotent (`domain/entities.py`'s "
        "`Notification.mark_read`). Authorization resolves against the real seeded RBAC "
        "permission matrix."
    ),
)
async def mark_notification_read(
    notification_id: str,
    principal: Principal = Depends(
        require_permission(Permission("notifications.notifications.update"))
    ),
    notification_service: NotificationApplicationService = Depends(get_notification_service),
    uow: NotificationsUnitOfWork = Depends(get_notifications_uow),
) -> NotificationResponse:
    command = MarkNotificationReadCommand(notification_id=notification_id, actor=principal)
    notification = await notification_service.mark_notification_read(command, uow=uow)
    return _notification_dto_to_response(notification)
