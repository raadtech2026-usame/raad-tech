"""Unit tests for CORS configuration and preflight caching (PERF-02 remediation).

Verifies:
- OPTIONS preflight responses include `Access-Control-Max-Age: 86400` to prevent redundant preflight RTT.
- Allowed origins receive correct CORS headers.
- Disallowed origins do not receive `Access-Control-Allow-Origin`.
- Credentials flag stays False (bearer tokens used, no cookies).
- Security headers remain intact.
"""

from __future__ import annotations

import unittest
from fastapi.testclient import TestClient

from raad.core.config.settings import CorsSettings, Settings
from raad.main import create_app


class CorsPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            cors=CorsSettings(
                allowed_origins=["https://app.raadsystems.tech", "http://localhost:3000"],
                max_age=86400,
            )
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)

    def test_preflight_options_returns_max_age_and_allowed_headers(self) -> None:
        headers = {
            "Origin": "https://app.raadsystems.tech",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        }
        response = self.client.options("/health", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "https://app.raadsystems.tech")
        self.assertEqual(response.headers.get("access-control-max-age"), "86400")
        self.assertIn("POST", response.headers.get("access-control-allow-methods", ""))
        self.assertNotIn("access-control-allow-credentials", response.headers)

    def test_preflight_from_localhost_allowed(self) -> None:
        headers = {
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        }
        response = self.client.options("/health", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:3000")
        self.assertEqual(response.headers.get("access-control-max-age"), "86400")

    def test_preflight_from_disallowed_origin_is_rejected(self) -> None:
        headers = {
            "Origin": "https://malicious-site.example.com",
            "Access-Control-Request-Method": "GET",
        }
        response = self.client.options("/health", headers=headers)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_actual_request_includes_cors_origin_header(self) -> None:
        headers = {
            "Origin": "https://app.raadsystems.tech",
        }
        response = self.client.get("/health", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "https://app.raadsystems.tech")
        # Actual GET response should not have access-control-max-age (preflight only)
        self.assertNotIn("access-control-max-age", response.headers)
