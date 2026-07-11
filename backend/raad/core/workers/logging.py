"""Background-job log context binding (Backend LLD §13.1: "every log line carries...
propagated, including into workers via the event's `correlation_id`"). Reuses the same
`contextvars` mechanism HTTP middleware uses (`core/logging/context.py`) so worker log lines
get the identical structured-JSON shape, just with `worker_name`/`job_id` instead of
`request_id`/`correlation_id`.
"""

from __future__ import annotations

from raad.core.logging.context import Token, bind_context, reset_context


def bind_worker_context(worker_name: str, job_id: str | None = None) -> dict[str, Token]:
    """Call at the start of a worker tick/job; pass the returned tokens to `reset_context`
    (or `unbind_worker_context`) when the tick/job ends."""
    return bind_context(worker_name=worker_name, job_id=job_id)


def unbind_worker_context(tokens: dict[str, Token]) -> None:
    reset_context(tokens)
