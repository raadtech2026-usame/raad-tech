"""LSZ MDVR server configuration — mirrors `src.config.ServerConfig` exactly, with its own
`MDVR_`-prefixed environment variables and its own default port (`7809`, distinct from JT/T 808's
`7808` default) so both protocol stacks could, in principle, run side by side against the same
physical fleet during a transition, rather than one silently shadowing the other's port.
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
class MdvrServerConfig:
    host: str = "0.0.0.0"
    port: int = 7809
    read_chunk_size: int = 4096
    max_frame_size: int = 8192
    idle_timeout_seconds: float = 90.0
    sweep_interval_seconds: float = 15.0
    device_session_timeout_seconds: float = 120.0
    device_session_sweep_interval_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> "MdvrServerConfig":
        return cls(
            host=os.environ.get("MDVR_HOST", cls.host),
            port=_env_int("MDVR_PORT", cls.port),
            read_chunk_size=_env_int("MDVR_READ_CHUNK_SIZE", cls.read_chunk_size),
            max_frame_size=_env_int("MDVR_MAX_FRAME_SIZE", cls.max_frame_size),
            idle_timeout_seconds=_env_float(
                "MDVR_IDLE_TIMEOUT_SECONDS", cls.idle_timeout_seconds
            ),
            sweep_interval_seconds=_env_float(
                "MDVR_SWEEP_INTERVAL_SECONDS", cls.sweep_interval_seconds
            ),
            device_session_timeout_seconds=_env_float(
                "MDVR_DEVICE_SESSION_TIMEOUT_SECONDS",
                cls.device_session_timeout_seconds,
            ),
            device_session_sweep_interval_seconds=_env_float(
                "MDVR_DEVICE_SESSION_SWEEP_INTERVAL_SECONDS",
                cls.device_session_sweep_interval_seconds,
            ),
        )
