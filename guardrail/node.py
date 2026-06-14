"""guardrail_node — runs every turn before any UC processing."""
from __future__ import annotations
import logging
from models.state import TriageState
from guardrail.phi_detector import detect_and_deidentify
from guardrail.health_relevance import check_health_relevance, HealthRelevance
from guardrail.emergency_detector import detect_escalation
from guardrail.diagnosis_detector import detect_diagnosis_demand
from prompts.guardrail import BLOCK_NOT_HEALTH

logger = logging.getLogger(__name__)


async def guardrail_node(state: TriageState) -> dict:
    last_message = state["messages"][-1].content if state["messages"] else ""
    turn_count = state.get("turn_count", 0) + 1
    session_id = state.get("session_id", "?")

    logger.info(
        "─── TURN %d [%s] ──────────────────────────────────────────",
        turn_count, session_id,
    )
    logger.info("  Patient: %r", last_message[:120] + ("..." if len(last_message) > 120 else ""))

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
    mid_session = bool(state.get("current_intent"))

    # Step 2: Three-tier health relevance check.
    # Skip when: (a) answering our own clarification questions, (b) answering 911 dispatch,
    # (c) already mid-session (turn 2+ in an established UC flow) — short answers like
    # "Yes, in-person please" or "Yep looks good" are always valid continuations.
    if in_clarification or awaiting_911 or mid_session:
        health_result = HealthRelevance.HEALTH
        logger.info(
            "  Health: skipped (clarification=%s, 911=%s, mid_session=%s) → HEALTH",
            in_clarification, awaiting_911, mid_session,
        )
    else:
        health_result = check_health_relevance(de_identified)

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
        "is_health_related": health_result != HealthRelevance.NOT_HEALTH,
        "needs_escalation": needs_escalation,
        "escalation_signals": escalation_signals,
        "diagnosis_demand": is_diagnosis_demand,
        "turn_count": turn_count,
        "response_blocked": False,
        "block_reason": None,
    }

    if first_name:
        updates["patient_first_name"] = first_name

    if health_result == HealthRelevance.NOT_HEALTH:
        updates["patient_response"] = BLOCK_NOT_HEALTH
        updates["response_blocked"] = True
        updates["block_reason"] = "not_health_related"
        logger.info("  Route → BLOCKED (not health-related)")

    elif health_result == HealthRelevance.AMBIGUOUS:
        # Message is unclear — don't block, don't guess. Route to clarification so
        # the LLM can ask one open question and gather enough context to route properly.
        updates["clarification_pending"] = True
        updates["detected_intents"] = ["UC1", "UC2", "UC3"]
        updates["clarification_form"] = state.get("clarification_form") or {}
        updates["clarification_turns"] = state.get("clarification_turns") or 0
        logger.info("  Route → AMBIGUOUS → clarification (intent unknown)")

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
    if state.get("needs_escalation"):
        return "escalation"
    if state.get("response_blocked"):
        return "blocked"
    return "pass"
