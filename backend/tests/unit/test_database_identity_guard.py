"""Unit tests for the pure logic behind `tests/integration/test_database_identity_guard.py`.

The guard itself needs a live PostgreSQL connection, so it is skipped wherever no database is
configured — including most unit-test runs. Its parsing and configuration rules are pure
functions, though, and those are what must not silently break: a guard that stops guarding is
worse than no guard, because it reads as protection while providing none.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from tests.integration.test_database_identity_guard import (
    DEFAULT_EXPECTED_MAJOR,
    describe_mismatch,
    expected_data_directory,
    expected_major,
    parse_major,
)


class ParseMajorTests(unittest.TestCase):
    def test_extracts_the_major_version_from_a_real_docker_version_string(self) -> None:
        version = (
            "PostgreSQL 16.15 on x86_64-pc-linux-musl, compiled by gcc (Alpine 13.2.1) 13.2.1, 64-bit"
        )
        self.assertEqual(parse_major(version), "16")

    def test_extracts_the_major_version_from_a_real_native_windows_version_string(self) -> None:
        version = "PostgreSQL 17.10 on x86_64-windows, compiled by msvc-19.44.35227, 64-bit"
        self.assertEqual(parse_major(version), "17")

    def test_the_two_real_servers_are_distinguishable(self) -> None:
        """The exact confusion this guard exists to catch."""
        docker = "PostgreSQL 16.15 on x86_64-pc-linux-musl, compiled by gcc, 64-bit"
        native = "PostgreSQL 17.10 on x86_64-windows, compiled by msvc-19.44.35227, 64-bit"
        self.assertNotEqual(parse_major(docker), parse_major(native))

    def test_unrecognised_version_string_returns_none_rather_than_raising(self) -> None:
        self.assertIsNone(parse_major("MySQL 8.0.36"))
        self.assertIsNone(parse_major(""))
        self.assertIsNone(parse_major("PostgreSQL"))


class ExpectedMajorTests(unittest.TestCase):
    def test_defaults_to_the_version_this_repository_targets(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(expected_major(), DEFAULT_EXPECTED_MAJOR)

    def test_default_matches_the_postgres_image_ci_and_compose_both_pin(self) -> None:
        """`postgres:16` in backend-pipeline.yml, `postgres:16-alpine` in docker-compose.yml."""
        self.assertEqual(DEFAULT_EXPECTED_MAJOR, "16")

    def test_can_be_overridden_for_a_deployment_on_another_major_version(self) -> None:
        with mock.patch.dict(os.environ, {"RAAD_TEST_DB_EXPECTED_MAJOR": "17"}, clear=True):
            self.assertEqual(expected_major(), "17")

    def test_can_be_disabled_explicitly(self) -> None:
        for disabling in ("", "any", "ANY", "*"):
            with mock.patch.dict(
                os.environ, {"RAAD_TEST_DB_EXPECTED_MAJOR": disabling}, clear=True
            ):
                self.assertIsNone(expected_major(), f"{disabling!r} should disable the check")

    def test_surrounding_whitespace_is_ignored(self) -> None:
        with mock.patch.dict(os.environ, {"RAAD_TEST_DB_EXPECTED_MAJOR": " 16 "}, clear=True):
            self.assertEqual(expected_major(), "16")


class ExpectedDataDirectoryTests(unittest.TestCase):
    def test_unset_by_default_so_ci_and_windows_both_pass(self) -> None:
        """Hardcoding either OS's path would break the other — see the guard's module docstring."""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(expected_data_directory())

    def test_returns_an_explicit_expectation_when_configured(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"RAAD_TEST_DB_EXPECTED_DATA_DIRECTORY": "/var/lib/postgresql/data"},
            clear=True,
        ):
            self.assertEqual(expected_data_directory(), "/var/lib/postgresql/data")


class DescribeMismatchTests(unittest.TestCase):
    def test_names_both_servers_so_the_failure_is_actionable(self) -> None:
        message = describe_mismatch(
            expected="16",
            actual_version="PostgreSQL 17.10 on x86_64-windows, compiled by msvc, 64-bit",
            data_directory="C:/Program Files/PostgreSQL/17/data",
        )
        self.assertIn("16", message)
        self.assertIn("17.10", message)
        self.assertIn("C:/Program Files/PostgreSQL/17/data", message)
        self.assertIn("RAAD_DB__URL", message)
        self.assertIn("RAAD_TEST_DB_EXPECTED_MAJOR", message)

    def test_mentions_the_second_listener_cause_a_reader_would_otherwise_miss(self) -> None:
        message = describe_mismatch(
            expected="16", actual_version="PostgreSQL 17.10 on x86_64-windows", data_directory="C:/x"
        )
        self.assertIn("another PostgreSQL", message)


if __name__ == "__main__":
    unittest.main()
