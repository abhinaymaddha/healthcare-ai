"""Mock appointment tools — replace with real scheduling service in production."""
from __future__ import annotations


MOCK_SLOTS = [
    {"slot_id": "S-001", "date": "2026-06-16", "time": "10:00 AM", "mode": "in_person"},
    {"slot_id": "S-002", "date": "2026-06-16", "time": "02:30 PM", "mode": "telehealth"},
    {"slot_id": "S-003", "date": "2026-06-17", "time": "09:00 AM", "mode": "in_person"},
    {"slot_id": "S-004", "date": "2026-06-17", "time": "04:00 PM", "mode": "telehealth"},
    {"slot_id": "S-005", "date": "2026-06-18", "time": "11:30 AM", "mode": "in_person"},
]


async def check_doctor_availability(doctor_id: str, date_preference: str = None) -> dict:
    """Returns available slots for a specific doctor."""
    return {
        "doctor_id": doctor_id,
        "doctor_name": "Dr. Priya Nair",
        "specialty": "General Physician",
        "available_slots": MOCK_SLOTS[:3],
    }


async def suggest_doctor(
    reason_for_visit: str,
    date_preference: str = None,
    visit_mode: str = None,
) -> dict:
    """Suggests an available doctor based on reason and preferences."""
    return {
        "suggested_doctor": {
            "doctor_id": "D-3305",
            "doctor_name": "Dr. Rahul Mehta",
            "specialty": "General Physician",
            "rating": 4.8,
        },
        "available_slots": MOCK_SLOTS[1:4],
    }


async def create_appointment(
    patient_id: str,
    doctor_id: str,
    slot_id: str,
    visit_mode: str,
    reason_for_visit: str,
    appointment_type: str = "new",
) -> dict:
    """Books the appointment and returns confirmation."""
    return {
        "appointment_id": "APT-2026-04421",
        "confirmation_number": "CNF-884920",
        "status": "confirmed",
        "instructions": [
            "Please arrive 10 minutes before your scheduled time.",
            "Carry a valid photo ID and your insurance card if applicable.",
            "You will receive a reminder SMS 2 hours before your appointment.",
        ],
    }
