"""
UC3 Appointment Booking — response templates.

UC3 nodes build responses from templates (no LLM call needed for the
preference-collection and slot-display steps). Using an LLM here adds
latency and cost with no quality gain — the information is fully
structured and can be rendered deterministically.

If future requirements call for more conversational slot negotiation,
add an LLM builder here and update the node.
"""
from __future__ import annotations


def build_preference_prompt(patient_name: str | None, reason: str | None) -> str:
    """Preference collection message shown to the patient on first UC3 turn."""
    greeting = f"{patient_name}, " if patient_name else ""
    reason_note = f" regarding {reason}" if reason else ""
    return (
        f"{greeting}I'll help you book an appointment{reason_note}.\n\n"
        "A few quick questions so I can find the best slot for you:\n\n"
        "  1. Would you prefer an in-person visit or a telehealth consultation?\n"
        "  2. Do you have a preferred date or time of day (morning / afternoon / evening)?\n"
        "  3. Do you have a preferred doctor, or would you like me to suggest one?"
    )


def build_slot_display(doctor_name: str, slots: list[dict]) -> str:
    """Slot listing shown to the patient after availability is fetched."""
    lines = "\n".join(
        f"  {i + 1}. {s['date']} at {s['time']} ({s['mode'].replace('_', '-')})"
        for i, s in enumerate(slots)
    )
    return (
        f"Here are the available slots with {doctor_name}:\n\n"
        f"{lines}\n\n"
        "Which would you prefer? Please reply with the number."
    )


def build_confirmation_prompt(
    doctor_name: str,
    slot: dict,
    visit_mode: str,
    reason: str,
) -> str:
    """Booking confirmation summary shown before the patient confirms."""
    mode_label = visit_mode.replace("_", "-")
    return (
        f"Here's your appointment summary:\n\n"
        f"  Doctor  : {doctor_name}\n"
        f"  Date    : {slot.get('date', 'TBC')}\n"
        f"  Time    : {slot.get('time', 'TBC')}\n"
        f"  Type    : {mode_label}\n"
        f"  Reason  : {reason}\n\n"
        "Shall I confirm this booking? Reply Yes to confirm or No to choose a different slot."
    )


def build_booking_confirmed(confirmation_number: str, instructions: list[str]) -> str:
    """Success message shown after the appointment is booked."""
    instruction_text = "\n".join(f"  • {i}" for i in instructions)
    return (
        f"Your appointment is confirmed! Reference number: {confirmation_number}\n\n"
        f"A few things to note before your visit:\n{instruction_text}"
    )
