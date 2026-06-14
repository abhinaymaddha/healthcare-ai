"""Intent router — classifies or carries forward the active use case."""
from __future__ import annotations
import logging
from models.state import TriageState
from models.llm import get_llm_client
from models.classifier import all_scores
from prompts.intent import build_intent_request, IntentResult

logger = logging.getLogger(__name__)

_NLI_LABELS = {
    "symptom check or health concern":           "UC1",
    "prescription refill or medication request": "UC2",
    "appointment or visit booking":              "UC3",
}

# ── Routing thresholds (calibrated for raw DeBERTa NLI logits) ───────────────
#
# DeBERTa NLI entailment logits are NOT probabilities; they can be negative.
# Observed ranges: appointment ~1.6, clear refill ~0.3, symptoms ~-1.1.
# The gap between top-2 scores is a more reliable signal than absolute value.
#
# Strategy:
#   • Very high confidence (high score + large gap) → direct route, no Haiku
#   • Any meaningful gap (≥ 0.15) → Haiku confirms the intent
#   • Truly tied (gap < 0.15) → clarification node
#   • Special: NLI says UC1 but Haiku says UC2/UC3 → patient stated symptoms
#     AND an explicit task request → genuinely mixed → clarification
#
_DIRECT_SCORE = 1.2   # NLI logit above which we skip Haiku
_DIRECT_GAP   = 1.0   # gap required alongside DIRECT_SCORE (avoids masked secondary intents)
_HAIKU_GAP    = 0.15  # minimum gap to call Haiku; below this → genuinely ambiguous


async def intent_router_node(state: TriageState) -> dict:
    # If clarification is in progress, stay put — route_intent sends to clarification
    if state.get("clarification_pending"):
        return {}

    message = state.get("de_identified_message", "")
    history = list(state.get("intent_history") or [])

    # Prescription demand phrases signal UC1 (health guidance), not UC2 (refill).
    # Checked BEFORE the UC-completion early-exit so demands override mid-session UC2.
    _PRESCRIPTION_DEMAND = [
        "prescribe me", "give me a prescription", "write me a prescription",
        "what dosage should i take", "what dose should i take",
        "maximum safe dose", "safe dose of", "safe dosage of",
        "what dosage", "what dose of", "correct dosage", "correct dose",
        "which medication should i", "what medication should i switch",
    ]
    msg_lower = message.lower()
    for phrase in _PRESCRIPTION_DEMAND:
        if phrase in msg_lower:
            logger.info("  [INTENT] Prescription demand detected → forcing UC1")
            history.append("UC1")
            return {
                "current_intent": "UC1",
                "intent_history": history,
                "pending_intent": None,
                "clarification_pending": False,
            }

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
        history.append(pending)
        return {
            "current_intent": pending,
            "pending_intent": None,
            "intent_history": history,
        }

    labels = list(_NLI_LABELS.keys())
    score_map = all_scores(message, labels)
    sorted_items = sorted(score_map.items(), key=lambda x: x[1], reverse=True)

    top_label,    top_score    = sorted_items[0]
    second_label, second_score = sorted_items[1]
    top_intent    = _NLI_LABELS[top_label]
    second_intent = _NLI_LABELS[second_label]
    gap           = top_score - second_score

    logger.info(
        "  [INTENT] NLI scores — %s=%.2f  %s=%.2f  %s=%.2f | gap=%.2f",
        _NLI_LABELS[sorted_items[0][0]], sorted_items[0][1],
        _NLI_LABELS[sorted_items[1][0]], sorted_items[1][1],
        _NLI_LABELS[sorted_items[2][0]], sorted_items[2][1],
        gap,
    )

    # ── Very high confidence → direct route (skip Haiku) ─────────────────────
    if top_score >= _DIRECT_SCORE and gap >= _DIRECT_GAP:
        logger.info(
            "  [INTENT] Direct → %s (logit=%.2f, gap=%.2f, no Haiku needed)",
            top_intent, top_score, gap,
        )
        history.append(top_intent)
        return {
            "current_intent": top_intent,
            "intent_history": history,
            "pending_intent": None,
            "clarification_pending": False,
        }

    # ── Meaningful gap → Haiku confirms ──────────────────────────────────────
    elif gap >= _HAIKU_GAP:
        client = get_llm_client()
        response = await client.complete(build_intent_request(message))
        result = IntentResult.parse(response.content)
        haiku_intent = result.intent
        logger.info(
            "  [INTENT] NLI top=%s → Haiku says %s",
            top_intent, haiku_intent,
        )

        if top_intent == "UC1" and haiku_intent != "UC1":
            detected = list(dict.fromkeys(["UC1", haiku_intent]))
            logger.info(
                "  [INTENT] Mixed signal (symptoms + task request) → CLARIFICATION | detected=%s",
                detected,
            )
            return _clarification_state(state, detected, history)

        logger.info("  [INTENT] Haiku confirmed → routing to %s", haiku_intent)
        history.append(haiku_intent)
        return {
            "current_intent": haiku_intent,
            "intent_history": history,
            "pending_intent": None,
            "clarification_pending": False,
        }

    # ── Genuinely tied intents → clarification ────────────────────────────────
    else:
        detected = list(dict.fromkeys([top_intent, second_intent]))
        logger.info(
            "  [INTENT] Tied intents (gap=%.2f < %.2f) → CLARIFICATION | detected=%s",
            gap, _HAIKU_GAP, detected,
        )
        return _clarification_state(state, detected, history)


def _clarification_state(state: TriageState, detected: list, history: list) -> dict:
    return {
        "clarification_pending": True,
        "detected_intents": detected,
        "clarification_form": state.get("clarification_form") or {},
        "clarification_turns": state.get("clarification_turns") or 0,
        "intent_history": history,
    }


def route_intent(state: TriageState) -> str:
    if state.get("clarification_pending"):
        return "clarification"
    return state.get("current_intent", "UC1")
