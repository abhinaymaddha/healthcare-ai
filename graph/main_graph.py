"""Top-level LangGraph graph assembly."""
from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import RetryPolicy

# ---------------------------------------------------------------------------
# Retry tiers — applied per-node based on call criticality.
#
# max_attempts = total attempts (initial + retries):
#   HIGH  → 4 attempts (3 retries)  — emergency companion, clinical reply gen
#   MED   → 3 attempts (2 retries)  — extraction, clarification, appointment
#   LOW   → 2 attempts (1 retry)    — intent classification, summarization
#
# Backoff: 0.5 s → 1 s → 2 s (HIGH), 0.5 s → 1 s (MED), 0.5 s (LOW)
# Jitter is enabled by default to avoid thundering-herd on rate-limit windows.
# ---------------------------------------------------------------------------
_RETRY_HIGH = RetryPolicy(max_attempts=4, initial_interval=0.5, backoff_factor=2.0)
_RETRY_MED  = RetryPolicy(max_attempts=3, initial_interval=0.5, backoff_factor=2.0)
_RETRY_LOW  = RetryPolicy(max_attempts=2, initial_interval=0.5, backoff_factor=2.0)

from models.state import TriageState
from guardrail.node import guardrail_node, route_after_guardrail
from guardrail.emergency_node import emergency_node, route_after_emergency
from intent.router import intent_router_node, route_intent
from emergency_companion.nodes import intake_node, companion_node, route_emergency_entry
from intent.clarification_node import clarification_node, route_after_clarification
from uc1_symptom_check.nodes import symptom_check_node, route_after_uc1
from uc2_prescription_refill.nodes import (
    uc2_resume_router,
    extract_medications_node,
    confirmation_loop_node,
    check_prescription_node,
    offer_appointment_node,
    handle_no_prescription_response_node,
    route_after_prescription_check,
    route_after_uc2,
)
from uc3_appointment_booking.nodes import (
    uc3_resume_router,
    load_patient_and_history_node,
    collect_preferences_node,
    fetch_slots_node,
    confirm_appointment_node,
    book_appointment_node,
)
from summarization.nodes import summarize_uc1_node, summarize_uc2_node
from safety.node import safety_compliance_node, response_formatter_node


def _build_uc2_subgraph():
    uc2 = StateGraph(TriageState)
    # MED retry: extraction + confirmation both call the small LLM
    uc2.add_node("extract_medications",    extract_medications_node,         retry=_RETRY_MED)
    uc2.add_node("confirmation_loop",      confirmation_loop_node,           retry=_RETRY_MED)
    uc2.add_node("check_prescription",     check_prescription_node)
    uc2.add_node("offer_appointment",      offer_appointment_node)
    uc2.add_node("handle_offer",           handle_no_prescription_response_node)

    # Entry: resume router decides which step to run this turn
    uc2.add_conditional_edges(START, uc2_resume_router, {
        "extract":           "extract_medications",
        "confirmation_loop": "confirmation_loop",
        "check_prescription": "check_prescription",
        "handle_offer":      "handle_offer",
    })

    # After extraction always show confirmation summary, then end turn
    uc2.add_edge("extract_medications", "confirmation_loop")
    uc2.add_edge("confirmation_loop", END)

    # After prescription check: either done or ask about appointment
    uc2.add_conditional_edges("check_prescription", route_after_prescription_check, {
        "complete":          END,
        "offer_appointment": "offer_appointment",
    })
    uc2.add_edge("offer_appointment", END)

    # After patient responds to appointment offer
    uc2.add_edge("handle_offer", END)

    return uc2.compile()


def _build_uc3_subgraph():
    uc3 = StateGraph(TriageState)
    uc3.add_node("load_patient",   load_patient_and_history_node)
    # MED retry: collect_prefs and confirm_slot both make LLM calls
    uc3.add_node("collect_prefs",  collect_preferences_node,    retry=_RETRY_MED)
    uc3.add_node("fetch_slots",    fetch_slots_node)
    uc3.add_node("confirm_slot",   confirm_appointment_node,    retry=_RETRY_MED)
    uc3.add_node("book",           book_appointment_node)

    # load_patient always runs first to populate patient info
    uc3.add_edge(START, "load_patient")

    # Resume router decides which step to run after loading patient
    uc3.add_conditional_edges("load_patient", uc3_resume_router, {
        "collect_prefs": "collect_prefs",
        "fetch_slots":   "fetch_slots",
        "confirm_slot":  "confirm_slot",
        "book":          "book",
    })

    # All nodes end the subgraph — no intra-invocation loops
    uc3.add_edge("collect_prefs", END)
    uc3.add_edge("fetch_slots",   END)
    uc3.add_edge("confirm_slot",  END)
    uc3.add_edge("book",          END)

    return uc3.compile()


def _build_emergency_companion_subgraph():
    g = StateGraph(TriageState)
    # HIGH retry: both nodes run during active emergency dispatch
    g.add_node("intake",    intake_node,    retry=_RETRY_HIGH)
    g.add_node("companion", companion_node, retry=_RETRY_HIGH)
    g.add_conditional_edges(START, route_emergency_entry, {
        "intake":    "intake",
        "companion": "companion",
    })
    g.add_edge("intake",    END)
    g.add_edge("companion", END)
    return g.compile()


def build_graph(checkpointer=None):
    if checkpointer is None:
        checkpointer = MemorySaver()

    uc2_subgraph               = _build_uc2_subgraph()
    uc3_subgraph               = _build_uc3_subgraph()
    emergency_companion_subgraph = _build_emergency_companion_subgraph()

    graph = StateGraph(TriageState)

    # No retry — pure local logic, no LLM calls
    graph.add_node("guardrail",           guardrail_node)
    graph.add_node("emergency",           emergency_node)
    graph.add_node("safety_compliance",   safety_compliance_node)
    graph.add_node("response_formatter",  response_formatter_node)

    # Retry tiers for LLM-calling nodes
    graph.add_node("emergency_companion", emergency_companion_subgraph)           # inner nodes carry HIGH retry
    graph.add_node("uc1",                symptom_check_node,  retry=_RETRY_HIGH) # medium LLM, clinical reply
    graph.add_node("clarification",      clarification_node,  retry=_RETRY_MED)  # small LLM, routing-critical
    graph.add_node("intent_router",      intent_router_node,  retry=_RETRY_LOW)  # small LLM, NLI fallback exists
    graph.add_node("uc2",                uc2_subgraph)                            # inner nodes carry MED retry
    graph.add_node("uc3",                uc3_subgraph)                            # inner nodes carry MED retry
    graph.add_node("summarize_uc1",      summarize_uc1_node,  retry=_RETRY_LOW)  # small LLM, non-blocking
    graph.add_node("summarize_uc2",      summarize_uc2_node,  retry=_RETRY_LOW)  # small LLM, non-blocking

    graph.add_edge(START, "guardrail")

    graph.add_conditional_edges("guardrail", route_after_guardrail, {
        "blocked":             "response_formatter",
        "escalation":          "emergency",
        "emergency_companion": "emergency_companion",
        "pass":                "intent_router",
    })

    graph.add_conditional_edges("emergency", route_after_emergency, {
        "emergency_companion": "emergency_companion",
        "response_formatter":  "response_formatter",
    })

    graph.add_edge("emergency_companion", "response_formatter")

    graph.add_conditional_edges("intent_router", route_intent, {
        "UC1":           "uc1",
        "UC2":           "uc2",
        "UC3":           "uc3",
        "clarification": "clarification",
    })

    # Clarification loop: ask a question → safety_compliance (adds disclaimer) → patient
    graph.add_conditional_edges("clarification", route_after_clarification, {
        "question": "safety_compliance",  # still collecting → add disclaimer → send to patient
        "route":    "intent_router",      # confirmed → dispatch to UC
    })

    graph.add_conditional_edges("uc1", route_after_uc1, {
        "summarize":  "summarize_uc1",
        "compliance": "safety_compliance",
    })
    graph.add_edge("summarize_uc1", "uc3")

    graph.add_conditional_edges("uc2", route_after_uc2, {
        "summarize":  "summarize_uc2",
        "compliance": "safety_compliance",
    })
    graph.add_edge("summarize_uc2", "uc3")

    graph.add_edge("uc3",                "safety_compliance")
    graph.add_edge("safety_compliance",  "response_formatter")
    graph.add_edge("response_formatter", END)

    return graph.compile(checkpointer=checkpointer)
