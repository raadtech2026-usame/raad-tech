"""HTTP surface of the `transport_ops` module (C4). Mounted at `/api/v1/students`,
`/api/v1/parents`, `/api/v1/routes`, and `/api/v1/trips` (Backend LLD §16.1).

Empty per Phase 4.2 scope — no endpoints beyond health checks are implemented yet.
"""
from fastapi import APIRouter

students_router = APIRouter()
parents_router = APIRouter()
routes_router = APIRouter()
trips_router = APIRouter()
