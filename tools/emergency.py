"""Mock emergency and HITL tools — replace with real dispatch/CRM service in production."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


async def dispatch_emergency_services(patient_id: str, location: str = None) -> dict:
    """Dispatches emergency services to the patient's location."""
    logger.warning(f"[EMERGENCY DISPATCH] patient_id={patient_id} location={location}")
    # In production: POST to emergency dispatch API with patient location
    return {
        "dispatched": True,
        "dispatch_id": "EMG-2026-00123",
        "eta_minutes": 8,
        "message": "Emergency services have been dispatched to your location.",
    }


async def notify_human_reviewer(session_id: str, transcript: list = None) -> dict:
    """Alerts the human service team to review an unresolved emergency session."""
    logger.warning(f"[HITL ALERT] session_id={session_id} — no 911 response, routing to human team")
    # In production: POST to internal CRM/alert system with session transcript
    return {
        "notified": True,
        "ticket_id": "HITL-2026-00089",
        "message": "Our care team has been alerted and will contact you shortly.",
    }
