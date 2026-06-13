"""Intent router — classifies or carries forward the active use case."""
from __future__ import annotations
import logging
from models.state import TriageState
from models.llm import get_llm_client
from models.classifier import top_label
from prompts.intent import build_intent_request, IntentResult

logger = logging.getLogger(__name__)

_NLI_INTENT_LABELS = {
    "symptom check or health concern":           "UC1",
    "prescription refill or medication request": "UC2",
    "appointment or visit booking":              "UC3",
}
_NLI_CONFIDENCE_THRESHOLD = 0.55


async def intent_router_node(state: TriageState) -> dict:
    # Stay in the current UC if it is not yet complete
    current = state.get("current_intent")
    if current == "UC1" and not state.get("uc1_complete"):
        return {}
    if current == "UC2" and not state.get("uc2_complete"):
        return {}
    if current == "UC3" and not state.get("uc3_complete"):
        return {}

    # Carry forward a pending intent queued by a previous UC
    pending = state.get("pending_intent")
    if pending:
        history = list(state.get("intent_history") or [])
        history.append(pending)
        return {
            "current_intent": pending,
            "pending_intent": None,
            "intent_history": history,
        }

    message = state.get("de_identified_message", "")

    # Primary classification: local NLI model (zero cost)
    label, score = top_label(message, list(_NLI_INTENT_LABELS.keys()))
    intent = _NLI_INTENT_LABELS[label]
    logger.info("NLI intent: %s (score=%.2f)", intent, score)

    # Low confidence → Haiku confirms with few-shot structured prompt
    if score < _NLI_CONFIDENCE_THRESHOLD:
        client = get_llm_client()
        response = await client.complete(build_intent_request(message))
        result = IntentResult.parse(response.content)
        intent = result.intent
        logger.info("Haiku intent override: %s", intent)

    history = list(state.get("intent_history") or [])
    history.append(intent)
    return {
        "current_intent": intent,
        "intent_history": history,
        "pending_intent": None,
    }


def route_intent(state: TriageState) -> str:
    return state.get("current_intent", "UC1")
