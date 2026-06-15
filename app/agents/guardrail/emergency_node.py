"""Emergency escalation node with HITL interrupt."""
from __future__ import annotations
import logging
from langgraph.types import interrupt
from app.core.state import TriageState
from app.tools.emergency import dispatch_emergency_services, notify_human_reviewer
from app.prompts.guardrail import (
    ASK_DISPATCH,
    DECLINED_DISPATCH_MSG,
    HITL_MSG,
)

logger = logging.getLogger(__name__)


async def emergency_node(state: TriageState) -> dict:
    signals = state.get("escalation_signals") or []

    # First time entering — ask patient about dispatch
    if not state.get("awaiting_911_confirmation"):
        logger.info("  [EMERGENCY] First entry — signals=%s → asking dispatch question", signals)
        return {
            "awaiting_911_confirmation": True,
            "patient_response": ASK_DISPATCH,
        }

    # Patient replied to the dispatch question
    messages = state.get("messages") or []
    last = messages[-1].content if messages else ""
    logger.info("  [EMERGENCY] Patient replied: %r", last[:120])

    if any(w in last.lower() for w in ["yes", "yeah", "please", "do it", "call"]):
        logger.info("  [EMERGENCY] Dispatch confirmed → calling emergency services → activating companion")
        await dispatch_emergency_services(patient_id=state.get("patient_id", "unknown"))
        # patient_response intentionally left unset — companion intake_node generates it
        return {
            "awaiting_911_confirmation": False,
            "emergency_dispatched": True,
        }

    if any(w in last.lower() for w in ["no", "nope", "don't", "cancel"]):
        logger.info("  [EMERGENCY] Dispatch declined → monitoring mode")
        return {
            "awaiting_911_confirmation": False,
            "patient_response": DECLINED_DISPATCH_MSG,
        }

    # No clear yes/no → HITL interrupt
    logger.info("  [EMERGENCY] No clear yes/no → HITL reviewer notified")
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


def route_after_emergency(state: TriageState) -> str:
    """After dispatch confirmed, hand off to companion subgraph. Otherwise format response."""
    if state.get("emergency_dispatched"):
        return "emergency_companion"
    return "response_formatter"
