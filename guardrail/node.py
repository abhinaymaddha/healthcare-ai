"""guardrail_node — runs every turn before any UC processing."""
from __future__ import annotations
import logging
from models.state import TriageState
from guardrail.phi_detector import detect_and_deidentify
from guardrail.health_relevance import is_health_related
from guardrail.emergency_detector import detect_escalation
from guardrail.diagnosis_detector import detect_diagnosis_demand
from prompts.guardrail import BLOCK_NOT_HEALTH, BLOCK_DIAGNOSIS_DEMAND

logger = logging.getLogger(__name__)


async def guardrail_node(state: TriageState) -> dict:
    last_message = state["messages"][-1].content if state["messages"] else ""
    turn_count = state.get("turn_count", 0) + 1

    logger.info("─── TURN %d ──────────────────────────────────────────────", turn_count)
    logger.info("  Patient: %r", last_message[:120] + ("…" if len(last_message) > 120 else ""))

    # Step 1: PHI detection + de-identification
    de_identified, lookup, phi_found = detect_and_deidentify(last_message)

    existing_lookup = state.get("phi_lookup_table") or {}
    merged_lookup = {**existing_lookup, **lookup}

    if lookup:
        logger.info("  PHI: %d token(s) replaced → %s", len(lookup), list(lookup.keys()))
    else:
        logger.info("  PHI: none detected")

    # Extract first name if found in this turn
    first_name = state.get("patient_first_name")
    if not first_name:
        for token, value in lookup.items():
            if token.startswith("[PERSON_"):
                first_name = value.strip().split()[0]
                break

    in_clarification = bool(state.get("clarification_pending"))
    awaiting_911 = bool(state.get("awaiting_911_confirmation"))

    # Step 2: Health relevance check
    # Skip when the patient is answering our own clarification questions or the 911
    # dispatch prompt — those answers don't need to be independently health-related.
    if in_clarification or awaiting_911:
        health_related = True
        logger.info("  Health: skipped (clarification_pending=%s, awaiting_911=%s) → PASS", in_clarification, awaiting_911)
    else:
        health_related = is_health_related(de_identified)

    # Step 3: Emergency detection — always runs, even mid-clarification
    needs_escalation, escalation_signals = detect_escalation(de_identified)
    if needs_escalation:
        logger.info("  Emergency: ESCALATE — signals=%s", escalation_signals)
    else:
        logger.info("  Emergency: clear")

    # Step 4: Diagnosis demand detection — skip mid-clarification (patient answering our Q)
    if in_clarification:
        is_diagnosis_demand, diagnosis_signal = False, None
        logger.info("  Diagnosis demand: skipped (in clarification)")
    else:
        is_diagnosis_demand, diagnosis_signal = detect_diagnosis_demand(de_identified)
        if is_diagnosis_demand:
            logger.info("  Diagnosis demand: BLOCKED — signal=%r", diagnosis_signal)
        else:
            logger.info("  Diagnosis demand: clear")

    updates: dict = {
        "de_identified_message": de_identified,
        "phi_lookup_table": merged_lookup,
        "is_health_related": health_related,
        "needs_escalation": needs_escalation,
        "escalation_signals": escalation_signals,
        "diagnosis_demand": is_diagnosis_demand,
        "turn_count": turn_count,
        "response_blocked": False,
        "block_reason": None,
    }

    if first_name:
        updates["patient_first_name"] = first_name

    if not health_related:
        updates["patient_response"] = BLOCK_NOT_HEALTH
        updates["response_blocked"] = True
        updates["block_reason"] = "not_health_related"
        logger.info("  Route → BLOCKED (not health-related)")
    elif is_diagnosis_demand:
        updates["patient_response"] = BLOCK_DIAGNOSIS_DEMAND
        updates["response_blocked"] = True
        updates["block_reason"] = f"diagnosis_demand:{diagnosis_signal}"
        logger.info("  Route → BLOCKED (diagnosis demand)")
    elif needs_escalation:
        logger.info("  Route → EMERGENCY")
    else:
        logger.info("  Route → PASS")

    return updates


def route_after_guardrail(state: TriageState) -> str:
    # Once dispatch is confirmed, every turn goes to the companion subgraph
    if state.get("emergency_dispatched"):
        return "emergency_companion"
    # Patient replying to the 911 dispatch question
    if state.get("awaiting_911_confirmation"):
        return "escalation"
    if state.get("response_blocked"):
        return "blocked"
    if state.get("needs_escalation"):
        return "escalation"
    return "pass"
