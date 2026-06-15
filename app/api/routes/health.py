"""GET /health — liveness probe."""
from __future__ import annotations
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    return {"status": "ok", "graph_ready": request.app.state.graph is not None}
