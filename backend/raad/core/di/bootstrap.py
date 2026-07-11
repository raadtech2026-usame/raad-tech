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

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from raad.core.config.settings import Settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from raad.core.di.container import Container
from raad.core.events.outbox import OutboxWriter, SqlOutboxPublisher
from raad.core.events.ports import BrokerPort, OutboxPublisher
from raad.core.events.processor import EventProcessorRegistry
from raad.core.ids.generator import IdGenerator, UlidGenerator
from raad.core.security.password_hashing import PasswordHasher, Pbkdf2PasswordHasher
from raad.core.security.tokens import JwtTokenService, TokenService
from raad.core.time.clock import Clock, SystemClock
from raad.core.workers.idempotency import IdempotencyStore, InMemoryIdempotencyStore
from raad.core.workers.retry import ExponentialBackoffRetryPolicy, RetryPolicy
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.infra.repositories import SqlAlchemyIamUnitOfWork


def build_container(settings: Settings) -> Container:
    container = Container()
    container.bind_singleton(Settings, settings)
    container.bind_singleton(Clock, SystemClock())
    container.bind_singleton(PasswordHasher, Pbkdf2PasswordHasher())
    container.bind_singleton(IdGenerator, UlidGenerator())
    container.bind_singleton(OutboxWriter, OutboxWriter())
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

    # Engine/session factory/UnitOfWork need a configured DB URL. Left unbound without one
    # (dev/CI with no MySQL reachable yet) — same policy as TokenService above — rather than
    # constructing an AsyncEngine against an empty connection string.
    if settings.db.url:
        engine: AsyncEngine = build_engine(settings.db)
        session_factory: async_sessionmaker[AsyncSession] = build_session_factory(engine)
        container.bind_singleton(AsyncEngine, engine)
        container.bind_singleton(async_sessionmaker, session_factory)
        container.bind_factory(
            UnitOfWork,
            lambda: SqlAlchemyUnitOfWork(session_factory, container.resolve(OutboxWriter)),
        )
        container.bind_factory(
            IamUnitOfWork,
            lambda: SqlAlchemyIamUnitOfWork(
                session_factory, container.resolve(OutboxWriter)
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
