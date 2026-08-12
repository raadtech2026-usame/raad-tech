# JT1078 Media Relay — container image (ADR-0013's own pattern, extended here — this ADR itself
# doesn't name this service, but its Dockerization conventions apply identically).
# Independent deployable (.claude/rules/architecture.md #2) — no dependency on backend/raad or
# on services/device-gateway; the only cross-service integration is the shared Redis broker
# (ADR-0024 §8/§9), coordinated entirely over the network, never shared code.
#
# Build context is `services/jt1078/` itself. `pyproject.toml` declares one dependency,
# `redis>=5.0` (the same pin already approved for device-gateway, ADR-0008/ADR-0010/ADR-0012);
# everything else (ingest demux, FLV muxer, WS-FLV viewer server) is stdlib, so no compiler
# toolchain is needed on top of python:3.11-slim.

FROM python:3.11-slim

WORKDIR /app

RUN groupadd --system appuser && useradd --system --gid appuser --create-home appuser

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir -e .

USER appuser

# 7910: device-facing ingest port (JT/T 1078 extended-RTP, the device connects here directly
# after 0x9101/0x9201 signaling names this host:port).
# 7911: viewer-facing WS-FLV delivery port (token-gated, ADR-0024 §5 point 2/§15).
EXPOSE 7910 7911

CMD ["python", "-m", "src.relay"]
