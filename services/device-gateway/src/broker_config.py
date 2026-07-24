"""Device-gateway broker configuration (Redis integration). A distinct, independently-configured
env var (`DEVICE_GATEWAY_BROKER_URL`, not the Business API's own `RAAD_BROKER__URL`) — this
deployable's own manifest/config stays independent of the Business API's, even though an MVP
deployment will typically point both at the same Redis instance (ADR-0008's own precedent for
`broker.url` vs `redis.url` being independently configurable settings that usually coincide).
Left unconfigured, `DeviceGateway` falls back to `LoggingEventPublisher` and the interim
allow-list provisioning ports — the same "fail loudly, don't fake it" policy every other
pending-infra port in the Business API already follows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BrokerConfig:
    url: str | None = None

    @classmethod
    def from_env(cls) -> "BrokerConfig":
        return cls(url=os.environ.get("DEVICE_GATEWAY_BROKER_URL") or None)
