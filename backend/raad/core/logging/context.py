"""Log context binding (Backend LLD §13.1).

Every log line carries request/correlation identity and, where resolved, principal/tenant
identity — bound once at the edge (HTTP middleware) and propagated through the call stack via
`contextvars`, which are async-task-safe (each request gets its own copy).
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
principal_id_var: ContextVar[str | None] = ContextVar("principal_id", default=None)
role_var: ContextVar[str | None] = ContextVar("role", default=None)
org_id_var: ContextVar[str | None] = ContextVar("org_id", default=None)
worker_name_var: ContextVar[str | None] = ContextVar("worker_name", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)

_ALL_VARS: dict[str, ContextVar[str | None]] = {
    "request_id": request_id_var,
    "correlation_id": correlation_id_var,
    "principal_id": principal_id_var,
    "role": role_var,
    "org_id": org_id_var,
    "worker_name": worker_name_var,
    "job_id": job_id_var,
}


def bind_context(**fields: str | None) -> dict[str, Token]:
    """Sets any of request_id/correlation_id/principal_id/role/org_id/worker_name/job_id for
    the current context. Returns reset tokens so the caller can restore prior values (see
    `reset_context`) — used by HTTP middleware and, for background work, `core.workers.logging`
    to unbind at the end of a request/job."""
    tokens: dict[str, Token] = {}
    for name, value in fields.items():
        var = _ALL_VARS[name]
        tokens[name] = var.set(value)
    return tokens


def reset_context(tokens: dict[str, Token]) -> None:
    for name, token in tokens.items():
        _ALL_VARS[name].reset(token)


def get_context() -> dict[str, Any]:
    """Snapshot of all currently-bound context fields, for the log formatter to attach."""
    return {name: var.get() for name, var in _ALL_VARS.items() if var.get() is not None}
