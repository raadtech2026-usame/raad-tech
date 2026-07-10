"""Composition-root wiring (Backend LLD §9.2).

Binds the interfaces that have a concrete implementation *today*. Module-specific ports
(`UnitOfWork` -> `SqlAlchemyUnitOfWork`, `PushSenderPort` -> `FcmPushSender`,
`PaymentProviderPort` -> `EvcPlusPaymentAdapter`, `DeviceCommandPort` -> `DeviceCommandClient`,
`VideoSignalingPort` -> `VideoSignalingClient`, `IdGenerator`) are bound here once their owning
module/infra is implemented in a later phase — deliberately absent now rather than stubbed,
so a missing binding fails loudly (`LookupError`) instead of silently resolving to a fake.
"""
from __future__ import annotations

from raad.core.config.settings import Settings
from raad.core.di.container import Container
from raad.core.time.clock import Clock, SystemClock


def build_container(settings: Settings) -> Container:
    container = Container()
    container.bind_singleton(Settings, settings)
    container.bind_singleton(Clock, SystemClock())
    return container
