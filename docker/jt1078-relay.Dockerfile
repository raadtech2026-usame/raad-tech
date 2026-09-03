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
#
# `ffmpeg` (ADR-0034): the one real runtime dependency this deployable has ever needed beyond
# Python's own stdlib + redis. Narrow, disclosed purpose — transcoding a confirmed-real device's
# G.711A audio to AAC, the only audio codec browsers' MediaSource Extensions reliably accept via
# `mpegts.js`'s own FLV->fMP4 remux path (Linear PCM and MP3-in-fMP4 both lack reliable MSE
# support, confirmed live against a real browser). Debian's own `ffmpeg` package, not a pinned
# custom build - this relay only uses ffmpeg's standard alaw-decode + AAC-LC encode, both stable
# for many releases.

FROM python:3.11-slim

WORKDIR /app

RUN groupadd --system appuser && useradd --system --gid appuser --create-home appuser \
    && apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

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

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir -e .

USER appuser

# 7910: device-facing ingest port (JT/T 1078 extended-RTP, the device connects here directly
# after 0x9101/0x9201 signaling names this host:port).
# 7911: viewer-facing WS-FLV delivery port (token-gated, ADR-0024 §5 point 2/§15).
EXPOSE 7910 7911

CMD ["python", "-m", "src.relay"]
