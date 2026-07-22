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


class RedisSettings(BaseModel):
    url: str = ""


class BrokerSettings(BaseModel):
    url: str = ""


class PasswordPolicySettings(BaseModel):
    """Minimum password strength rules (Backend LLD §17 `security`). Enforced by
    `core.security.password_policy.PasswordPolicy` — kept configurable rather than hardcoded
    so it can be tightened without a code change."""

    min_length: int = 10
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_digit: bool = True
    require_special: bool = True


class AuthSettings(BaseModel):
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 1_209_600
    password_policy: PasswordPolicySettings = PasswordPolicySettings()


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
    report_worker_interval_seconds: float = 10.0
    vehicle_position_retention_days: int = 90  # `.claude/rules/database.md` #6's own
    # "recommend 90 days, configurable"
    vehicle_position_retention_job_interval_seconds: float = 3600.0
    subscription_sweep_interval_seconds: float = 3600.0
    payment_reconciliation_timeout_minutes: int = 30
    payment_reconciliation_interval_seconds: float = 600.0
    # WebSocket phase: the two realtime fan-out consumers (interfaces/http/realtime.py) are
    # themselves core.workers.base.Worker instances, hosted in-process with the API (Backend
    # LLD §11.1) rather than the separate workers/bootstrap.py process — same tick-interval
    # tuning shape as every other worker above.
    realtime_fanout_interval_seconds: float = 1.0


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
        (Backend LLD §12.1). Kept intentionally minimal at this phase — real secret/
        connectivity checks are added as their owning subsystems (DB, broker, FCM, payment)
        are wired in later phases."""
        if self.environment is Environment.PROD and not self.auth.jwt_secret_key:
            raise ValueError("auth.jwt_secret_key must be set when environment=prod")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Cached so environment parsing happens once."""
    return Settings()
