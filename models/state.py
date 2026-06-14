from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages


class TriageState(TypedDict):
    # Session
    session_id: str
    patient_id: Optional[str]
    patient_first_name: Optional[str]
    phi_lookup_table: dict                  # { hash_token: original_value }

    # Conversation history — LangGraph appends via add_messages reducer
    messages: Annotated[list, add_messages]

    # Intent tracking
    current_intent: Optional[str]           # "UC1" | "UC2" | "UC3"
    intent_history: list                    # e.g. ["UC2", "UC3"]
    pending_intent: Optional[str]           # intent to enter after current completes

    # Guardrail outputs
    de_identified_message: Optional[str]
    is_health_related: bool
    needs_escalation: bool
    escalation_signals: list
    diagnosis_demand: bool              # patient is pushing for a specific diagnosis

    # UC1 — Symptom Check
    chief_complaint: Optional[str]
    acuity: Optional[str]                   # "Low" | "Medium" | "High"
    uc1_complete: bool
    uc1_summary: Optional[str]

    # UC2 — Prescription Refill
    medications_extracted: list             # [{ name, dosage, quantity }]
    medications_confirmed: list
    uc2_awaiting_confirmation: bool
    prescription_status: Optional[str]      # "found" | "not_found"
    order_id: Optional[str]
    uc2_complete: bool
    uc2_summary: Optional[str]

    # UC3 — Appointment Booking
    appointment_type: Optional[str]         # "new" | "follow_up"
    visit_mode: Optional[str]               # "in_person" | "telehealth"
    reason_for_visit: Optional[str]
    preferred_doctor: Optional[str]
    available_slots: list
    selected_slot: Optional[dict]
    appointment_id: Optional[str]
    uc3_complete: bool

    # Clarification / intake form
    clarification_pending: bool          # True while asking clarifying questions
    detected_intents: list               # NLI top-2 intents with meaningful scores
    clarification_form: dict             # structured data collected so far
    clarification_turns: int             # safety valve — max 3 turns

    # Emergency / HITL
    awaiting_911_confirmation: bool
    hitl_triggered: bool

    # Response to patient
    patient_response: Optional[str]
    response_blocked: bool
    block_reason: Optional[str]

    # Cost tracking
    total_cost_usd: float
    llm_calls: int
    turn_count: int
