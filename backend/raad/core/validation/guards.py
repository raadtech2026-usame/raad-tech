"""Shared validation primitives (Backend LLD §15).

Generic, business-rule-free helpers used across layers. Transport validation (Pydantic
schemas) and domain invariants (aggregate/value-object guards, policies) each carry their own
specific rules elsewhere (§15.1) — this module only provides the reusable mechanics.
"""
from __future__ import annotations

from abc import ABC
from typing import TypeVar

from raad.core.errors.exceptions import ValidationError

T = TypeVar("T")


def ensure(condition: bool, message: str, *, details: object | None = None) -> None:
    """Raises ValidationError if `condition` is false. Generic guard clause used by callers
    that need a precondition check without hand-rolling an if/raise."""
    if not condition:
        raise ValidationError(message, details=details)


def guard_not_none(value: T | None, *, field: str) -> T:
    if value is None:
        raise ValidationError(f"{field} is required", details={"field": field})
    return value


class SelfValidating(ABC):
    """Marker base for Value Objects that validate their own invariants on construction
    (§15.2) — e.g. a future `Msisdn`, `GeoPoint`, `Radius`. No concrete value objects are
    defined in this phase; this is the shared contract they will implement against."""
