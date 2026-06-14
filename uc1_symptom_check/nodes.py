"""UC1 Symptom Check nodes."""
from __future__ import annotations
import logging
from models.state import TriageState
from models.llm import get_llm_client
from tools.patient import get_appointment_history
from prompts.uc1 import build_symptom_response_request

logger = logging.getLogger(__name__)

HIGH_ACUITY_TERMS = [
    "severe", "sudden", "worst", "can't walk", "unable to walk",
    "high fever", "103", "104", "105", "can't eat", "can't drink",
    "vision loss", "worst headache of my life", "jaw pain", "left arm",
]
MEDIUM_ACUITY_TERMS = [
    # Duration — days (numeric)
    "2 days", "3 days", "4 days", "5 days", "6 days", "7 days",
    # Duration — days (written)
    "two days", "three days", "four days", "five days", "six days", "seven days",
    "a few days", "few days", "several days", "past few days", "last few days",
    # Duration — weeks
    "a week", "1 week", "2 weeks", "3 weeks", "4 weeks",
    "one week", "two weeks", "three weeks", "four weeks",
    "past week", "last week", "for weeks", "several weeks",
    # Duration — months
    "a month", "past month", "last month", "for months", "several months",
    "few months", "a few months", "for the past month",
    # Progression
    "getting worse", "worsening", "not improving", "no improvement",
    "hasn't improved", "has not improved", "not getting better",
    "not going away", "won't go away", "keeps coming back", "comes back",
    "spreading", "spreading to",
    "not helping", "isn't helping", "not working", "isn't working",
    "no relief", "not cleared up", "hasn't cleared",
    # Pattern
    "persistent", "ongoing", "recurring", "recurrent", "chronic", "lingering",
    "on and off", "on-and-off", "intermittent", "comes and goes",
    "daily", "every day", "each day", "multiple times a day",
]
MENTAL_HEALTH_CRISIS_TERMS = [
    "suicidal", "self-harm", "want to die", "end my life", "hopeless",
    "severe depression", "panic attack", "can't function",
]



def _classify_acuity_with_reason(message: str, needs_escalation: bool) -> tuple[str, str]:
    if needs_escalation:
        return "High", "emergency escalation flag"
    text_lower = message.lower()
    for t in MENTAL_HEALTH_CRISIS_TERMS:
        if t in text_lower:
            return "High", f"mental health term: {t!r}"
    for t in HIGH_ACUITY_TERMS:
        if t in text_lower:
            return "High", f"high-acuity term: {t!r}"
    for t in MEDIUM_ACUITY_TERMS:
        if t in text_lower:
            return "Medium", f"medium-acuity term: {t!r}"
    return "Low", "no acuity terms matched"


async def symptom_check_node(state: TriageState) -> dict:
    message = state.get("de_identified_message", "")
    needs_escalation = state.get("needs_escalation", False)
    acuity, acuity_reason = _classify_acuity_with_reason(message, needs_escalation)
    logger.info("  [UC1] Acuity=%s (%s)", acuity, acuity_reason)
    first_name = state.get("patient_first_name") or None

    client = get_llm_client()
    response = await client.complete(
        build_symptom_response_request(message, acuity, first_name)
    )
    logger.info("  [UC1] LLM response generated (cost=$%.4f)", response.estimated_cost_usd)

    patient_id = state.get("patient_id")
    appointment_offer = ""
    if acuity in ("Low", "Medium") and patient_id:
        history = await get_appointment_history(patient_id)
        if history.get("has_prior_appointments"):
            doc = history["preferred_doctor"]["doctor_name"]
            appointment_offer = (
                f"\n\nWould you like me to book a follow-up consultation "
                f"with {doc}, or schedule a new appointment?"
            )
        else:
            appointment_offer = (
                "\n\nWould you like me to help you book a doctor's appointment?"
            )

    full_response = response.content + appointment_offer

    return {
        "chief_complaint": message[:200],
        "acuity": acuity,
        "patient_response": full_response,
        "uc1_complete": True,
        "total_cost_usd": state.get("total_cost_usd", 0.0) + response.estimated_cost_usd,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def route_after_uc1(state: TriageState) -> str:
    pending = state.get("pending_intent")
    if pending == "UC3":
        return "summarize"
    return "compliance"
