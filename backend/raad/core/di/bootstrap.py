"""Composition-root wiring (Backend LLD §9.2).

Binds the interfaces that have a concrete implementation *today*. Module-specific ports
(`PushSenderPort` -> `FcmPushSender`, `PaymentProviderPort` -> `EvcPlusPaymentAdapter`,
`DeviceCommandPort` -> `DeviceCommandClient`, `VideoSignalingPort` -> `VideoSignalingClient`,
`ScopeResolver`, `PermissionEvaluator`) — plus `BrokerPort`/`BrokerConsumer`/
`DeadLetterQueue`/`LockPort` (all pending the broker choice, Phase 2 §4.3, still an open
item) — are bound here once their owning module/infra is implemented in a later phase,
deliberately absent now rather than stubbed, so a missing binding fails loudly (`LookupError`)
instead of silently resolving to a fake.
"""

from __future__ import annotations

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import Settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from raad.core.di.container import Container
from raad.core.events.outbox import OutboxWriter, SqlOutboxPublisher
from raad.core.events.ports import BrokerPort, OutboxPublisher
from raad.core.events.processor import EventProcessorRegistry
from raad.core.ids.generator import IdGenerator, UlidGenerator
from raad.core.policies import SubscriptionAccessPolicy, VideoAccessPolicy
from raad.core.security.password_hashing import PasswordHasher, Pbkdf2PasswordHasher
from raad.core.security.password_policy import PasswordPolicy
from raad.core.security.permissions import PermissionEvaluator
from raad.core.security.tokens import JwtTokenService, TokenService
from raad.core.tenancy.resolver import ScopeResolver
from raad.core.time.clock import Clock, SystemClock
from raad.core.workers.idempotency import IdempotencyStore, InMemoryIdempotencyStore
from raad.core.workers.retry import ExponentialBackoffRetryPolicy, RetryPolicy
from raad.modules.iam.application.ports import IamUnitOfWork
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
    VehicleApplicationService,
)
from raad.modules.fleet_device.infra.repositories import (
    SqlAlchemyFleetDeviceUnitOfWork,
)
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.application.services import (
    OrganizationApplicationService,
    RegionApplicationService,
    ScopeAssignmentApplicationService,
)
from raad.modules.organization.infra.adapters import OrganizationScopeResolver
from raad.modules.organization.infra.repositories import (
    SqlAlchemyOrganizationUnitOfWork,
)
from raad.modules.tracking.application.ports import (
    LatestPositionPort,
    TrackingUnitOfWork,
)
from raad.modules.tracking.application.services import TrackingApplicationService
from raad.modules.tracking.infra.adapters import RedisLatestPositionPort
from raad.modules.tracking.infra.repositories import SqlAlchemyTrackingUnitOfWork
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.services import (
    DriverApplicationService,
    ParentApplicationService,
    RouteApplicationService,
    StudentApplicationService,
    StudentAssignmentApplicationService,
    StudentParentApplicationService,
    TripApplicationService,
)
from raad.modules.transport_ops.infra.repositories import (
    SqlAlchemyTransportOpsUnitOfWork,
)
from raad.modules.billing.application.ports import BillingUnitOfWork, PaymentProviderPort
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.billing.infra.repositories import SqlAlchemyBillingUnitOfWork
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.services import NotificationApplicationService
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
    container.bind_singleton(Settings, settings)
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

    # OrganizationApplicationService/RegionApplicationService need no TokenService either —
    # always constructible, same reasoning as UserApplicationService above.
    container.bind_singleton(
        OrganizationApplicationService,
        OrganizationApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )
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

    # StudentApplicationService/ParentApplicationService need no TokenService either — always
    # constructible, same reasoning as OrganizationApplicationService above.
    container.bind_singleton(
        StudentApplicationService,
        StudentApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )
    container.bind_singleton(
        ParentApplicationService,
        ParentApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
    )
    # StudentParentApplicationService needs no id_generator (StudentParent has no surrogate id
    # to mint, `application/services.py`'s Phase 10.7 docstring) or TokenService — always
    # constructible, same reasoning as the two services above.
    container.bind_singleton(
        StudentParentApplicationService,
        StudentParentApplicationService(clock=container.resolve(Clock)),
    )
    # DriverApplicationService needs no TokenService either — always constructible, same
    # reasoning as StudentApplicationService/ParentApplicationService above.
    container.bind_singleton(
        DriverApplicationService,
        DriverApplicationService(
            clock=container.resolve(Clock),
            id_generator=container.resolve(IdGenerator),
        ),
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

    # LatestPositionPort (Database Design §7.1: latest position is Redis-backed, not read from
    # the PostgreSQL history table) — RedisLatestPositionPort (Backend Stabilization phase)
    # needs a reachable `RAAD_REDIS__URL`; left unbound without one, same "fail loudly, don't
    # fake it" policy as `db.url`/`jwt_secret_key` below. `decode_responses=True` since the
    # adapter reads the key's value as a JSON *string* (`redis.asyncio.Redis.get` would
    # otherwise return `bytes`).
    if settings.redis.url:
        redis_client = Redis.from_url(settings.redis.url, decode_responses=True)
        container.bind_singleton(Redis, redis_client)
        container.bind_singleton(
            LatestPositionPort,
            RedisLatestPositionPort(
                redis_client,
                clock=container.resolve(Clock),
                id_generator=container.resolve(IdGenerator),
            ),
        )

    # TrackingApplicationService additionally needs the LatestPositionPort bound just above —
    # no concrete implementation existed before this phase (Phase 8.3 deliberately deferred
    # it), so this stays unbound without a reachable Redis, the same "fail loudly, don't fake
    # it" policy OutboxPublisher/BrokerPort already follow below.
    latest_position_port = container.try_resolve(LatestPositionPort)
    if latest_position_port is not None:
        container.bind_singleton(
            TrackingApplicationService,
            TrackingApplicationService(
                clock=container.resolve(Clock),
                id_generator=container.resolve(IdGenerator),
                latest_position_port=latest_position_port,
            ),
        )

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
        # BrokerPort — never bound in this phase (broker choice is still an open item), so
        # this stays unbound too until one is. Written so binding it later is a one-line
        # change, not a redesign.
        broker = container.try_resolve(BrokerPort)
        if broker is not None:
            container.bind_singleton(
                OutboxPublisher, SqlOutboxPublisher(session_factory, broker)
            )

    return container
