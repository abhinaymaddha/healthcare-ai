"""UC3 Appointment Booking nodes."""
from __future__ import annotations
import logging
from models.state import TriageState
from tools.patient import get_patient_info, get_appointment_history
from tools.appointment import (
    check_doctor_availability,
    suggest_doctor,
    create_appointment,
)
from prompts.uc3 import (
    build_preference_prompt,
    build_slot_display,
    build_confirmation_prompt,
    build_booking_confirmed,
)

logger = logging.getLogger(__name__)


async def load_patient_and_history_node(state: TriageState) -> dict:
    updates: dict = {}
    if not state.get("patient_id"):
        info = await get_patient_info(state["session_id"])
        updates["patient_id"] = info["patient_id"]
        if not state.get("patient_first_name"):
            updates["patient_first_name"] = info["first_name"]

    history = await get_appointment_history(state.get("patient_id", ""))
    if history.get("preferred_doctor") and not state.get("preferred_doctor"):
        updates["preferred_doctor"] = history["preferred_doctor"]["doctor_id"]

    return updates


async def collect_preferences_node(state: TriageState) -> dict:
    response = build_preference_prompt(
        patient_name=state.get("patient_first_name"),
        reason=state.get("reason_for_visit"),
    )
    return {"patient_response": response}


async def fetch_slots_node(state: TriageState) -> dict:
    messages = state.get("messages") or []
    last = messages[-1].content.lower() if messages else ""

    # Parse visit mode
    visit_mode = "in_person"
    if "telehealth" in last or "online" in last or "virtual" in last:
        visit_mode = "telehealth"

    preferred_doctor = state.get("preferred_doctor")
    reason = state.get("reason_for_visit", "general consultation")

    if preferred_doctor:
        result = await check_doctor_availability(preferred_doctor)
        doctor_name = result["doctor_name"]
        slots = result["available_slots"]
    else:
        result = await suggest_doctor(reason, visit_mode=visit_mode)
        doctor_name = result["suggested_doctor"]["doctor_name"]
        preferred_doctor = result["suggested_doctor"]["doctor_id"]
        slots = result["available_slots"]

    # Filter by mode
    filtered = [s for s in slots if visit_mode in s["mode"]] or slots

    return {
        "preferred_doctor": preferred_doctor,
        "visit_mode": visit_mode,
        "available_slots": filtered[:4],
        "patient_response": build_slot_display(doctor_name, filtered[:4]),
        "selected_slot": None,
    }


async def confirm_appointment_node(state: TriageState) -> dict:
    messages = state.get("messages") or []
    last = messages[-1].content if messages else ""
    slots = state.get("available_slots") or []

    selected = None
    try:
        idx = int(last.strip()) - 1
        if 0 <= idx < len(slots):
            selected = slots[idx]
    except (ValueError, IndexError):
        pass

    if not selected and slots:
        selected = slots[0]

    return {
        "selected_slot": selected,
        "patient_response": build_confirmation_prompt(
            doctor_name="your doctor",
            slot=selected,
            visit_mode=state.get("visit_mode", "in_person"),
            reason=state.get("reason_for_visit", "consultation"),
        ),
    }


async def book_appointment_node(state: TriageState) -> dict:
    slot = state.get("selected_slot") or {}
    result = await create_appointment(
        patient_id=state.get("patient_id", ""),
        doctor_id=state.get("preferred_doctor", ""),
        slot_id=slot.get("slot_id", ""),
        visit_mode=state.get("visit_mode", "in_person"),
        reason_for_visit=state.get("reason_for_visit", "consultation"),
    )

    return {
        "appointment_id": result["appointment_id"],
        "patient_response": build_booking_confirmed(
            confirmation_number=result["confirmation_number"],
            instructions=result["instructions"],
        ),
        "uc3_complete": True,
    }


_PREF_WORDS = [
    "in-person", "in person", "telehealth", "online", "morning", "afternoon",
    "evening", "virtual", "any", "flexible", "dr.", "doctor",
]
_CONFIRM_WORDS = ["yes", "confirm", "book", "ok", "okay", "sure", "yep", "perfect"]


def uc3_resume_router(state: TriageState) -> str:
    """Entry-point router — determines which UC3 step to resume based on state."""
    messages = state.get("messages") or []
    last = messages[-1].content.lower() if messages else ""

    # Slot selected — waiting for patient to confirm or reject
    if state.get("selected_slot") and not state.get("uc3_complete"):
        if any(w in last for w in _CONFIRM_WORDS):
            return "book"
        return "fetch_slots"   # patient wants a different slot

    # Slots shown — patient is picking one
    if state.get("available_slots"):
        return "confirm_slot"

    # Preferences collected (visit_mode set) — fetch available slots
    if state.get("visit_mode"):
        return "fetch_slots"

    # Check if patient is giving preferences in this message
    if any(w in last for w in _PREF_WORDS):
        return "fetch_slots"

    # First turn — ask for preferences
    return "collect_prefs"
