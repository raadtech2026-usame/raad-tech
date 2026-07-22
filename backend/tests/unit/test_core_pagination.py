"""Unit tests for `core.pagination`'s framework-free primitives (API Contracts §7/§8).
Stdlib `unittest`, no DB/FastAPI — pure parsing/encoding logic. Live-SQL behavior (actual
filtering/sorting/pagination against a real table) is covered separately by
`tests/integration/test_repository_pagination.py`.
"""

from __future__ import annotations

import unittest

from raad.core.errors.exceptions import ValidationError
from raad.core.pagination import (
    CursorPageRequest,
    FilterCondition,
    OffsetPageRequest,
    decode_cursor,
    encode_cursor,
    parse_filters,
    parse_sort,
)


class OffsetPageRequestTests(unittest.TestCase):
    def test_defaults(self) -> None:
        request = OffsetPageRequest()
        self.assertEqual(request.page, 1)
        self.assertEqual(request.page_size, 25)
        self.assertEqual(request.offset, 0)

    def test_offset_is_zero_indexed_from_one_indexed_page(self) -> None:
        request = OffsetPageRequest(page=3, page_size=10)
        self.assertEqual(request.offset, 20)

    def test_page_below_one_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            OffsetPageRequest(page=0)

    def test_page_size_above_max_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            OffsetPageRequest(page_size=101)

    def test_page_size_below_one_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            OffsetPageRequest(page_size=0)


class CursorPageRequestTests(unittest.TestCase):
    def test_defaults(self) -> None:
        request = CursorPageRequest()
        self.assertEqual(request.limit, 25)
        self.assertIsNone(request.cursor)

    def test_limit_above_max_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CursorPageRequest(limit=101)


class ParseSortTests(unittest.TestCase):
    def test_none_returns_empty_list(self) -> None:
        self.assertEqual(parse_sort(None), [])

    def test_empty_string_returns_empty_list(self) -> None:
        self.assertEqual(parse_sort(""), [])

    def test_single_ascending_field(self) -> None:
        specs = parse_sort("name")
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].field, "name")
        self.assertFalse(specs[0].descending)

    def test_single_descending_field(self) -> None:
        specs = parse_sort("-created_at")
        self.assertEqual(specs[0].field, "created_at")
        self.assertTrue(specs[0].descending)

    def test_multiple_comma_separated_fields(self) -> None:
        specs = parse_sort("-scheduled_date,trip_type")
        self.assertEqual(
            [(s.field, s.descending) for s in specs],
            [("scheduled_date", True), ("trip_type", False)],
        )


class ParseFiltersTests(unittest.TestCase):
    def test_implicit_eq_operator(self) -> None:
        conditions = parse_filters([("filter[status]", "active")])
        self.assertEqual(
            conditions, [FilterCondition(field="status", op="eq", value="active")]
        )

    def test_explicit_operator(self) -> None:
        conditions = parse_filters([("filter[created_at][gte]", "2026-07-01")])
        self.assertEqual(
            conditions,
            [FilterCondition(field="created_at", op="gte", value="2026-07-01")],
        )

    def test_in_operator_with_comma_separated_value(self) -> None:
        conditions = parse_filters([("filter[trip_type][in]", "morning,afternoon")])
        self.assertEqual(conditions[0].op, "in")
        self.assertEqual(conditions[0].value, "morning,afternoon")

    def test_unsupported_operator_raises_validation_error(self) -> None:
        with self.assertRaises(ValidationError):
            parse_filters([("filter[status][unsupported]", "active")])

    def test_non_filter_keys_are_ignored(self) -> None:
        conditions = parse_filters([("page", "1"), ("sort", "-name")])
        self.assertEqual(conditions, [])


class CursorCodecTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        cursor = encode_cursor("2026-07-21T10:00:00+00:00", "01J8Z3K9G6X8YV5T4N2R7QW3ME")
        sort_value, row_id = decode_cursor(cursor)
        self.assertEqual(sort_value, "2026-07-21T10:00:00+00:00")
        self.assertEqual(row_id, "01J8Z3K9G6X8YV5T4N2R7QW3ME")

    def test_cursor_is_opaque_base64(self) -> None:
        cursor = encode_cursor("value", "id")
        self.assertNotIn("value", cursor)
        self.assertNotIn("id", cursor)

    def test_decode_invalid_cursor_raises_validation_error(self) -> None:
        with self.assertRaises(ValidationError):
            decode_cursor("not-a-valid-cursor!!!")


if __name__ == "__main__":
    unittest.main()
