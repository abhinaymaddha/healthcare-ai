"""Mock prescription tools — replace with real pharmacy/EHR service in production."""
from __future__ import annotations


STANDARD_QUANTITIES = {
    "paracetamol":   {"quantity": 10, "unit": "tablets", "pack": "sheet of 10"},
    "amoxicillin":   {"quantity": 21, "unit": "capsules", "pack": "box of 21"},
    "metformin":     {"quantity": 60, "unit": "tablets", "pack": "box of 60"},
    "lisinopril":    {"quantity": 30, "unit": "tablets", "pack": "box of 30"},
    "atorvastatin":  {"quantity": 30, "unit": "tablets", "pack": "box of 30"},
    "omeprazole":    {"quantity": 28, "unit": "capsules", "pack": "box of 28"},
    "levothyroxine": {"quantity": 30, "unit": "tablets", "pack": "box of 30"},
    "cytosine":      {"quantity": 20, "unit": "tablets", "pack": "box of 20"},
    "ibuprofen":     {"quantity": 24, "unit": "tablets", "pack": "pack of 24"},
    "cetirizine":    {"quantity": 10, "unit": "tablets", "pack": "sheet of 10"},
}

DEFAULT_PACK = {"quantity": 30, "unit": "tablets", "pack": "box of 30"}


async def get_standard_quantity(medication_name: str) -> dict:
    """Returns default pack size for a medication."""
    key = medication_name.lower().strip()
    return STANDARD_QUANTITIES.get(key, DEFAULT_PACK)


async def check_prescription_history(patient_id: str, medications: list[dict]) -> dict:
    """Checks if patient has a valid prescription or prior purchase for these medications."""
    # Mock: paracetamol always found, others not found
    found = []
    not_found = []
    for med in medications:
        name = med.get("name", "").lower()
        if name in ("paracetamol", "cetirizine", "ibuprofen"):
            found.append(med["name"])
        else:
            not_found.append(med["name"])

    return {
        "has_prescription": len(not_found) == 0,
        "found": found,
        "not_found": not_found,
        "previous_purchase": len(found) > 0,
    }


async def create_prescription_order(
    patient_id: str,
    medications: list[dict],
    status: str = "pending_prescription",
) -> dict:
    """Creates a prescription order in pending state."""
    return {
        "order_id": "RX-2026-00847",
        "status": status,
        "medications": medications,
        "message": (
            "Your order has been created. Please upload your doctor's prescription "
            "in the app to proceed. Our team will verify and dispatch once confirmed."
        ),
    }
