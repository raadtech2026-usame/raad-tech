"""HTTP surface of the `billing` module (C8). Mounted at `/api/v1/billing` (+ subscriptions,
invoices, payments per Backend LLD §16.1).

Empty per Phase 4.2 scope — no endpoints beyond health checks are implemented yet.
"""
from fastapi import APIRouter

billing_router = APIRouter()
