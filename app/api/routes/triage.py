"""POST /triage — main patient interaction endpoint."""
from __future__ import annotations
from fastapi import APIRouter, Depends

from app.api.dependencies import get_graph
from app.schemas.triage import TriageRequest, TriageResponse
from app.services.triage_service import invoke_triage

router = APIRouter()


@router.post("/triage", response_model=TriageResponse)
async def triage(request: TriageRequest, graph=Depends(get_graph)) -> TriageResponse:
    return await invoke_triage(graph, request)
