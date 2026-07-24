"""`DeviceProtocolAdapter` — the common interface every vendor's own device-plane server
implements (device-gateway multi-vendor architecture, see `docs/architecture/adr/
0010-device-gateway-multi-vendor-architecture.md`). The gateway composition root
(`src/gateway.py`) depends only on this interface, never on a specific vendor's concrete class —
adding a new vendor under `vendors/<name>/` means implementing this ABC (and, internally, however
much of that vendor's own protocol/dispatcher/handlers stack it needs); nothing here or in
`src/gateway.py` changes as a result.

Deliberately minimal: `start`/`stop`/`bound_port`/`session_count`/`device_session_count` are the
only operations the gateway itself ever needs across *every* vendor. Each concrete adapter is
free to expose additional vendor-specific properties (e.g. `device_provisioning`, `event_
publisher`) beyond this interface for its own tests/introspection — those are accessed by name on
the concrete instance, not through this ABC, exactly the way `Jt808Server`/`MdvrServer` already
did before this interface existed.

**Not part of this interface:** `serve_forever()`. Each vendor's own server class keeps its own
`serve_forever()` for standalone single-adapter use (its own tests, or running that one adapter
in isolation) — but the multi-adapter `DeviceGateway` composition root calls `start()`/`stop()`
directly and owns its own single shared signal handler, rather than letting every adapter install
its own `SIGINT`/`SIGTERM` handler (which would conflict once more than one adapter is running in
the same process).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class DeviceProtocolAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """A short, stable identifier for this adapter (e.g. `"jt808"`, `"lsz"`) — used only for
        logging/introspection in the gateway composition root, never for dispatch logic."""
        raise NotImplementedError

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def bound_port(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def session_count(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def device_session_count(self) -> int:
        raise NotImplementedError
