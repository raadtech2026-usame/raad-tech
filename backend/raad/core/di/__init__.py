"""Composition root: container + startup wiring (Backend LLD §9)."""

from raad.core.di.bootstrap import build_container
from raad.core.di.container import Container

__all__ = ["Container", "build_container"]
