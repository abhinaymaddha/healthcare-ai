"""
Static messages for the guardrail and emergency nodes.
These are patient-facing strings — no LLM call involved.
Edit here to change what the patient sees for blocks and emergencies.
"""

# ── Health relevance block ────────────────────────────────────────────────────

BLOCK_NOT_HEALTH = (
    "I'm here to help with health and medical questions. "
    "Your message doesn't appear to be health-related. "
    "If you have a symptom, medication question, or want to book an appointment, "
    "please feel free to share it and I'll be happy to help."
)

# ── Emergency escalation messages ─────────────────────────────────────────────

ASK_DISPATCH = (
    "Your message suggests this could be a medical emergency.\n\n"
    "Should we dispatch emergency services to your location?\n"
    "Please reply YES or NO.\n\n"
    "If this is immediately life-threatening, call 911 now.\n"
    "For mental health crisis support, call or text 988."
)

DISPATCHED_MSG = (
    "Emergency services have been notified and dispatched to your location. "
    "Please stay where you are and keep this chat open. "
    "If your condition worsens before they arrive, call 911 directly."
)

DECLINED_DISPATCH_MSG = (
    "Understood. Please monitor your symptoms closely. "
    "If they worsen or you feel unsafe at any point, call 911 immediately. "
    "Our care team remains available if you need further assistance."
)

HITL_MSG = (
    "Our clinical care team has been alerted and will contact you shortly. "
    "If your situation is immediately life-threatening, please call 911 now. "
    "For mental health crisis support, call or text 988."
)
