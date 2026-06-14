"""FastAPI backend — Healthcare AI Patient Symptom Triage Concierge."""
from __future__ import annotations
import os
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from graph.main_graph import build_graph
from models.classifier import get_classifier

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    logger.info("Pre-loading local classifier...")
    get_classifier()
    logger.info("Building LangGraph...")
    _graph = build_graph()          # MemorySaver (in-memory, demo)
    # Production: use RedisSaver
    # from langgraph.checkpoint.redis import RedisSaver
    # _graph = build_graph(checkpointer=RedisSaver.from_conn_string(os.getenv("REDIS_URL")))
    logger.info("Ready.")
    yield


app = FastAPI(
    title="Healthcare AI Triage Concierge",
    description=(
        "Multi-agent patient symptom triage system. "
        "3 use cases: Symptom Check, Prescription Refill, Appointment Booking."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def _initial_state(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "patient_id": None,
        "patient_first_name": None,
        "phi_lookup_table": {},
        "messages": [],
        "current_intent": None,
        "intent_history": [],
        "pending_intent": None,
        "de_identified_message": None,
        "is_health_related": False,
        "needs_escalation": False,
        "escalation_signals": [],
        "chief_complaint": None,
        "acuity": None,
        "uc1_complete": False,
        "uc1_summary": None,
        "medications_extracted": [],
        "medications_confirmed": [],
        "uc2_awaiting_confirmation": False,
        "prescription_status": None,
        "order_id": None,
        "uc2_complete": False,
        "uc2_summary": None,
        "appointment_type": None,
        "visit_mode": None,
        "reason_for_visit": None,
        "preferred_doctor": None,
        "available_slots": [],
        "selected_slot": None,
        "appointment_id": None,
        "uc3_complete": False,
        "awaiting_911_confirmation": False,
        "hitl_triggered": False,
        "emergency_dispatched": False,
        "emergency_summary": None,
        "patient_response": None,
        "response_blocked": False,
        "block_reason": None,
        "total_cost_usd": 0.0,
        "llm_calls": 0,
        "turn_count": 0,
    }


@app.post("/triage", response_model=TriageResponse)
async def triage(request: TriageRequest) -> TriageResponse:
    t0 = time.time()
    config = {"configurable": {"thread_id": request.session_id}}

    # Only send full initial state on first turn; subsequent turns send only the new message
    existing = await _graph.aget_state(config)
    if existing.values:
        input_data = {"messages": [{"role": "user", "content": request.message}]}
    else:
        input_data = {
            **_initial_state(request.session_id),
            "messages": [{"role": "user", "content": request.message}],
        }

    result = await _graph.ainvoke(input_data, config=config)

    latency_ms = int((time.time() - t0) * 1000)
    escalated = result.get("needs_escalation", False)
    clarification_pending = result.get("clarification_pending", False)

    if escalated:
        intent_label = "EMERGENCY"
    elif clarification_pending:
        intent_label = "CLARIFYING"
    else:
        intent_label = result.get("current_intent")

    return TriageResponse(
        response=result.get("patient_response") or "I'm sorry, something went wrong. Please try again.",
        session_id=request.session_id,
        intent=intent_label,
        acuity=result.get("acuity"),
        escalated=escalated,
        blocked=result.get("response_blocked", False),
        latency_ms=latency_ms,
        estimated_cost_usd=round(result.get("total_cost_usd", 0.0), 6),
        llm_calls=result.get("llm_calls", 0),
    )


@app.get("/health")
async def health():
    return {"status": "ok", "graph_ready": _graph is not None}
