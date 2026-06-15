"""Pydantic request/response schemas for the triage API."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class TriageRequest(BaseModel):
    message: str
    session_id: str = "default-session"


class TriageResponse(BaseModel):
    response: str
    session_id: str
    intent: Optional[str] = None
    acuity: Optional[str] = None
    escalated: bool = False
    blocked: bool = False
    latency_ms: int
    estimated_cost_usd: float
    llm_calls: int
