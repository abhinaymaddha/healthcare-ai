"""Clarification node — iterative intake form collection before UC routing."""
from __future__ import annotations
import logging
from models.state import TriageState
from models.llm import get_llm_client
from prompts.clarification import build_clarification_request, ClarificationResult

logger = logging.getLogger(__name__)

_MAX_CLARIFICATION_TURNS = 3


def _build_conversation_context(messages: list) -> str:
    """Summarise the last N messages for the Haiku prompt."""
    lines = []
    for m in messages[-8:]:  # last 8 messages is more than enough context
        role = "Patient" if getattr(m, "type", "") == "human" else "Assistant"
        lines.append(f"{role}: {m.content}")
    return "\n".join(lines)


def _synthesize_complaint(form: dict) -> str:
    """Build a coherent symptom summary from the collected form fields."""
    parts = []
    if form.get("primary_concern"):
        parts.append(form["primary_concern"])
    if form.get("severity"):
        parts.append(f"severity: {form['severity']}")
    if form.get("duration"):
        parts.append(f"for {form['duration']}")
    if form.get("onset"):
        parts.append(f"onset: {form['onset']}")
    if form.get("emergency_signs") is False:
        parts.append("no emergency signs reported")
    return "; ".join(parts) if parts else ""


async def clarification_node(state: TriageState) -> dict:
    messages = state.get("messages") or []
    form = dict(state.get("clarification_form") or {})
    turns = state.get("clarification_turns") or 0
    detected = state.get("detected_intents") or []

    # Preserve original message on first clarification turn
    if "original_message" not in form:
        form["original_message"] = state.get("de_identified_message", "")

    # Safety valve — after max turns, default to safest routing
    if turns >= _MAX_CLARIFICATION_TURNS:
        fallback = "UC1" if "UC1" in detected else (detected[0] if detected else "UC1")
        logger.info("Clarification: max turns reached, defaulting to %s", fallback)
        return _complete_routing(fallback, form, turns)

    # Call Haiku to extract data and generate next question
    context = _build_conversation_context(messages)
    client = get_llm_client()
    response = await client.complete(
        build_clarification_request(context, form, detected)
    )
    result = ClarificationResult.parse(response.content)

    # Merge extracted fields into form (never overwrite with None)
    for k, v in result.extracted.items():
        if v is not None:
            form[k] = v

    logger.info(
        "Clarification turn %d: intent_confirmed=%s complete=%s",
        turns + 1, result.intent_confirmed, result.clarification_complete,
    )

    if result.clarification_complete and result.intent_confirmed:
        return _complete_routing(result.intent_confirmed, form, turns + 1)

    # Still collecting — send the next question to the patient
    return {
        "patient_response": result.response,
        "clarification_pending": True,
        "clarification_form": form,
        "clarification_turns": turns + 1,
        "total_cost_usd": state.get("total_cost_usd", 0.0) + response.estimated_cost_usd,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def _complete_routing(intent: str, form: dict, turns: int) -> dict:
    """Return the state update that exits the clarification loop."""
    original_msg = form.get("original_message", "")

    if intent == "UC1":
        # Synthesize a complete symptom description so UC1 has full context
        synthesized = _synthesize_complaint(form)
        effective_message = synthesized or original_msg
    else:
        # UC2/UC3: restore original message so extraction nodes work correctly
        effective_message = original_msg

    return {
        "current_intent": intent,
        "clarification_pending": False,
        "clarification_form": form,
        "clarification_turns": turns,
        "de_identified_message": effective_message,
        "patient_response": None,
    }


def route_after_clarification(state: TriageState) -> str:
    """Still collecting → send question to patient. Done → dispatch to UC."""
    if state.get("clarification_pending"):
        return "question"
    return "route"
