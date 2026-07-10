"""HTTP surface of the `video` module (C6). Mounted at `/api/v1/video` (Backend LLD §16.1).
Org-Admin-only surface by construction (D5) once endpoints are added — the Parent role must
never gain a reachable code path here (see `.claude/rules/security.md`).

Empty per Phase 4.2 scope — no endpoints beyond health checks are implemented yet.
"""
from fastapi import APIRouter

video_router = APIRouter()
