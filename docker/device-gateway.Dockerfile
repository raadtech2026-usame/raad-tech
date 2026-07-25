# RAAD Device Gateway — container image (ADR-0013: docs/architecture/adr/
# 0013-platform-dockerization.md). Independent deployable (.claude/rules/architecture.md #2) —
# no dependency on backend/raad, built and run entirely on its own.
#
# Build context is `services/device-gateway/` itself. `pyproject.toml` declares one dependency,
# `redis>=5.0` (device-gateway Redis integration, ADR-0010/ADR-0012); everything else is stdlib,
# so no compiler toolchain is needed on top of python:3.11-slim.

FROM python:3.11-slim

WORKDIR /app

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
