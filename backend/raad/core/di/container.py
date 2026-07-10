"""Composition root registry (Backend LLD §9.1).

`Container` is a minimal bind/resolve registry — the single place concrete implementations
are bound to interfaces. Domain and application code never reference concrete classes; they
receive interfaces resolved through this container (or, at the HTTP edge, through FastAPI
`Depends`, which reads from `app.state.container`).
"""
from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


class Container:
    def __init__(self) -> None:
        self._singletons: dict[type, object] = {}
        self._factories: dict[type, Callable[[], object]] = {}

    def bind_singleton(self, interface: type[T], instance: T) -> None:
        self._singletons[interface] = instance

    def bind_factory(self, interface: type[T], factory: Callable[[], T]) -> None:
        """Registers a factory invoked on every `resolve` call — used for request-scoped
        objects (e.g. a future `UnitOfWork` factory)."""
        self._factories[interface] = factory

    def resolve(self, interface: type[T]) -> T:
        if interface in self._singletons:
            return self._singletons[interface]  # type: ignore[return-value]
        if interface in self._factories:
            return self._factories[interface]()  # type: ignore[return-value]
        raise LookupError(f"No binding registered for {interface!r}")
