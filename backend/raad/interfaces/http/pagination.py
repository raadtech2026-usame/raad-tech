"""FastAPI-facing pagination envelope schemas (API Contracts §7). `core.pagination` holds the
framework-free request/result dataclasses every repository/application-service layer works with;
this module is the one place they get projected onto Pydantic response models for the OpenAPI
schema, and onto the wire-shape a router actually returns — `{"data": [...], "page": {...}}`,
verbatim for both the offset and cursor variants.
"""

from __future__ import annotations

from typing import Callable, Generic, TypeVar

from pydantic import BaseModel

from raad.core.pagination import CursorPage, OffsetPage

T = TypeVar("T", bound=BaseModel)
TSource = TypeVar("TSource")


class OffsetPageMeta(BaseModel):
    total: int
    page: int
    page_size: int


class CursorPageMeta(BaseModel):
    limit: int
    next_cursor: str | None
    has_more: bool


class OffsetPageResponse(BaseModel, Generic[T]):
    data: list[T]
    page: OffsetPageMeta


class CursorPageResponse(BaseModel, Generic[T]):
    data: list[T]
    page: CursorPageMeta


def to_offset_page_response(
    page: OffsetPage[TSource], mapper: Callable[[TSource], T]
) -> OffsetPageResponse[T]:
    return OffsetPageResponse(
        data=[mapper(item) for item in page.data],
        page=OffsetPageMeta(total=page.total, page=page.page, page_size=page.page_size),
    )


def to_cursor_page_response(
    page: CursorPage[TSource], mapper: Callable[[TSource], T]
) -> CursorPageResponse[T]:
    return CursorPageResponse(
        data=[mapper(item) for item in page.data],
        page=CursorPageMeta(
            limit=page.limit, next_cursor=page.next_cursor, has_more=page.has_more
        ),
    )


__all__ = [
    "OffsetPageMeta",
    "CursorPageMeta",
    "OffsetPageResponse",
    "CursorPageResponse",
    "to_offset_page_response",
    "to_cursor_page_response",
]
