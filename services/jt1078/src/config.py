"""JT1078 relay configuration — env-var driven, mirroring `device-gateway`'s own `ServerConfig`
shape (`vendors/jt808/config.py`). `viewer_token_secret` is the one genuinely security-sensitive
setting: it must match whatever secret a future Business API `Jt1078RelayAdapter` mints viewer
tokens with (ADR-0022's own "secrets are environment variables, composition-root only" precedent)
— there is no default in production; a missing secret fails loudly at startup rather than
minting/accepting tokens under a guessable default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RelayConfig:
    ingest_host: str = "0.0.0.0"
    ingest_port: int = 7910
    viewer_host: str = "0.0.0.0"
    viewer_port: int = 7911
    viewer_token_secret: bytes = b""
    viewer_grace_seconds: float = 15.0
    absolute_idle_seconds: float = 60.0
    ingest_timeout_seconds: float = 30.0
    idle_sweep_interval_seconds: float = 5.0
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
            viewer_grace_seconds=float(os.environ.get("JT1078_RELAY_VIEWER_GRACE_SECONDS", "15")),
            absolute_idle_seconds=float(
                os.environ.get("JT1078_RELAY_ABSOLUTE_IDLE_SECONDS", "60")
            ),
            ingest_timeout_seconds=float(
                os.environ.get("JT1078_RELAY_INGEST_TIMEOUT_SECONDS", "30")
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
