"""guardrail_node — runs every turn before any UC processing."""
from __future__ import annotations
import logging
from models.state import TriageState
from guardrail.phi_detector import detect_and_deidentify
from guardrail.health_relevance import is_health_related
from guardrail.emergency_detector import detect_escalation
from prompts.guardrail import BLOCK_NOT_HEALTH

logger = logging.getLogger(__name__)


async def guardrail_node(state: TriageState) -> dict:
    last_message = state["messages"][-1].content if state["messages"] else ""

    # Step 1: PHI detection + de-identification
    de_identified, lookup, phi_found = detect_and_deidentify(last_message)

    # Merge new lookup entries into existing table
    existing_lookup = state.get("phi_lookup_table") or {}
    merged_lookup = {**existing_lookup, **lookup}

    # Extract first name if found in this turn
    first_name = state.get("patient_first_name")
    if not first_name:
        for token, value in lookup.items():
            if token.startswith("[PERSON_"):
                first_name = value.strip().split()[0]
                break

    # Step 2: Health relevance check (on de-identified message)
    health_related = is_health_related(de_identified)

    # Step 3: Emergency detection (on de-identified message)
    needs_escalation, escalation_signals = detect_escalation(de_identified)

    updates: dict = {
        "de_identified_message": de_identified,
        "phi_lookup_table": merged_lookup,
        "is_health_related": health_related,
        "needs_escalation": needs_escalation,
        "escalation_signals": escalation_signals,
        "turn_count": state.get("turn_count", 0) + 1,
        # Bug D fix: always reset block flag at the start of each turn
        "response_blocked": False,
        "block_reason": None,
    }

    if first_name:
        updates["patient_first_name"] = first_name

    if not health_related:
        updates["patient_response"] = BLOCK_NOT_HEALTH
        updates["response_blocked"] = True
        updates["block_reason"] = "not_health_related"
        logger.info("Guardrail: blocked — not health related")

    return updates


def route_after_guardrail(state: TriageState) -> str:
    # Bug E fix: patient replying to the 911 prompt must re-enter emergency node
    if state.get("awaiting_911_confirmation"):
        return "escalation"
    if state.get("response_blocked"):
        return "blocked"
    if state.get("needs_escalation"):
        return "escalation"
    return "pass"
