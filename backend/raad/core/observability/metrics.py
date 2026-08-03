"""Minimal, hand-rolled Prometheus-text-exposition-format metrics registry (Priority 1 Item 5,
`PROJECT_STATUS.md`'s "minimum monitoring"). No new dependency (`prometheus-client` or
equivalent) — this codebase already prefers a small, purpose-built primitive over a
general-purpose framework where the actual need is this narrow (one counter, dependency gauges,
a process-start gauge — no histograms/quantiles), the same reasoning `core/pagination`/`core/di`
already apply for their own hand-rolled-over-framework decisions.

Process-local, in-memory only — deliberately not shared across worker processes, matching
`interfaces/http/realtime.ConnectionManager`'s identical "correct for this single-process
deployment shape, would need a shared backend (Redis) behind the same interface to scale to
multiple instances" precedent, not attempted here for the same reason.
"""

from __future__ import annotations

import threading
import time

_LabelKey = tuple[tuple[str, str], ...]


def _label_key(labels: dict[str, str]) -> _LabelKey:
    return tuple(sorted(labels.items()))


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    parts = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return "{" + parts + "}"


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[_LabelKey, float]] = {}
        self._start_time = time.time()

    def increment(
        self, name: str, *, labels: dict[str, str] | None = None, value: float = 1.0
    ) -> None:
        key = _label_key(labels or {})
        with self._lock:
            series = self._counters.setdefault(name, {})
            series[key] = series.get(key, 0.0) + value

    def render(self, *, dependency_reachable: dict[str, bool | None] | None = None) -> str:
        """Prometheus text exposition format (the 0.0.4 line-based standard every scraper —
        Prometheus itself, Grafana Agent, OpenTelemetry Collector — already understands)."""
        lines: list[str] = []

        lines.append(
            "# HELP raad_http_requests_total Total HTTP requests processed, labeled by "
            "method, route template (not raw path, to keep cardinality bounded), and status "
            "code."
        )
        lines.append("# TYPE raad_http_requests_total counter")
        with self._lock:
            request_series = dict(self._counters.get("raad_http_requests_total", {}))
        for label_key, value in sorted(request_series.items()):
            lines.append(
                f"raad_http_requests_total{_format_labels(dict(label_key))} {value:g}"
            )

        lines.append(
            "# HELP raad_dependency_up Whether a configured dependency (database, redis, "
            "broker) is currently reachable (1) or not (0). A dependency that was never "
            "configured at all is omitted here, not fabricated as 0."
        )
        lines.append("# TYPE raad_dependency_up gauge")
        for dependency, reachable in sorted((dependency_reachable or {}).items()):
            if reachable is None:
                continue
            lines.append(
                f'raad_dependency_up{{dependency="{dependency}"}} {1 if reachable else 0}'
            )

        lines.append(
            "# HELP raad_process_start_time_seconds Unix timestamp this process started — "
            "diff against wall-clock time to derive uptime, or watch for unexpected jumps to "
            "detect restarts."
        )
        lines.append("# TYPE raad_process_start_time_seconds gauge")
        lines.append(f"raad_process_start_time_seconds {self._start_time:.0f}")

        return "\n".join(lines) + "\n"
