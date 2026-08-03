"""Unit tests for `core.observability.metrics.MetricsRegistry` (Priority 1 Item 5,
`PROJECT_STATUS.md`, "minimum monitoring"). Stdlib `unittest` — no `pytest`.
"""

from __future__ import annotations

import unittest

from raad.core.observability.metrics import MetricsRegistry


class MetricsRegistryTests(unittest.TestCase):
    def test_render_with_no_data_still_has_help_and_type_lines(self) -> None:
        registry = MetricsRegistry()
        body = registry.render()
        self.assertIn("# HELP raad_http_requests_total", body)
        self.assertIn("# TYPE raad_http_requests_total counter", body)
        self.assertIn("# TYPE raad_dependency_up gauge", body)
        self.assertIn("raad_process_start_time_seconds", body)

    def test_increment_appears_in_rendered_output(self) -> None:
        registry = MetricsRegistry()
        registry.increment(
            "raad_http_requests_total",
            labels={"method": "GET", "route": "/health", "status": "200"},
        )
        body = registry.render()
        self.assertIn(
            'raad_http_requests_total{method="GET",route="/health",status="200"} 1', body
        )

    def test_repeated_increment_accumulates_the_same_series(self) -> None:
        registry = MetricsRegistry()
        for _ in range(3):
            registry.increment(
                "raad_http_requests_total",
                labels={"method": "GET", "route": "/health", "status": "200"},
            )
        body = registry.render()
        self.assertIn(
            'raad_http_requests_total{method="GET",route="/health",status="200"} 3', body
        )

    def test_different_labels_are_distinct_series(self) -> None:
        registry = MetricsRegistry()
        registry.increment(
            "raad_http_requests_total",
            labels={"method": "GET", "route": "/health", "status": "200"},
        )
        registry.increment(
            "raad_http_requests_total",
            labels={"method": "POST", "route": "/api/v1/auth/login", "status": "401"},
        )
        body = registry.render()
        self.assertIn(
            'raad_http_requests_total{method="GET",route="/health",status="200"} 1', body
        )
        self.assertIn(
            'raad_http_requests_total{method="POST",route="/api/v1/auth/login",status="401"} 1',
            body,
        )

    def test_dependency_gauges_render_true_and_false(self) -> None:
        registry = MetricsRegistry()
        body = registry.render(
            dependency_reachable={"database": True, "redis": False}
        )
        self.assertIn('raad_dependency_up{dependency="database"} 1', body)
        self.assertIn('raad_dependency_up{dependency="redis"} 0', body)

    def test_dependency_gauge_omitted_when_not_configured(self) -> None:
        registry = MetricsRegistry()
        body = registry.render(dependency_reachable={"broker": None})
        self.assertNotIn("dependency=\"broker\"", body)

    def test_route_template_keeps_cardinality_bounded_across_ids(self) -> None:
        """The whole point of labeling by route *template*, not raw path — this registry
        itself is agnostic to what string it's given, but confirms two different label values
        really do stay as two distinct series rather than colliding or exploding unexpectedly."""
        registry = MetricsRegistry()
        for vehicle_id in ("v1", "v2", "v3"):
            registry.increment(
                "raad_http_requests_total",
                labels={
                    "method": "GET",
                    "route": "/api/v1/vehicles/{vehicle_id}",
                    "status": "200",
                },
            )
        body = registry.render()
        self.assertIn(
            'raad_http_requests_total{method="GET",route="/api/v1/vehicles/{vehicle_id}",'
            'status="200"} 3',
            body,
        )


if __name__ == "__main__":
    unittest.main()
