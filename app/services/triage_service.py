"""Business logic layer — invokes the LangGraph graph and shapes the response."""
from __future__ import annotations
import time

from app.schemas.triage import TriageRequest, TriageResponse


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


async def invoke_triage(graph, request: TriageRequest) -> TriageResponse:
    t0 = time.time()
    config = {"configurable": {"thread_id": request.session_id}}

    existing = await graph.aget_state(config)
    if existing.values:
        input_data = {"messages": [{"role": "user", "content": request.message}]}
    else:
        input_data = {
            **_initial_state(request.session_id),
            "messages": [{"role": "user", "content": request.message}],
        }

    result = await graph.ainvoke(input_data, config=config)
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
