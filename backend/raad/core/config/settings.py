"""Typed application settings (Backend LLD §12).

A single `Settings` object, validated at startup (fail fast on misconfiguration). Layering
(LLD §12.1): in-code defaults -> `.env` file (local/dev convenience, never committed) ->
environment variables / mounted secret store (highest precedence). No secrets are hardcoded
here. Sub-config groups match the LLD §12.3 contract skeleton exactly.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class DbSettings(BaseModel):
    url: str = ""
    pool_size: int = 5


class RedisConnectionSettings(BaseModel):
    """Priority 1 Item 4 (`PROJECT_STATUS.md`, Redis production hardening) — connection-level
    resilience shared by `RedisSettings`/`BrokerSettings` below. `redis.asyncio.Redis.from_url`
    was previously called with no timeout kwargs at all (`core/di/bootstrap.py`) — redis-py's
    own library defaults (5s connect/socket timeout, no periodic health check) are reasonable
    but were undocumented and unconfigurable here; explicit, slightly tighter defaults suit this
    codebase's request-scoped hot paths (e.g. `RateLimitMiddleware`, Priority 1 Item 3, must fail
    fast rather than hang a login request). `health_check_interval` proactively pings idle pooled
    connections — these clients are DI singletons living for the whole process lifetime, so a
    connection gone stale (a mid-air network blip that doesn't raise immediately) would otherwise
    only surface as a failure on the next real command."""

    socket_connect_timeout_seconds: float = 3.0
    socket_timeout_seconds: float = 3.0
    health_check_interval_seconds: int = 30


class RedisSettings(RedisConnectionSettings):
    url: str = ""


class BrokerSettings(RedisConnectionSettings):
    url: str = ""
    #: **Default 0 = trimming DISABLED. Do not turn this on without first making the device
    #: registry durable.** Live-proven regression, 2026-09-02: this was briefly defaulted to
    #: 100_000 to bound Redis memory, and trimming immediately evicted the oldest entries —
    #: which included the `DeviceRegistered`/`DeviceActivated`/`DeviceAssignedToVehicle` events
    #: from 2026-08-18 that `services/device-gateway`'s `DeviceRegistryProjection` rebuilds
    #: itself from on every cold start (`RedisDeviceRegistryConsumer.replay_from_start`, a full
    #: `XRANGE` over the whole stream). The projection came back empty and the physical MDVR
    #: could no longer authenticate at all (`authentication_failed` on every `0x0102`).
    #: `raad:events` is therefore not a transient bus: for the device registry it is the durable
    #: log of record, with unbounded retention. Any finite cap eventually evicts those founding
    #: events, because they are by definition the oldest and position reports are high-volume —
    #: so no "safe" non-zero value exists under the current design. Bounding Redis memory needs
    #: the projection to stop depending on infinite history (persist it, or compact registry
    #: events onto their own keys) — a design change, not a tuning knob.
    stream_max_length: int = 0


class PasswordPolicySettings(BaseModel):
    """Minimum password strength rules (Backend LLD §17 `security`). Enforced by
    `core.security.password_policy.PasswordPolicy` — kept configurable rather than hardcoded
    so it can be tightened without a code change."""

    min_length: int = 10
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_digit: bool = True
    require_special: bool = True


class LockoutSettings(BaseModel):
    """Account lockout after repeated failed logins (Priority 1 Item 3, `PROJECT_STATUS.md`).
    Enforced by `User.record_failed_login`/`is_locked` (`modules.iam.domain.entities`) — kept
    configurable rather than hardcoded, the same reasoning `PasswordPolicySettings` above
    already applies. Defaults sit in the commonly-recommended range (OWASP names 3-10 attempts,
    a lockout on the order of minutes) rather than inventing untested numbers."""

    max_failed_attempts: int = 5
    lockout_duration_minutes: int = 15


class RateLimitSettings(BaseModel):
    """IP-based throttling on `/auth/login` (Priority 1 Item 3, `PROJECT_STATUS.md`), distinct
    from and complementary to `LockoutSettings` above: this limits *how fast* one source can
    attempt logins at all, regardless of which account(s) it targets, where lockout limits
    *how many wrong guesses* one specific account tolerates regardless of source. Enforced by
    `core.security.login_rate_limiter.LoginRateLimiter`, bound only when `RedisSettings.url` is
    configured — see that class's own docstring for the fail-open-and-log-once posture when it
    isn't."""

    max_attempts: int = 10
    window_seconds: int = 60


class AuthSettings(BaseModel):
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 1_209_600
    password_policy: PasswordPolicySettings = PasswordPolicySettings()
    lockout: LockoutSettings = LockoutSettings()
    rate_limit: RateLimitSettings = RateLimitSettings()


class FcmSettings(BaseModel):
    credentials_path: str = ""


class PaymentSettings(BaseModel):
    """Provider-agnostic seam (Phase 2 §20.1). `provider` selects the adapter bound in
    core/di; no provider-specific fields live outside `provider_credentials`."""

    provider: str = "evcplus"
    provider_credentials: dict[str, str] = {}


class MapSettings(BaseModel):
    """Pluggable map provider seam (Phase 2 §8.2 / §11.8)."""

    provider: str = ""


class DevicePlaneSettings(BaseModel):
    """Signaling endpoints for the JT808/JT1078 seam (D6). The Business API never opens a
    device socket — these are the addresses of the separate device-plane services."""

    jt808_signaling_url: str = ""
    jt1078_signaling_url: str = ""


class CorsSettings(BaseModel):
    """Cross-origin access for the React web frontend (`.claude/rules/frontend.md`) — this API
    has no browser-facing origin of its own, so without this every cross-origin request from a
    dev or prod frontend is blocked by the browser regardless of a valid bearer token.
    `allowed_origins` defaults to the local React dev server only; add the deployed frontend's
    origin(s) via `RAAD_CORS__ALLOWED_ORIGINS` (a JSON array) once one exists. `allow_credentials`
    stays `False` — auth is a bearer token in the `Authorization` header (`.claude/rules/api.md`
    #3), never a cookie, so the browser's credentialed-request mode is not needed here."""

    allowed_origins: list[str] = ["http://localhost:3000"]


class WebSocketSettings(BaseModel):
    """`/ws/tracking`/`/ws/notifications` tuning (API Contracts §11.1). Its own sub-config
    group (LLD §12.1's "one sub-config group per concern"), separate from `WorkerSettings`
    below even though the realtime fan-out consumers are themselves `core.workers.base.Worker`
    instances — this group is protocol/connection tuning (how long to wait for the documented
    "first auth frame" before closing), not background-job-polling tuning."""

    auth_frame_timeout_seconds: float = 10.0


class ObservabilitySettings(BaseModel):
    log_level: str = "INFO"
    log_format: str = "json"


class FeatureFlags(BaseModel):
    """Gates dormant seams so they ship off by default (D2/D3 scope discipline)."""

    org_hierarchy_enabled: bool = False
    additional_notification_channels_enabled: bool = False


class WorkerSettings(BaseModel):
    """Background worker tuning (Backend LLD §11). The worker *runtime* (Celery vs arq) is
    still an open item (§20.1) — these intervals drive the runtime-agnostic polling loop in
    `core.workers.base.Worker` regardless of which runtime eventually hosts it, so nothing
    here commits to that choice."""

    outbox_relay_interval_seconds: float = 5.0
    outbox_relay_batch_size: int = 100
    scheduler_tick_interval_seconds: float = 60.0
    retry_max_attempts: int = 5
    retry_base_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 300.0
    # Backend Stabilization phase (ADR-0008) - scheduled-job tuning. Registered by
    # `interfaces/workers/bootstrap.py`, consumed by `tracking`/`billing`'s own new
    # `prune_position_history`/`sweep_expired_subscriptions`/`reconcile_expired_payments`
    # application-service methods.
    notification_worker_interval_seconds: float = 5.0
    # Raised from `RedisStreamsBrokerConsumer`'s own 10-message default (2026-09-02), measured
    # against the live bench stack. `NotificationWorker.run_once` performs exactly one
    # `XREADGROUP count=<this>` per tick, and this single `notification-worker` consumer group
    # carries *every* backend event processor - notifications, tracking positions, device
    # connectivity, and (ADR-0026 §7) the JT1078 relay's own VideoSessionActivated/Ended/Failed
    # lifecycle events. At 10 per 5s tick the whole pipeline was hard-capped at ~2 events/sec,
    # measured directly: `XINFO GROUPS raad:events` showed this group persistently 105-125
    # entries behind on a 299k-entry stream, and `video_sessions.started_at` landed ~50s after
    # the relay's own `ingest_connection_correlated` for the same session - i.e. the durable
    # session status a UI reads was systematically ~50s stale. Larger batches add no latency
    # when the stream is idle (`block_ms` still returns early with whatever is available); they
    # only raise the ceiling during a burst.
    notification_worker_batch_size: int = 200
    report_worker_interval_seconds: float = 10.0
    vehicle_position_retention_days: int = 90  # `.claude/rules/database.md` #6's own
    # "recommend 90 days, configurable"
    vehicle_position_retention_job_interval_seconds: float = 3600.0
    subscription_sweep_interval_seconds: float = 3600.0
    #: ADR-0039 §1 — how long an organization keeps working after its billing period ends with
    #: an unpaid invoice, before it is suspended. Seven days is a deliberate product choice, not
    #: a number any document supplies: RAAD's customers are schools whose users are tracking
    #: children on buses, so an abrupt cutoff the moment an invoice slips is the wrong default,
    #: while an unbounded grace window would make the whole lifecycle decorative. Configurable
    #: precisely because the right value is a business decision, not an engineering one.
    subscription_grace_period_days: int = 7
    payment_reconciliation_timeout_minutes: int = 30
    payment_reconciliation_interval_seconds: float = 600.0
    # WebSocket phase: the two realtime fan-out consumers (interfaces/http/realtime.py) are
    # themselves core.workers.base.Worker instances, hosted in-process with the API (Backend
    # LLD §11.1) rather than the separate workers/bootstrap.py process — same tick-interval
    # tuning shape as every other worker above.
    realtime_fanout_interval_seconds: float = 1.0
    # ADR-0037 — a defense-in-depth backstop, independent of whether the relay's own
    # VideoSessionActivated/Ended/Failed event ever successfully arrives and is consumed (the
    # live-found 2026-09-01 incident: a poisoned broker message wedged the event pipeline for
    # over an hour, leaving a REQUESTED intercom session permanently blocking every other
    # operator's own attempt to talk to that bus). 180s is deliberately well past the relay's
    # own worst-case internal timeout (ingest_timeout 30s + absolute_idle 60s, `services/jt1078/
    # src/session/session_manager.py`'s own defaults) - this job must never race the primary,
    # event-driven reconciliation path, only catch what it misses.
    intercom_reconciliation_interval_seconds: float = 60.0
    #: Audit finding B7 / ADR-0024 §16. The staleness threshold for ordinary live/playback
    #: sessions, deliberately far higher than the intercom one: a stuck intercom session blocks
    #: every other operator from that bus and must be cleared aggressively, while a legitimate
    #: live viewing session can genuinely run for a long time and failing one someone is
    #: actually watching would be worse than the stale row it prevents. Two hours is comfortably
    #: longer than any real viewing session observed on the bench, and short enough that stale
    #: rows cannot accumulate for weeks — as 16 of them did (oldest 2026-08-19) before this
    #: existed.
    video_stale_session_timeout_seconds: float = 7200.0
    intercom_stale_session_timeout_seconds: float = 180.0
    #: Camera/AV discovery retry (2026-09-17, amending ADR-0030's once-per-device request).
    #: `..._retry_after_seconds`: how long an unanswered `0x9003` waits before it may be sent
    #: again, on reconnect or by the sweep. `..._retry_interval_seconds`: how often the worker
    #: sweeps for online devices still waiting, so a device that stays connected is retried too.
    #: See `Device.is_av_attributes_discovery_due`.
    av_attributes_discovery_retry_after_seconds: float = 600.0
    av_attributes_discovery_retry_interval_seconds: float = 300.0


#: Audit finding B3. Substrings that mark a value as a development placeholder rather than a
#: real secret. Matched case-insensitively against the whole value, so it also catches a
#: placeholder embedded in a connection URL (`redis://:dev-only-change-me@redis:6379/1`).
#: Deliberately a small, explicit list rather than an entropy heuristic: a false positive here
#: blocks a real deployment, so it must only ever fire on values this repository itself ships.
_PLACEHOLDER_SECRET_MARKERS = (
    "dev-only-change-me",
    "change-me",
    "changeme",
    "ci-only-not-a-real-secret",
    "not-a-real-secret",
    "placeholder",
)

#: Long enough that a hand-typed value fails. `secrets.token_urlsafe(64)` produces ~86 chars, so
#: a genuinely generated key clears this comfortably.
_MIN_PROD_SECRET_LENGTH = 32


def _is_placeholder_secret(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_SECRET_MARKERS)


class Settings(BaseSettings):
    """Root settings object. Environment variables use the `RAAD_` prefix and `__` as the
    nested-field delimiter, e.g. `RAAD_DB__URL`, `RAAD_AUTH__JWT_SECRET_KEY`."""

    model_config = SettingsConfigDict(
        env_prefix="RAAD_",
        env_nested_delimiter="__",
        extra="ignore",
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
    )

    environment: Environment = Environment.DEV
    db: DbSettings = DbSettings()
    redis: RedisSettings = RedisSettings()
    broker: BrokerSettings = BrokerSettings()
    auth: AuthSettings = AuthSettings()
    fcm: FcmSettings = FcmSettings()
    payment: PaymentSettings = PaymentSettings()
    maps: MapSettings = MapSettings()
    device_plane: DevicePlaneSettings = DevicePlaneSettings()
    cors: CorsSettings = CorsSettings()
    websocket: WebSocketSettings = WebSocketSettings()
    observability: ObservabilitySettings = ObservabilitySettings()
    feature_flags: FeatureFlags = FeatureFlags()
    workers: WorkerSettings = WorkerSettings()

    def validate_on_startup(self) -> None:
        """Fail-fast checks that must hold before the app is allowed to serve traffic
        (Backend LLD §12.1).

        **Hardened per audit finding B3.** This method previously checked one thing — that
        `auth.jwt_secret_key` was non-empty when `environment=prod` — and `docker/.env.example`
        ships that key with the literal value `dev-only-change-me`. A non-empty placeholder
        satisfies a non-empty check, so an operator who copied the template verbatim and set
        `RAAD_ENVIRONMENT=prod` got a deployment that started cleanly while signing every JWT
        with a value published in this repository. The check existed and was worthless.

        Every rule below is **prod-only**: dev and staging keep booting from the template
        unchanged, which is the whole point of having placeholders. Each raises with the exact
        variable name, because a startup failure that doesn't say what to fix just becomes a
        deployment outage of a different kind.
        """
        if self.environment is not Environment.PROD:
            return

        problems: list[str] = []

        if not self.auth.jwt_secret_key:
            problems.append("RAAD_AUTH__JWT_SECRET_KEY must be set")
        elif _is_placeholder_secret(self.auth.jwt_secret_key):
            problems.append(
                "RAAD_AUTH__JWT_SECRET_KEY is still a development placeholder - generate a "
                'real value: python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        elif len(self.auth.jwt_secret_key) < _MIN_PROD_SECRET_LENGTH:
            problems.append(
                f"RAAD_AUTH__JWT_SECRET_KEY is shorter than {_MIN_PROD_SECRET_LENGTH} "
                "characters - too short to be a safe HMAC signing key"
            )

        # A localhost CORS origin in production is either a copy-paste of the dev template (so
        # the real dashboard's origin is missing and every browser request fails) or a genuine
        # attempt to allow a local origin against a production API. Both are wrong, and the
        # first fails in a way that looks like a frontend bug rather than a config one.
        localhost_origins = [
            origin
            for origin in self.cors.allowed_origins
            if "localhost" in origin or "127.0.0.1" in origin
        ]
        if localhost_origins:
            problems.append(
                "RAAD_CORS__ALLOWED_ORIGINS still contains development origins "
                f"({', '.join(localhost_origins)}) - set the deployed frontend's real origin"
            )
        if "*" in self.cors.allowed_origins:
            problems.append(
                'RAAD_CORS__ALLOWED_ORIGINS must not be "*" in production'
            )

        if self.db.url and _is_placeholder_secret(self.db.url):
            problems.append(
                "RAAD_DB__URL still contains a development placeholder password"
            )
        if self.redis.url and _is_placeholder_secret(self.redis.url):
            problems.append(
                "RAAD_REDIS__URL still contains a development placeholder password"
            )
        if self.broker.url and _is_placeholder_secret(self.broker.url):
            problems.append(
                "RAAD_BROKER__URL still contains a development placeholder password"
            )

        # Audit finding B2 is deliberately NOT enforced here, and that is the correct call.
        # An unbounded `raad:events` under `maxmemory-policy=noeviction` is a real risk, but
        # requiring `stream_max_length > 0` would mandate the exact configuration that caused a
        # live outage on 2026-09-02: trimming evicts the oldest entries, which are the device
        # registration events `DeviceRegistryProjection` rebuilds from on cold start, and the
        # physical MDVR stopped authenticating entirely. See `BrokerSettings.stream_max_length`
        # for the full account. No finite cap is safe until that projection stops depending on
        # infinite stream history — a design change, not a config value. Until then this is a
        # monitoring concern (Redis memory), not a startup assertion.

        if problems:
            raise ValueError(
                "Refusing to start in production with unsafe configuration:\n  - "
                + "\n  - ".join(problems)
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Cached so environment parsing happens once."""
    return Settings()
