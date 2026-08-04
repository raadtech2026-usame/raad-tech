"""Composition-root wiring (Backend LLD §9.2).

Binds the interfaces that have a concrete implementation *today*. Module-specific ports
(`PushSenderPort` -> `FcmPushSender`, `PaymentProviderPort` -> `EvcPlusPaymentAdapter`,
`DeviceCommandPort` -> `DeviceCommandClient`, `VideoSignalingPort` -> `VideoSignalingClient`)
still have no bound adapter and stay deliberately absent, so resolving them fails loudly
(`LookupError`) instead of silently resolving to a fake. `ScopeResolver`/`PermissionEvaluator`
(ADR-0004/0005) and `BrokerPort`/`BrokerConsumer`/`DeadLetterQueue`/`LockPort` (ADR-0008, Redis
Streams at MVP) are now bound for real, conditional on their own settings being configured.
"""

from __future__ import annotations

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import Settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from raad.core.di.container import Container
from raad.core.di.session_cap_adapter import SystemSettingSessionCapAdapter
from raad.core.events.outbox import OutboxWriter, SqlOutboxPublisher
from raad.core.events.ports import BrokerConsumer, BrokerPort, OutboxPublisher
from raad.core.events.processor import EventProcessorRegistry
from raad.core.events.redis_streams import (
    RedisDeadLetterQueue,
    RedisStreamsBrokerConsumer,
    RedisStreamsBrokerPort,
)
from raad.core.health.service import HealthCheckService
from raad.core.ids.generator import IdGenerator, UlidGenerator
from raad.core.observability.metrics import MetricsRegistry
from raad.core.policies import SubscriptionAccessPolicy, VideoAccessPolicy
from raad.core.security.login_rate_limiter import LoginRateLimiter
from raad.core.security.password_hashing import PasswordHasher, Pbkdf2PasswordHasher
from raad.core.security.password_policy import PasswordPolicy
from raad.core.security.permissions import PermissionEvaluator
from raad.core.security.tokens import JwtTokenService, TokenService
from raad.core.tenancy.resolver import ScopeResolver
from raad.core.time.clock import Clock, SystemClock
from raad.core.workers.dlq import DeadLetterQueue
from raad.core.workers.idempotency import IdempotencyStore, InMemoryIdempotencyStore
from raad.core.workers.retry import ExponentialBackoffRetryPolicy, RetryPolicy
from raad.core.workers.scheduler import LockPort, RedisLockPort
from raad.modules.iam.application.ports import IamUnitOfWork, SessionCapPort
from raad.modules.iam.application.services import (
    AuthApplicationService,
    PermissionApplicationService,
    UserApplicationService,
)
from raad.modules.iam.infra.adapters import IamPermissionEvaluator
from raad.modules.iam.infra.repositories import SqlAlchemyIamUnitOfWork
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.services import (
    DeviceApplicationService,
    DeviceInventoryApplicationService,
    VehicleApplicationService,
)
from raad.modules.fleet_device.events.subscribers import register_fleet_device_processors
from raad.modules.fleet_device.infra.repositories import (
    SqlAlchemyFleetDeviceUnitOfWork,
)
from raad.modules.organization.application.ports import (
    IamProvisioningPort,
    OrganizationUnitOfWork,
)
from raad.modules.organization.application.services import (
    OrganizationApplicationService,
    RegionApplicationService,
    ScopeAssignmentApplicationService,
)
from raad.modules.organization.infra.adapters import (
    IamUserProvisioningAdapter as OrganizationIamUserProvisioningAdapter,
    OrganizationScopeResolver,
)
from raad.modules.organization.infra.repositories import (
    SqlAlchemyOrganizationUnitOfWork,
)
from raad.modules.tracking.application.ports import (
    GeofenceStatePort,
    LatestPositionPort,
    TrackingUnitOfWork,
)
from raad.modules.tracking.application.services import TrackingApplicationService
from raad.modules.tracking.events.subscribers import register_tracking_processors
from raad.modules.tracking.infra.adapters import (
    RedisGeofenceStatePort,
    RedisLatestPositionPort,
)
from raad.modules.tracking.infra.repositories import SqlAlchemyTrackingUnitOfWork
from raad.modules.transport_ops.application.ports import (
    TransportOpsUnitOfWork,
    UserProvisioningPort,
)
from raad.modules.transport_ops.application.services import (
    DriverApplicationService,
    ParentApplicationService,
    RouteApplicationService,
    StudentApplicationService,
    StudentAssignmentApplicationService,
    StudentParentApplicationService,
    TripApplicationService,
)
from raad.modules.transport_ops.infra.adapters import IamUserProvisioningAdapter
from raad.modules.transport_ops.infra.repositories import (
    SqlAlchemyTransportOpsUnitOfWork,
)
from raad.modules.billing.application.ports import BillingUnitOfWork, PaymentProviderPort
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.billing.infra.repositories import SqlAlchemyBillingUnitOfWork
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.services import NotificationApplicationService
from raad.modules.notifications.events.subscribers import register_notification_processors
from raad.modules.notifications.infra.repositories import (
    SqlAlchemyNotificationsUnitOfWork,
)
from raad.modules.reporting.application.ports import ReportingUnitOfWork
from raad.modules.reporting.application.services import ReportingApplicationService
from raad.modules.reporting.infra.repositories import SqlAlchemyReportingUnitOfWork
from raad.modules.video.application.ports import VideoProviderPort, VideoUnitOfWork
from raad.modules.video.application.services import VideoApplicationService
from raad.modules.video.infra.repositories import SqlAlchemyVideoUnitOfWork
from raad.modules.platform_audit.application.ports import PlatformAuditUnitOfWork
from raad.modules.platform_audit.application.services import PlatformAuditApplicationService
from raad.modules.platform_audit.infra.repositories import (
    SqlAlchemyPlatformAuditUnitOfWork,
)


def build_container(settings: Settings) -> Container:
    container = Container()
    # Priority 1 Item 5 (PROJECT_STATUS.md, health checks): pre-declared here (rather than only
    # inside their own `if settings.redis.url:`/`if settings.broker.url:` blocks below) so
    # `HealthCheckService`'s construction at the very end of this function can reference them
    # regardless of which combination of dependencies is actually configured.
    latest_position_redis_client: Redis | None = None
    broker_redis_client: Redis | None = None
    container.bind_singleton(Settings, settings)
    # Priority 1 Item 5 (PROJECT_STATUS.md, "minimum monitoring") — always bound, no
    # dependencies of its own; RequestLoggingMiddleware increments it on every request,
    # `/metrics` (interfaces/http/health.py) renders it.
    container.bind_singleton(MetricsRegistry, MetricsRegistry())
    container.bind_singleton(Clock, SystemClock())
    container.bind_singleton(PasswordHasher, Pbkdf2PasswordHasher())
    container.bind_singleton(
        PasswordPolicy, PasswordPolicy(settings.auth.password_policy)
    )
    container.bind_singleton(IdGenerator, UlidGenerator())
    # Phase 14: stateless, pure decision objects - no constructor dependencies, same
    # unconditional-singleton treatment as any other side-effect-free core service.
    container.bind_singleton(SubscriptionAccessPolicy, SubscriptionAccessPolicy())
    container.bind_singleton(VideoAccessPolicy, VideoAccessPolicy())
    container.bind_singleton(OutboxWriter, OutboxWriter())
    # AuditWriter (ADR-0007) - stateless, same unconditional-singleton treatment as
    # OutboxWriter above; threaded through every SqlAlchemy<Module>UnitOfWork factory below.
    container.bind_singleton(AuditWriter, AuditWriter())
    container.bind_singleton(EventProcessorRegistry, EventProcessorRegistry())
    container.bind_singleton(
        RetryPolicy,
        ExponentialBackoffRetryPolicy(
            max_attempts=settings.workers.retry_max_attempts,
            base_delay_seconds=settings.workers.retry_base_delay_seconds,
            max_delay_seconds=settings.workers.retry_max_delay_seconds,
        ),
    )
    # Process-local only (`core/workers/idempotency.py`) — replace with a Redis/DB-backed
    # store before running more than one worker process.
    container.bind_singleton(IdempotencyStore, InMemoryIdempotencyStore())

    # UserApplicationService needs no TokenService, so it's always constructible (unlike
    # AuthApplicationService, below, which is bound only alongside TokenService).
    container.bind_singleton(
        UserApplicationService,
        UserApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
            password_hasher=container.resolve(PasswordHasher),
            password_policy=container.resolve(PasswordPolicy),
        ),
    )
    # PermissionApplicationService needs no TokenService either — always constructible, same
    # reasoning as UserApplicationService above.
    container.bind_singleton(
        PermissionApplicationService,
        PermissionApplicationService(clock=container.resolve(Clock)),
    )

    # OrganizationApplicationService now additionally needs `IamProvisioningPort` (ADR-0017) —
    # bound further below, inside the `if settings.db.url:` block, since the concrete adapter
    # needs a DB-backed `IamUnitOfWork` factory (same reasoning ParentApplicationService/
    # DriverApplicationService's own binding already documents). RegionApplicationService is
    # unaffected and stays bound unconditionally here.
    container.bind_singleton(
        RegionApplicationService,
        RegionApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )
    # ScopeAssignmentApplicationService needs no id_generator either — composite-key grant
    # data, same reasoning as PermissionApplicationService above.
    container.bind_singleton(
        ScopeAssignmentApplicationService,
        ScopeAssignmentApplicationService(clock=container.resolve(Clock)),
    )
    container.bind_singleton(
        VehicleApplicationService,
        VehicleApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )
    container.bind_singleton(
        DeviceApplicationService,
        DeviceApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )
    container.bind_singleton(
        DeviceInventoryApplicationService,
        DeviceInventoryApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )

    # StudentApplicationService/ParentApplicationService need no TokenService either — always
    # constructible, same reasoning as OrganizationApplicationService above.
    container.bind_singleton(
        StudentApplicationService,
        StudentApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )
    # ParentApplicationService/DriverApplicationService now additionally need
    # `UserProvisioningPort` (ADR-0003, accepted) — bound further below, inside the
    # `if settings.db.url:` block, since the concrete adapter needs a DB-backed
    # `IamUnitOfWork` factory. Both bindings therefore moved there too; see that block for the
    # actual `container.bind_singleton(ParentApplicationService, ...)`/`DriverApplicationService`
    # calls.
    # StudentParentApplicationService needs no id_generator (StudentParent has no surrogate id
    # to mint, `application/services.py`'s Phase 10.7 docstring) or TokenService — always
    # constructible, same reasoning as the two services above.
    container.bind_singleton(
        StudentParentApplicationService,
        StudentParentApplicationService(clock=container.resolve(Clock)),
    )
    # RouteApplicationService needs no TokenService either — always constructible, same
    # reasoning as the services above.
    container.bind_singleton(
        RouteApplicationService,
        RouteApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )
    # TripApplicationService needs no TokenService either — always constructible, same
    # reasoning as the services above.
    container.bind_singleton(
        TripApplicationService,
        TripApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )
    # StudentAssignmentApplicationService needs no TokenService either — always constructible,
    # same reasoning as the services above.
    container.bind_singleton(
        StudentAssignmentApplicationService,
        StudentAssignmentApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )

    # BillingApplicationService is always constructible too — `payment_provider` is optional
    # by design (see that class's own module docstring: only `initiate_payment`'s actual charge
    # step needs it, and no `PaymentProviderPort` adapter exists yet — Phase 15's own scope
    # explicitly forbids integrating a real one). `try_resolve` mirrors `LatestPositionPort`'s
    # pattern above but, unlike Tracking, a `None` result here does not block binding the
    # service — it is passed straight through to the optional constructor arg.
    container.bind_singleton(
        BillingApplicationService,
        BillingApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
            payment_provider=container.try_resolve(PaymentProviderPort),
        ),
    )

    # NotificationApplicationService needs no TokenService either — always constructible, same
    # reasoning as the services above.
    container.bind_singleton(
        NotificationApplicationService,
        NotificationApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )

    # ReportingApplicationService needs no TokenService either — always constructible, same
    # reasoning as the services above.
    container.bind_singleton(
        ReportingApplicationService,
        ReportingApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )

    # VideoApplicationService is always constructible too — `video_provider` is optional by
    # design (see that class's own module docstring), identical to `BillingApplicationService.
    # payment_provider` above. No `VideoProviderPort` adapter exists this phase — the user's own
    # task scope explicitly forbids implementing native JT1078 or integrating a real vendor
    # video API this phase ("Implement only the abstraction layer if needed").
    container.bind_singleton(
        VideoApplicationService,
        VideoApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
            video_provider=container.try_resolve(VideoProviderPort),
        ),
    )

    # PlatformAuditApplicationService needs no id_generator (AuditEntry is never created
    # through this module; SystemSetting is keyed by its own `key`, not a minted id) or
    # TokenService — always constructible, same reasoning as the services above.
    container.bind_singleton(
        PlatformAuditApplicationService,
        PlatformAuditApplicationService(clock=container.resolve(Clock)),
    )

    # SessionCapPort (ADR-0019): bound unconditionally — unlike TokenService/RedisLatestPosition
    # Port below, this needs no external dependency beyond Postgres (already required), and
    # `AuthApplicationService`'s own construction (below) requires it with no default. The
    # adapter resolves `PlatformAuditApplicationService`/`PlatformAuditUnitOfWork` lazily, per
    # call, so binding it here (before `PlatformAuditUnitOfWork` itself is bound, further down)
    # is safe — nothing calls `get_max_sessions()` until an actual login/refresh request.
    container.bind_singleton(SessionCapPort, SystemSettingSessionCapAdapter(container))

    # LatestPositionPort (Database Design §7.1: latest position is Redis-backed, not read from
    # the PostgreSQL history table) — RedisLatestPositionPort (Backend Stabilization phase)
    # needs a reachable `RAAD_REDIS__URL`; left unbound without one, same "fail loudly, don't
    # fake it" policy as `db.url`/`jwt_secret_key` below. `decode_responses=True` since the
    # adapter reads the key's value as a JSON *string* (`redis.asyncio.Redis.get` would
    # otherwise return `bytes`).
    if settings.redis.url:
        # Priority 1 Item 4 (PROJECT_STATUS.md, Redis production hardening): explicit
        # connection-level timeouts/health-check, previously absent entirely — see
        # `RedisConnectionSettings`'s own docstring (`core/config/settings.py`).
        latest_position_redis_client = Redis.from_url(
            settings.redis.url,
            decode_responses=True,
            socket_connect_timeout=settings.redis.socket_connect_timeout_seconds,
            socket_timeout=settings.redis.socket_timeout_seconds,
            health_check_interval=settings.redis.health_check_interval_seconds,
        )
        container.bind_singleton(
            LatestPositionPort,
            RedisLatestPositionPort(
                latest_position_redis_client,
                clock=container.resolve(Clock),
                id_generator=container.resolve(IdGenerator),
            ),
        )
        # GeofenceStatePort (post-F7 roadmap item A5; ADR-0014) - reuses the same Redis client
        # as LatestPositionPort above rather than opening a second connection, the same
        # "reuse, don't duplicate" convention the device-gateway's own Redis wiring follows.
        container.bind_singleton(
            GeofenceStatePort, RedisGeofenceStatePort(latest_position_redis_client)
        )
        # LoginRateLimiter (Priority 1 Item 3, PROJECT_STATUS.md) - same "reuse, don't
        # duplicate" reasoning as GeofenceStatePort immediately above. Left unbound without a
        # reachable RAAD_REDIS__URL, same policy as everything else in this `if` block -
        # RateLimitMiddleware (interfaces/http/middleware.py) treats that as "not enforced,"
        # logged once, never as a reason to refuse login itself.
        container.bind_singleton(
            LoginRateLimiter,
            LoginRateLimiter(latest_position_redis_client, settings=settings.auth.rate_limit),
        )

    # TrackingApplicationService is always constructible — `latest_position_port` is optional
    # at the service level (Backend Stabilization phase, see that class's own module
    # docstring), identical to `BillingApplicationService.payment_provider`/
    # `VideoApplicationService.video_provider`'s already-established pattern. Only
    # `get_current_vehicle_position` needs the port and fails loudly without one; every other
    # method (including `prune_position_history`, the retention scheduled job's own entry
    # point) needs no Redis at all and must stay reachable regardless.
    container.bind_singleton(
        TrackingApplicationService,
        TrackingApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
            latest_position_port=container.try_resolve(LatestPositionPort),
        ),
    )

    # Event broker (ADR-0008: Redis Streams at MVP) - BrokerPort/BrokerConsumer/LockPort/
    # DeadLetterQueue all stay unbound without a reachable RAAD_BROKER__URL, the same "fail
    # loudly, don't fake it" policy every other pending-infra port in this file follows. A
    # separate Redis client from `latest_position_redis_client` above - `broker.url` is an
    # independently configurable setting (ADR-0008's own reasoning), even though an MVP
    # deployment will typically point both at the same instance.
    if settings.broker.url:
        # Priority 1 Item 4: same connection-level hardening as latest_position_redis_client
        # above, independently configurable via `settings.broker.*` (this client's own
        # RedisConnectionSettings fields, not shared with `settings.redis.*`).
        broker_redis_client = Redis.from_url(
            settings.broker.url,
            decode_responses=True,
            socket_connect_timeout=settings.broker.socket_connect_timeout_seconds,
            socket_timeout=settings.broker.socket_timeout_seconds,
            health_check_interval=settings.broker.health_check_interval_seconds,
        )
        broker_port = RedisStreamsBrokerPort(broker_redis_client)
        container.bind_singleton(BrokerPort, broker_port)
        container.bind_singleton(LockPort, RedisLockPort(broker_redis_client))
        dead_letter_queue = RedisDeadLetterQueue(broker_redis_client)
        container.bind_singleton(DeadLetterQueue, dead_letter_queue)
        container.bind_singleton(
            BrokerConsumer,
            RedisStreamsBrokerConsumer(
                broker_redis_client,
                group_name="notification-worker",
                retry_policy=container.resolve(RetryPolicy),
                dead_letter_queue=dead_letter_queue,
            ),
        )

        # EventProcessorRegistry (already bound as an empty singleton above) gets the
        # Notification Worker's four D1 processors registered - see
        # `modules/notifications/events/subscribers.py`'s own module docstring.
        register_notification_processors(
            container.resolve(EventProcessorRegistry), container
        )

        # Same registry, roadmap track B2's consumer half (ADR-0009): persists
        # `DevicePositionReported` events published by the device-plane service - see
        # `modules/tracking/events/subscribers.py`'s own module docstring for the wire-envelope
        # contract and for why the producer side isn't wired yet either.
        register_tracking_processors(container.resolve(EventProcessorRegistry), container)

        # Same registry, post-F7 production readiness roadmap item A3: persists
        # `DeviceOnline`/`DeviceOffline` (published by the device-plane service since ADR-0010,
        # never consumed anywhere on this backend before now) onto `devices.last_seen_at` - see
        # `modules/fleet_device/events/subscribers.py`'s own module docstring.
        register_fleet_device_processors(container.resolve(EventProcessorRegistry), container)

    # TokenService needs a non-empty signing secret. In `dev`/`staging` without one configured
    # (e.g. no .env populated yet) it is left unbound — same "fail loudly, don't fake it"
    # policy as the ports above — rather than signing tokens with an empty key.
    if settings.auth.jwt_secret_key:
        container.bind_singleton(
            TokenService,
            JwtTokenService(
                secret_key=settings.auth.jwt_secret_key,
                algorithm=settings.auth.jwt_algorithm,
                access_token_ttl_seconds=settings.auth.access_token_ttl_seconds,
                refresh_token_ttl_seconds=settings.auth.refresh_token_ttl_seconds,
                clock=container.resolve(Clock),
            ),
        )
        container.bind_singleton(
            AuthApplicationService,
            AuthApplicationService(
                clock=container.resolve(Clock),
                id_generator=container.resolve(IdGenerator),
                token_service=container.resolve(TokenService),
                password_hasher=container.resolve(PasswordHasher),
                session_cap_port=container.resolve(SessionCapPort),
                lockout_settings=settings.auth.lockout,
            ),
        )

    # Engine/session factory/UnitOfWork need a configured DB URL. Left unbound without one
    # (dev/CI with no PostgreSQL reachable yet) — same policy as TokenService above — rather
    # than constructing an AsyncEngine against an empty connection string.
    if settings.db.url:
        engine: AsyncEngine = build_engine(settings.db)
        session_factory: async_sessionmaker[AsyncSession] = build_session_factory(
            engine
        )
        container.bind_singleton(AsyncEngine, engine)
        container.bind_singleton(async_sessionmaker, session_factory)
        container.bind_factory(
            UnitOfWork,
            lambda: SqlAlchemyUnitOfWork(
                session_factory,
                container.resolve(OutboxWriter),
                container.resolve(AuditWriter),
            ),
        )
        container.bind_factory(
            IamUnitOfWork,
            lambda: SqlAlchemyIamUnitOfWork(
                session_factory,
                container.resolve(OutboxWriter),
                container.resolve(AuditWriter),
            ),
        )
        # PermissionEvaluator (Database Design §4.4's RBAC permission matrix) needs a fresh
        # IamUnitOfWork per `has_permission` call, not a shared one — `container.resolve`
        # (not a captured variable) re-invokes the `IamUnitOfWork` factory above every time,
        # exactly like every other per-request UnitOfWork resolution in this codebase.
        container.bind_singleton(
            PermissionEvaluator,
            IamPermissionEvaluator(lambda: container.resolve(IamUnitOfWork)),
        )
        container.bind_factory(
            OrganizationUnitOfWork,
            lambda: SqlAlchemyOrganizationUnitOfWork(
                session_factory,
                container.resolve(OutboxWriter),
                container.resolve(AuditWriter),
            ),
        )
        # ScopeResolver (Phase 2 §17.4's effective_org_scope) needs a fresh
        # OrganizationUnitOfWork per call, same reasoning as PermissionEvaluator above.
        container.bind_singleton(
            ScopeResolver,
            OrganizationScopeResolver(
                lambda: container.resolve(OrganizationUnitOfWork)
            ),
        )
        # IamProvisioningPort (ADR-0017) — a fresh IamUnitOfWork per call, same uow_factory
        # shape as PermissionEvaluator/ScopeResolver/transport_ops's identical port above.
        container.bind_singleton(
            IamProvisioningPort,
            OrganizationIamUserProvisioningAdapter(
                user_service=container.resolve(UserApplicationService),
                uow_factory=lambda: container.resolve(IamUnitOfWork),
            ),
        )
        # OrganizationApplicationService depends on IamProvisioningPort (just bound above),
        # so — unlike RegionApplicationService — it's bound here, inside the DB-configured
        # block, rather than unconditionally near the top of this function.
        container.bind_singleton(
            OrganizationApplicationService,
            OrganizationApplicationService(
                clock=container.resolve(Clock),
                id_generator=container.resolve(IdGenerator),
                iam_provisioning=container.resolve(IamProvisioningPort),
            ),
        )
        container.bind_factory(
            FleetDeviceUnitOfWork,
            lambda: SqlAlchemyFleetDeviceUnitOfWork(
                session_factory,
                container.resolve(OutboxWriter),
                container.resolve(AuditWriter),
            ),
        )
        container.bind_factory(
            TrackingUnitOfWork,
            lambda: SqlAlchemyTrackingUnitOfWork(
                session_factory,
                container.resolve(OutboxWriter),
                container.resolve(AuditWriter),
            ),
        )
        container.bind_factory(
            TransportOpsUnitOfWork,
            lambda: SqlAlchemyTransportOpsUnitOfWork(
                session_factory,
                container.resolve(OutboxWriter),
                container.resolve(AuditWriter),
            ),
        )
        # UserProvisioningPort (ADR-0003, accepted) — a fresh IamUnitOfWork per call, same
        # `uow_factory` shape as PermissionEvaluator/ScopeResolver above.
        container.bind_singleton(
            UserProvisioningPort,
            IamUserProvisioningAdapter(
                user_service=container.resolve(UserApplicationService),
                uow_factory=lambda: container.resolve(IamUnitOfWork),
            ),
        )
        # ParentApplicationService/DriverApplicationService now depend on
        # UserProvisioningPort (just bound above), so — unlike every sibling
        # transport_ops service — both are bound here, inside the DB-configured block, rather
        # than unconditionally near the top of this function.
        container.bind_singleton(
            ParentApplicationService,
            ParentApplicationService(
                clock=container.resolve(Clock),
                id_generator=container.resolve(IdGenerator),
                user_provisioning=container.resolve(UserProvisioningPort),
            ),
        )
        container.bind_singleton(
            DriverApplicationService,
            DriverApplicationService(
                clock=container.resolve(Clock),
                id_generator=container.resolve(IdGenerator),
                user_provisioning=container.resolve(UserProvisioningPort),
            ),
        )
        container.bind_factory(
            BillingUnitOfWork,
            lambda: SqlAlchemyBillingUnitOfWork(
                session_factory,
                container.resolve(OutboxWriter),
                container.resolve(AuditWriter),
            ),
        )
        container.bind_factory(
            NotificationsUnitOfWork,
            lambda: SqlAlchemyNotificationsUnitOfWork(
                session_factory,
                container.resolve(OutboxWriter),
                container.resolve(AuditWriter),
            ),
        )
        container.bind_factory(
            ReportingUnitOfWork,
            lambda: SqlAlchemyReportingUnitOfWork(
                session_factory,
                container.resolve(OutboxWriter),
                container.resolve(AuditWriter),
            ),
        )
        container.bind_factory(
            VideoUnitOfWork,
            lambda: SqlAlchemyVideoUnitOfWork(
                session_factory,
                container.resolve(OutboxWriter),
                container.resolve(AuditWriter),
            ),
        )
        container.bind_factory(
            PlatformAuditUnitOfWork,
            lambda: SqlAlchemyPlatformAuditUnitOfWork(
                session_factory,
                container.resolve(OutboxWriter),
                container.resolve(AuditWriter),
            ),
        )

        # OutboxPublisher (the Outbox Relay's read/publish side) additionally needs a
        # BrokerPort — bound above (ADR-0008) only when `settings.broker.url` is configured;
        # stays unbound without one, the same "fail loudly, don't fake it" policy as every
        # other pending-infra port. `OutboxRelayWorker` already documents the resulting
        # previously-permanent no-op this makes conditional instead.
        broker = container.try_resolve(BrokerPort)
        if broker is not None:
            container.bind_singleton(
                OutboxPublisher, SqlOutboxPublisher(session_factory, broker)
            )

    # HealthCheckService (Priority 1 Item 5) — always bound, referencing whichever of
    # engine/latest_position_redis_client/broker_redis_client actually got constructed above
    # (each independently optional); `container.try_resolve(AsyncEngine)` rather than a local
    # variable since the DB engine, unlike the two Redis clients, is already bound to the
    # container by the `if settings.db.url:` block earlier in this function.
    container.bind_singleton(
        HealthCheckService,
        HealthCheckService(
            engine=container.try_resolve(AsyncEngine),
            redis_client=latest_position_redis_client,
            broker_client=broker_redis_client,
        ),
    )

    return container
