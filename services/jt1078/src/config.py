"""JT1078 relay configuration — env-var driven, mirroring `device-gateway`'s own `ServerConfig`
shape (`vendors/jt808/config.py`). `viewer_token_secret` is the one genuinely security-sensitive
setting: it must match whatever secret a future Business API `Jt1078RelayAdapter` mints viewer
tokens with (ADR-0022's own "secrets are environment variables, composition-root only" precedent).

**Corrected 2026-09-10 (P0 security finding).** This docstring previously claimed "a missing
secret fails loudly at startup rather than minting/accepting tokens under a guessable default" —
that was aspirational, not real: `from_env()` defaulted a missing/empty secret to `b""`, and
`session.viewer_token.mint_token`/`verify_token` perform no strength check of their own (HMAC-
SHA256 accepts an empty key without complaint), so a relay started with no
`JT1078_RELAY_VIEWER_TOKEN_SECRET` set would silently mint and accept viewer tokens signed with an
empty, universally-guessable key — anyone could forge a valid viewer token for any session without
ever holding the real secret. `validate_on_startup()` below now actually enforces the claim,
mirroring `raad.core.config.settings.Settings.validate_on_startup()`'s own prod-only placeholder/
strength checks exactly (same marker list intent, same 32-character floor) — this deployable has
no shared code with the backend (`.claude/rules/architecture.md` #2), so the check is duplicated
here rather than imported, not reused via a new cross-deployable dependency.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: Mirrors `raad.core.config.settings._PLACEHOLDER_SECRET_MARKERS` — kept as an independent
#: literal here (not imported) since this deployable shares no code with the backend. Matched
#: case-insensitively, substring, against the whole secret value.
_PLACEHOLDER_SECRET_MARKERS = (
    "dev-only-change-me",
    "change-me",
    "changeme",
    "ci-only-not-a-real-secret",
    "not-a-real-secret",
    "placeholder",
)

#: Mirrors `raad.core.config.settings._MIN_PROD_SECRET_LENGTH` — long enough that a hand-typed
#: value fails; `secrets.token_urlsafe(32)` clears this comfortably.
_MIN_PROD_SECRET_LENGTH = 32


def _is_placeholder_secret(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_SECRET_MARKERS)


@dataclass(frozen=True)
class RelayConfig:
    ingest_host: str = "0.0.0.0"
    ingest_port: int = 7910
    viewer_host: str = "0.0.0.0"
    viewer_port: int = 7911
    viewer_token_secret: bytes = b""
    #: `JT1078_RELAY_ENVIRONMENT` (default `"dev"`) — this deployable's own environment marker,
    #: distinct from the backend's `RAAD_ENVIRONMENT` (no shared `Settings` class exists between
    #: the two independent deployables). Only `"prod"` triggers `validate_on_startup()`'s checks,
    #: identical to `Settings.validate_on_startup`'s own `Environment.PROD`-only gate — dev/staging
    #: keep booting from the template default unchanged.
    environment: str = "dev"
    viewer_grace_seconds: float = 15.0
    absolute_idle_seconds: float = 60.0
    ingest_timeout_seconds: float = 30.0
    idle_sweep_interval_seconds: float = 5.0
    #: How long a viewer may be *continuously* backpressured — every chunk dropped, nothing
    #: delivered — before the relay closes it (2026-09-22). Production showed browsers that
    #: stopped consuming for 40 s to 4 minutes while the MDVR kept streaming over cellular, with
    #: nothing to end the session. `30` sits above the player's own 3 s freeze threshold and
    #: matches `ingest_timeout_seconds`, while the send queue holds only ~1-3 s, so reaching it
    #: means ~10-30 queue lengths of total failure. A viewer that receives *anything* resets its
    #: own clock, so ordinary jitter or a slow link never trips it. `<= 0` disables the check.
    #: Never applied to INTERCOM sessions - see `relay.py._on_session_created`.
    viewer_stuck_timeout_seconds: float = 30.0
    #: ADR-0026 §8. `50` cites `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md`
    #: §13.1's own "e.g., start 50 global" - the one concrete number an approved document names.
    #: `<= 0` means "no ceiling." No approved document names a per-org number, so that one
    #: defaults unconfigured (`0`, no additional restriction beyond the global ceiling).
    max_global_sessions: int = 50
    max_sessions_per_organization: int = 0
    #: The address a device dials to reach `ingest_port` — distinct from `ingest_host` (a bind
    #: address, typically "0.0.0.0", never a valid destination for a device to connect *to*).
    #: `SessionRequestServer` echoes this back to the Business API's `Jt1078RelayAdapter` as part
    #: of a session's own ingest coordinates, which the adapter embeds directly in the `0x9101`/
    #: `0x9201` signaling body it publishes (ADR-0024 §6 step 3). Falls back to `ingest_host`
    #: when unset, correct only for same-host dev/test use (a real deployment must set this to
    #: the VPS's real reachable IP/hostname).
    public_ingest_host: str = ""

    @classmethod
    def from_env(cls) -> "RelayConfig":
        secret = os.environ.get("JT1078_RELAY_VIEWER_TOKEN_SECRET", "")
        ingest_host = os.environ.get("JT1078_RELAY_INGEST_HOST", "0.0.0.0")
        return cls(
            ingest_host=ingest_host,
            ingest_port=int(os.environ.get("JT1078_RELAY_INGEST_PORT", "7910")),
            viewer_host=os.environ.get("JT1078_RELAY_VIEWER_HOST", "0.0.0.0"),
            viewer_port=int(os.environ.get("JT1078_RELAY_VIEWER_PORT", "7911")),
            viewer_token_secret=secret.encode("utf-8"),
            environment=os.environ.get("JT1078_RELAY_ENVIRONMENT", "dev").strip().lower(),
            absolute_idle_seconds=float(
                os.environ.get("JT1078_RELAY_ABSOLUTE_IDLE_SECONDS", "60")
            ),
            ingest_timeout_seconds=float(
                os.environ.get("JT1078_RELAY_INGEST_TIMEOUT_SECONDS", "30")
            ),
            # Was declared on this dataclass but read from no environment variable at all
            # (2026-09-02) — the one `RelayConfig` field `from_env` silently ignored, so the
            # sweep cadence could not be tuned without a code change. It directly sets the
            # granularity of every timeout above: a session that has exceeded
            # `ingest_timeout_seconds` is only actually failed on the next sweep, which is why
            # the observed browser-visible disconnect clustered at 30-35s rather than exactly
            # 30s. Wiring it closes this codebase's own "docker-compose.yml must wire every
            # value `from_env()` reads" rule (CLAUDE.md, Permanent Engineering Lessons).
            idle_sweep_interval_seconds=float(
                os.environ.get("JT1078_RELAY_IDLE_SWEEP_INTERVAL_SECONDS", "5")
            ),
            viewer_grace_seconds=float(
                os.environ.get("JT1078_RELAY_VIEWER_GRACE_SECONDS", "15")
            ),
            viewer_stuck_timeout_seconds=float(
                os.environ.get("JT1078_RELAY_VIEWER_STUCK_TIMEOUT_SECONDS", "30")
            ),
            max_global_sessions=int(
                os.environ.get("JT1078_RELAY_MAX_GLOBAL_SESSIONS", "50")
            ),
            max_sessions_per_organization=int(
                os.environ.get("JT1078_RELAY_MAX_SESSIONS_PER_ORGANIZATION", "0")
            ),
            public_ingest_host=os.environ.get(
                "JT1078_RELAY_PUBLIC_INGEST_HOST", ingest_host
            ),
        )

    @property
    def effective_public_ingest_host(self) -> str:
        return self.public_ingest_host or self.ingest_host

    def validate_on_startup(self) -> None:
        """Fail-fast check that must hold before the relay is allowed to accept a single
        connection — the P0 fix this docstring's own class-level comment describes.

        **Prod-only**, mirroring `Settings.validate_on_startup`'s exact `environment != "prod"`
        early return: `docker-compose.yml`'s dev default (`JT1078_RELAY_VIEWER_TOKEN_SECRET`
        unset, `JT1078_RELAY_ENVIRONMENT` unset) keeps booting unchanged, since local dev/CI has
        no real viewer to protect and the whole point of a template default is that it stays
        usable without a deployment-specific secret.
        """
        if self.environment != "prod":
            return

        secret_text = self.viewer_token_secret.decode("utf-8", errors="replace")

        if not secret_text or not secret_text.strip():
            raise ValueError(
                "Refusing to start in production with an unsafe JT1078 viewer token secret:\n"
                "  - JT1078_RELAY_VIEWER_TOKEN_SECRET must be set to a real, non-empty value"
            )
        if _is_placeholder_secret(secret_text):
            raise ValueError(
                "Refusing to start in production with an unsafe JT1078 viewer token secret:\n"
                "  - JT1078_RELAY_VIEWER_TOKEN_SECRET is still a development placeholder - "
                'generate a real value: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        if len(secret_text) < _MIN_PROD_SECRET_LENGTH:
            raise ValueError(
                "Refusing to start in production with an unsafe JT1078 viewer token secret:\n"
                f"  - JT1078_RELAY_VIEWER_TOKEN_SECRET is shorter than {_MIN_PROD_SECRET_LENGTH} "
                "characters - too short to be a safe HMAC signing key"
            )
