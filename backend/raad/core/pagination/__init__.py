"""Pagination, filtering, and sorting primitives (API Contracts §7/§8; Backend LLD §16.2).

Framework-free — no FastAPI, no SQLAlchemy (`core/db/repository.py`'s `SqlAlchemyRepositoryBase`
is the infra-layer consumer; `interfaces/http/pagination.py` is the FastAPI-facing one). This is
the module `core/db/repository.py`'s own `Page`/`Specification` stubs were left waiting for
("finalized alongside `core/pagination` — not implemented in this phase").

**Two pagination modes, per §7 verbatim:**
- **Offset** (`?page&page_size`) — "offered for admin tables where total counts matter." Used for
  every plain resource list (organizations, vehicles, students, ...).
- **Cursor** (`?limit&cursor`) — "stable under inserts, efficient on time-ordered data like
  positions/notifications." Used only for `GET /tracking/trips/{id}/positions` and
  `GET /notifications` — the two routes §4.4/§4.6 explicitly mark "(paginated)" with that framing
  in mind. Not built as a fully generic "any field" cursor system: both call sites paginate over a
  single, fixed, already-indexed `(timestamp, id)` keyset (`event_time` / `created_at`), so the
  cursor only ever needs to encode that one pair — building more than that would be inventing
  generality no documented resource asks for.

**Filtering/sorting (§8):** `filter[field]=value` (implicit `eq`) or `filter[field][op]=value`
(`gte`/`lte`/`gt`/`lt`/`in` — the only operators the doc's own examples name); `sort=field`
(ascending) / `sort=-field` (descending), comma-separated for multiple keys. Both are parsed here
from plain strings/dicts (query-string shape only, no `Request` dependency) and applied against a
**per-resource whitelist** at the repository layer (`core/db/repository.py`) — never an arbitrary
column name, per §8's own "Allowed fields are whitelisted per resource" requirement.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from raad.core.errors.exceptions import ValidationError

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
DEFAULT_LIMIT = 25
MAX_LIMIT = 100

FilterOp = Literal["eq", "gte", "lte", "gt", "lt", "in"]
_VALID_OPS: frozenset[str] = frozenset({"eq", "gte", "lte", "gt", "lt", "in"})

_FILTER_KEY_PATTERN = re.compile(r"^filter\[([a-zA-Z0-9_]+)\](?:\[([a-zA-Z0-9_]+)\])?$")


@dataclass(frozen=True)
class OffsetPageRequest:
    """`?page=1&page_size=25` (§7). 1-indexed, matching the documented example verbatim."""

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValidationError(
                "page must be >= 1.", details={"field": "page", "value": self.page}
            )
        if not (1 <= self.page_size <= MAX_PAGE_SIZE):
            raise ValidationError(
                f"page_size must be between 1 and {MAX_PAGE_SIZE}.",
                details={"field": "page_size", "value": self.page_size},
            )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


@dataclass(frozen=True)
class CursorPageRequest:
    """`?limit=50&cursor=<opaque>` (§7). `cursor=None` means "first page."""

    limit: int = DEFAULT_LIMIT
    cursor: str | None = None

    def __post_init__(self) -> None:
        if not (1 <= self.limit <= MAX_LIMIT):
            raise ValidationError(
                f"limit must be between 1 and {MAX_LIMIT}.",
                details={"field": "limit", "value": self.limit},
            )


@dataclass(frozen=True)
class OffsetPage(Generic[T]):
    data: list[T]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class CursorPage(Generic[T]):
    data: list[T]
    limit: int
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True)
class SortSpec:
    field: str
    descending: bool = False


@dataclass(frozen=True)
class FilterCondition:
    field: str
    op: FilterOp
    value: str


def parse_sort(raw: str | None) -> list[SortSpec]:
    """`?sort=-scheduled_date,trip_type` -> `[SortSpec("scheduled_date", True),
    SortSpec("trip_type", False)]`. Whitelist checking happens at the repository layer, not
    here — this function only knows query-string shape, never which fields a given resource
    actually allows."""
    if not raw:
        return []
    specs: list[SortSpec] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token.startswith("-"):
            specs.append(SortSpec(field=token[1:], descending=True))
        else:
            specs.append(SortSpec(field=token, descending=False))
    return specs


def parse_filters(query_params: list[tuple[str, str]]) -> list[FilterCondition]:
    """`query_params` is the raw list of `(key, value)` pairs from the request's query string
    (e.g. `Request.query_params.multi_items()`) — a plain list, not a framework type, so this
    function has no FastAPI/Starlette dependency. Matches `filter[field]=value` (implicit `eq`)
    and `filter[field][op]=value` (explicit op, one of `gte`/`lte`/`gt`/`lt`/`in`)."""
    conditions: list[FilterCondition] = []
    for key, value in query_params:
        match = _FILTER_KEY_PATTERN.match(key)
        if match is None:
            continue
        field_name, op = match.group(1), match.group(2) or "eq"
        if op not in _VALID_OPS:
            raise ValidationError(
                f"Unsupported filter operator: {op!r}.",
                details={"field": field_name, "op": op},
            )
        conditions.append(FilterCondition(field=field_name, op=op, value=value))  # type: ignore[arg-type]
    return conditions


def encode_cursor(sort_value: str, row_id: str) -> str:
    """Opaque per §7 ("cursor=<opaque>") — a client must never construct or parse one itself,
    only pass back exactly what it was given. `sort_value` is always pre-stringified by the
    caller (e.g. `datetime.isoformat()`) so this function stays type-agnostic."""
    payload = json.dumps([sort_value, row_id]).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        payload = base64.urlsafe_b64decode(cursor.encode("ascii"))
        sort_value, row_id = json.loads(payload)
        return str(sort_value), str(row_id)
    except Exception as exc:
        raise ValidationError(
            "Invalid or corrupted cursor.", details={"field": "cursor"}
        ) from exc


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "FilterOp",
    "OffsetPageRequest",
    "CursorPageRequest",
    "OffsetPage",
    "CursorPage",
    "SortSpec",
    "FilterCondition",
    "parse_sort",
    "parse_filters",
    "encode_cursor",
    "decode_cursor",
]
