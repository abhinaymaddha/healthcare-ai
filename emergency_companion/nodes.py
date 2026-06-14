"""
Emergency companion subgraph nodes.

Activated once the patient confirms emergency dispatch. The medium-size LLM
takes over the conversation to keep the patient calm and engaged until help
arrives. Two nodes:

  intake_node    — runs once: sends full conversation history to medium LLM
                   to build a situation summary and generate the first message.
  companion_node — runs each subsequent turn: uses summary + recent messages
                   to generate a brief, calming response.
"""
from __future__ import annotations
import logging
from models.state import TriageState
from models.llm import get_llm_client
from prompts.emergency_companion import (
    build_intake_request,
    build_companion_request,
    EmergencyIntakeResult,
)

logger = logging.getLogger(__name__)


def _format_full_history(messages: list) -> str:
    lines = []
    for m in messages:
        role = "Patient" if getattr(m, "type", "") == "human" else "Assistant"
        lines.append(f"{role}: {m.content}")
    return "\n".join(lines)


def _format_recent_context(messages: list, n: int = 6) -> str:
    recent = messages[-n:]
    lines = []
    for m in recent:
        role = "Patient" if getattr(m, "type", "") == "human" else "Assistant"
        lines.append(f"{role}: {m.content}")
    return "\n".join(lines)


async def intake_node(state: TriageState) -> dict:
    """First turn after dispatch confirmed — analyse full history, open companion."""
    messages = state.get("messages") or []
    history = _format_full_history(messages)

    logger.info("  [EMERGENCY INTAKE] Sending %d messages to medium-size LLM", len(messages))

    client = get_llm_client()
    response = await client.complete(build_intake_request(history))
    result = EmergencyIntakeResult.parse(response.content)

    logger.info("  [EMERGENCY INTAKE] Summary: %r", result.situation_summary[:120])

    return {
        "emergency_summary": result.situation_summary,
        "patient_response": result.response,
        "total_cost_usd": state.get("total_cost_usd", 0.0) + response.estimated_cost_usd,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


async def companion_node(state: TriageState) -> dict:
    """Subsequent turns — keep the patient calm until help arrives."""
    messages = state.get("messages") or []
    summary = state.get("emergency_summary", "Emergency dispatch confirmed.")
    recent = _format_recent_context(messages)

    logger.info("  [EMERGENCY COMPANION] Generating response (summary known)")

    client = get_llm_client()
    response = await client.complete(build_companion_request(summary, recent))

    logger.info(
        "  [EMERGENCY COMPANION] Response generated (cost=$%.4f)",
        response.estimated_cost_usd,
    )

    return {
        "patient_response": response.content,
        "total_cost_usd": state.get("total_cost_usd", 0.0) + response.estimated_cost_usd,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def route_emergency_entry(state: TriageState) -> str:
    """First turn → intake (no summary yet). Subsequent turns → companion."""
    return "companion" if state.get("emergency_summary") else "intake"
