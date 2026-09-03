# RAAD Business API — container image (ADR-0013: docker/architecture/adr/
# 0013-platform-dockerization.md).
#
# Reused, unmodified, for the `migrate` and `worker` Compose services too — `interfaces/workers/
# bootstrap.py`'s own docstring notes workers "can run in-process with the API at the smallest
# scale and split into their own process as load grows — no redesign"; only the container
# `command:` differs per service, so there is no separate `worker.Dockerfile`.
#
# Build context is `backend/` itself (not the repo root) — `migrations/`/`alembic.ini` already
# live there alongside `raad/`, so nothing outside this directory is needed. FastAPI/SQLAlchemy/
# asyncpg/redis-py/pydantic all ship manylinux wheels for cp311, so no compiler toolchain is
# installed here.

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
COPY raad ./raad
COPY migrations ./migrations
COPY alembic.ini ./

# --default-timeout/--retries: resilience against a slow/unstable network mid-build — pip's
# stock 15s read timeout was observed failing repeatedly on a constrained connection; a longer
# per-chunk timeout plus more retries is strictly safer everywhere (a fast network just never
# hits either limit), not a workaround specific to any one environment.
RUN pip install --no-cache-dir --default-timeout=100 --retries 10 -e .

USER appuser

EXPOSE 8000

# API process default. `migrate`/`worker` (docker-compose.yml) override `command:` on this same
# image to `alembic upgrade head` / `python -m raad.interfaces.workers.bootstrap`.
CMD ["uvicorn", "raad.main:app", "--host", "0.0.0.0", "--port", "8000"]
