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

RUN groupadd --system appuser && useradd --system --gid appuser --create-home appuser

COPY pyproject.toml ./
COPY raad ./raad
COPY migrations ./migrations
COPY alembic.ini ./

RUN pip install --no-cache-dir -e .

USER appuser

EXPOSE 8000

# API process default. `migrate`/`worker` (docker-compose.yml) override `command:` on this same
# image to `alembic upgrade head` / `python -m raad.interfaces.workers.bootstrap`.
CMD ["uvicorn", "raad.main:app", "--host", "0.0.0.0", "--port", "8000"]
