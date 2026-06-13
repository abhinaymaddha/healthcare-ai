"""Top-level LangGraph graph assembly."""
from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from models.state import TriageState
from guardrail.node import guardrail_node, route_after_guardrail
from guardrail.emergency_node import emergency_node
from intent.router import intent_router_node, route_intent
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
    uc2.add_node("extract_medications",    extract_medications_node)
    uc2.add_node("confirmation_loop",      confirmation_loop_node)
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
    uc3.add_node("collect_prefs",  collect_preferences_node)
    uc3.add_node("fetch_slots",    fetch_slots_node)
    uc3.add_node("confirm_slot",   confirm_appointment_node)
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


def build_graph(checkpointer=None):
    if checkpointer is None:
        checkpointer = MemorySaver()

    uc2_subgraph = _build_uc2_subgraph()
    uc3_subgraph = _build_uc3_subgraph()

    graph = StateGraph(TriageState)

    graph.add_node("guardrail",          guardrail_node)
    graph.add_node("emergency",          emergency_node)
    graph.add_node("intent_router",      intent_router_node)
    graph.add_node("uc1",                symptom_check_node)
    graph.add_node("uc2",                uc2_subgraph)
    graph.add_node("uc3",                uc3_subgraph)
    graph.add_node("summarize_uc1",      summarize_uc1_node)
    graph.add_node("summarize_uc2",      summarize_uc2_node)
    graph.add_node("safety_compliance",  safety_compliance_node)
    graph.add_node("response_formatter", response_formatter_node)

    graph.add_edge(START, "guardrail")

    graph.add_conditional_edges("guardrail", route_after_guardrail, {
        "blocked":    "response_formatter",
        "escalation": "emergency",
        "pass":       "intent_router",
    })

    graph.add_edge("emergency", "response_formatter")

    graph.add_conditional_edges("intent_router", route_intent, {
        "UC1": "uc1",
        "UC2": "uc2",
        "UC3": "uc3",
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
