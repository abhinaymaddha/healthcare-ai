"""UC2 Prescription Refill nodes."""
from __future__ import annotations
import logging
from models.state import TriageState
from models.llm import get_llm_client
from tools.patient import get_patient_info
from tools.prescription import (
    get_standard_quantity,
    check_prescription_history,
    create_prescription_order,
)
from prompts.uc2 import build_extraction_request, MedicationExtractionResult

logger = logging.getLogger(__name__)


def _patient_confirmed(state: TriageState) -> bool:
    messages = state.get("messages") or []
    if not messages:
        return False
    last = messages[-1].content.lower()
    confirm_words = ["yes", "correct", "that's right", "confirm", "looks good", "perfect", "ok", "okay", "sure", "yep"]
    return any(w in last for w in confirm_words)


def uc2_resume_router(state: TriageState) -> str:
    """Entry-point router — determines which UC2 step to resume based on state."""
    medications = state.get("medications_extracted") or []

    if not medications:
        return "extract"

    # Flow already completed — don't re-extract on subsequent turns
    if state.get("uc2_complete"):
        return "confirmation_loop"

    if state.get("uc2_awaiting_confirmation"):
        if _patient_confirmed(state):
            return "check_prescription"
        return "confirmation_loop"   # re-show summary or handle correction

    prescription_status = state.get("prescription_status")
    if prescription_status == "not_found":
        return "handle_offer"

    return "extract"


async def extract_medications_node(state: TriageState) -> dict:
    message = state.get("de_identified_message", "")
    updates: dict = {}

    if not state.get("patient_id"):
        info = await get_patient_info(state["session_id"])
        updates["patient_id"] = info["patient_id"]
        if not state.get("patient_first_name"):
            updates["patient_first_name"] = info["first_name"]

    client = get_llm_client()
    response = await client.complete(build_extraction_request(message))
    extraction = MedicationExtractionResult.parse(response.content)

    # Resolve standard quantities for each extracted medication
    resolved = []
    for med in extraction.medications:
        med_dict = med.model_dump()
        if not med_dict.get("quantity"):
            pack_info = await get_standard_quantity(med.name)
            med_dict["quantity"] = pack_info["quantity"]
            med_dict["pack"] = pack_info["pack"]
        resolved.append(med_dict)

    updates.update({
        "medications_extracted": resolved,
        "uc2_awaiting_confirmation": True,
        "total_cost_usd": state.get("total_cost_usd", 0.0) + response.estimated_cost_usd,
        "llm_calls": state.get("llm_calls", 0) + 1,
    })
    return updates


async def confirmation_loop_node(state: TriageState) -> dict:
    """Show extracted medications to patient and ask for confirmation. Always ends subgraph."""
    medications = state.get("medications_extracted") or []
    first_name = state.get("patient_first_name", "")
    greeting = f"{first_name}, " if first_name else ""

    lines = "\n".join(
        f"  • {m['name']} {m.get('dosage', '')} — {m.get('pack', str(m.get('quantity', '')) + ' units')}"
        for m in medications
    )
    response = (
        f"{greeting}I've noted the following prescription refill request:\n"
        f"{lines}\n\n"
        f"Is this correct? Is there anything else you'd like to add or change?"
    )
    return {
        "patient_response": response,
        "uc2_awaiting_confirmation": True,
    }


async def check_prescription_node(state: TriageState) -> dict:
    patient_id = state.get("patient_id", "")
    medications = state.get("medications_extracted") or []
    result = await check_prescription_history(patient_id, medications)
    status = "found" if result["has_prescription"] else "not_found"

    updates = {
        "medications_confirmed": list(medications),
        "prescription_status": status,
        "uc2_awaiting_confirmation": False,
    }
    if status == "found":
        updates["patient_response"] = (
            "Your prescription has been verified. "
            "Your refill request has been submitted and will be dispatched to your registered address."
        )
        updates["uc2_complete"] = True

    return updates


async def offer_appointment_node(state: TriageState) -> dict:
    """Ask patient whether to book appointment or upload prescription. Ends subgraph."""
    not_found = [m["name"] for m in (state.get("medications_confirmed") or [])]
    names = ", ".join(not_found)
    response = (
        f"We couldn't find a prescription on file for: {names}.\n\n"
        f"Would you like to:\n"
        f"  1. Book a doctor's appointment to review your history and authorize this refill?\n"
        f"  2. Upload a prescription yourself in the app?\n\n"
        f"Please reply 1 or 2."
    )
    return {"patient_response": response}


async def handle_no_prescription_response_node(state: TriageState) -> dict:
    messages = state.get("messages") or []
    last = messages[-1].content.lower() if messages else ""

    if "1" in last or "appointment" in last or "doctor" in last or "book" in last:
        meds = state.get("medications_confirmed") or []
        reason = "Prescription authorization for: " + ", ".join(m["name"] for m in meds)
        return {
            "pending_intent": "UC3",
            "reason_for_visit": reason,
            "uc2_complete": True,
        }
    else:
        patient_id = state.get("patient_id", "")
        medications = state.get("medications_confirmed") or []
        order = await create_prescription_order(patient_id, medications)
        return {
            "order_id": order["order_id"],
            "patient_response": order["message"],
            "uc2_complete": True,
        }


def route_after_prescription_check(state: TriageState) -> str:
    if state.get("prescription_status") == "found":
        return "complete"
    return "offer_appointment"


def route_after_uc2(state: TriageState) -> str:
    if state.get("pending_intent") == "UC3":
        return "summarize"
    return "compliance"
