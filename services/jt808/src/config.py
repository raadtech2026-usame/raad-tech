"""JT808 TCP transport service configuration (Phase 9.1 — Transport Layer only).

Stdlib-only — no `pydantic-settings` (that's an approved *Business API* dependency, Phase 4.2;
this is a separate deployable with its own, currently empty, dependency list). Values are read
from environment variables with documented defaults suitable for local development.

Transport-layer tuning only: no protocol/business configuration (message-size limits tied to
JT808 body semantics, vendor allow-lists, device auth keys, etc. belong to later phases).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value else default


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 7808
    read_chunk_size: int = 4096
    max_frame_size: int = (
        8192  # ceiling against unbounded buffering from a bad/hostile peer
    )
    idle_timeout_seconds: float = (
        90.0  # heartbeat-timeout infrastructure (framework only)
    )
    sweep_interval_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> "ServerConfig":
        return cls(
            host=os.environ.get("JT808_HOST", cls.host),
            port=_env_int("JT808_PORT", cls.port),
            read_chunk_size=_env_int("JT808_READ_CHUNK_SIZE", cls.read_chunk_size),
            max_frame_size=_env_int("JT808_MAX_FRAME_SIZE", cls.max_frame_size),
            idle_timeout_seconds=_env_float(
                "JT808_IDLE_TIMEOUT_SECONDS", cls.idle_timeout_seconds
            ),
            sweep_interval_seconds=_env_float(
                "JT808_SWEEP_INTERVAL_SECONDS", cls.sweep_interval_seconds
            ),
        )
