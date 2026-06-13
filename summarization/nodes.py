"""Summarization nodes — compress completed UC context before handoff."""
from __future__ import annotations
from models.state import TriageState
from models.llm import get_llm_client
from prompts.summarization import build_uc1_summary_request, build_uc2_summary_request


async def summarize_uc1_node(state: TriageState) -> dict:
    messages = state.get("messages") or []
    acuity = state.get("acuity", "Low")
    client = get_llm_client()
    response = await client.complete(build_uc1_summary_request(messages, acuity))
    return {
        "uc1_summary": response.content,
        "total_cost_usd": state.get("total_cost_usd", 0.0) + response.estimated_cost_usd,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


async def summarize_uc2_node(state: TriageState) -> dict:
    messages = state.get("messages") or []
    meds = state.get("medications_confirmed") or []
    client = get_llm_client()
    response = await client.complete(build_uc2_summary_request(messages, meds))
    return {
        "uc2_summary": response.content,
        "total_cost_usd": state.get("total_cost_usd", 0.0) + response.estimated_cost_usd,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }
