"""Mock patient tools — replace with real service calls in production."""
from __future__ import annotations


async def get_patient_info(session_id: str) -> dict:
    """Returns patient profile for the given session."""
    return {
        "patient_id": "P-10042",
        "first_name": "Arjun",
        "last_name": "Sharma",
        "date_of_birth": "1990-03-15",
        "phone": "+91-9876543210",
        "email": "arjun.sharma@email.com",
        "registered": True,
    }


async def get_appointment_history(patient_id: str) -> dict:
    """Returns prior appointment and doctor relationship for the patient."""
    return {
        "has_prior_appointments": True,
        "last_appointment": {
            "date": "2026-03-10",
            "doctor_id": "D-2201",
            "doctor_name": "Dr. Priya Nair",
            "specialty": "General Physician",
        },
        "preferred_doctor": {
            "doctor_id": "D-2201",
            "doctor_name": "Dr. Priya Nair",
            "specialty": "General Physician",
        },
    }
