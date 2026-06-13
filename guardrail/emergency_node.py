"""Emergency escalation node with HITL interrupt."""
from __future__ import annotations
import logging
from langgraph.types import interrupt
from models.state import TriageState
from tools.emergency import dispatch_emergency_services, notify_human_reviewer
from prompts.guardrail import (
    ASK_DISPATCH,
    DISPATCHED_MSG,
    DECLINED_DISPATCH_MSG,
    HITL_MSG,
)

logger = logging.getLogger(__name__)


async def emergency_node(state: TriageState) -> dict:
    # First time entering — ask patient about dispatch
    if not state.get("awaiting_911_confirmation"):
        return {
            "awaiting_911_confirmation": True,
            "patient_response": ASK_DISPATCH,
        }

    # Patient replied
    messages = state.get("messages") or []
    last = messages[-1].content.lower() if messages else ""

    if any(w in last for w in ["yes", "yeah", "please", "do it", "call"]):
        result = await dispatch_emergency_services(
            patient_id=state.get("patient_id", "unknown"),
        )
        return {
            "awaiting_911_confirmation": False,
            "patient_response": DISPATCHED_MSG,
        }

    if any(w in last for w in ["no", "nope", "don't", "cancel"]):
        return {
            "awaiting_911_confirmation": False,
            "patient_response": DECLINED_DISPATCH_MSG,
        }

    # No clear response → HITL interrupt
    interrupt({"reason": "no_911_response", "session_id": state.get("session_id")})
    await notify_human_reviewer(
        session_id=state.get("session_id", ""),
        transcript=[m.content for m in messages],
    )
    return {
        "hitl_triggered": True,
        "awaiting_911_confirmation": False,
        "patient_response": HITL_MSG,
    }
