# RAAD Device Gateway — container image (ADR-0013: docs/architecture/adr/
# 0013-platform-dockerization.md). Independent deployable (.claude/rules/architecture.md #2) —
# no dependency on backend/raad, built and run entirely on its own.
#
# Build context is `services/device-gateway/` itself. `pyproject.toml` declares one dependency,
# `redis>=5.0` (device-gateway Redis integration, ADR-0010/ADR-0012); everything else is stdlib,
# so no compiler toolchain is needed on top of python:3.11-slim.

FROM python:3.11-slim

WORKDIR /app

# Line-buffer stdout (2026-09-02). `logging_setup.py` writes to `sys.stdout`, which Python
# block-buffers (8KB) whenever stdout is a pipe rather than a TTY - which it always is under
# Docker. A high-volume service masks this (its buffer fills constantly), but a low-volume
# one does not: `device-gateway` produced ZERO observable log output for five days straight
# while genuinely running and serving a live JT/T 808 device connection, because its output
# never filled a single buffer. That made every device-plane fact (0x9101 sends, 0x0001
# acks, heartbeats, position reports) unobservable in `docker logs` - the exact evidence
# needed to diagnose a media session that never establishes. Observability only; no
# behavioral change to any service.
ENV PYTHONUNBUFFERED=1

RUN groupadd --system appuser && useradd --system --gid appuser --create-home appuser

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir -e .

USER appuser

# 7808: JT/T 808 adapter (dormant — no compliant vendor procured yet, kept running per
# DeviceGateway._build_adapters(), see .claude/rules/jt808.md's "reality check").
# 7809: LSZ MDVR adapter — the actually-integrated hardware (ADR-0009).
EXPOSE 7808 7809

# The real, already-implemented entrypoint — src/gateway.py's own `if __name__ == "__main__"`.
CMD ["python", "-m", "src.gateway"]
