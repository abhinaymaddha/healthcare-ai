"""Safety compliance check and response formatter."""
from __future__ import annotations
import re
import logging
from models.state import TriageState
from guardrail.phi_detector import reidentify_first_name
from prompts.safety import DISCLAIMER, SAFE_FALLBACK

logger = logging.getLogger(__name__)

DIAGNOSIS_PATTERNS = [
    re.compile(r"\byou\s+have\b.{0,50}\b(disease|condition|disorder|syndrome|infection|virus|cancer|diabetes)\b", re.IGNORECASE),
    re.compile(r"\bthis is (definitely|clearly|obviously)\b", re.IGNORECASE),
    re.compile(r"\byou('re| are) (suffering from|diagnosed with)\b", re.IGNORECASE),
]

PRESCRIPTION_PATTERNS = [
    re.compile(r"\btake\s+\d+\s*(mg|ml|mcg|units?)\b", re.IGNORECASE),
    re.compile(r"\bstop taking\b", re.IGNORECASE),
    re.compile(r"\bI prescribe\b", re.IGNORECASE),
    re.compile(r"\bincrease (your|the) (dose|dosage)\b", re.IGNORECASE),
]


async def safety_compliance_node(state: TriageState) -> dict:
    reply = state.get("patient_response") or ""

    # Symptom check replies must always have disclaimer
    if state.get("current_intent") == "UC1":
        if DISCLAIMER not in reply:
            reply = reply.rstrip() + f"\n\n{DISCLAIMER}"

    violations = []
    if any(p.search(reply) for p in DIAGNOSIS_PATTERNS):
        violations.append("diagnosis_violation")
    if any(p.search(reply) for p in PRESCRIPTION_PATTERNS):
        violations.append("prescription_violation")

    if violations:
        logger.warning(f"Compliance violations: {violations}")
        return {
            "patient_response": SAFE_FALLBACK,
            "response_blocked": True,
            "block_reason": f"compliance_fail:{','.join(violations)}",
        }

    return {"patient_response": reply}


async def response_formatter_node(state: TriageState) -> dict:
    """Re-identify first name and finalize patient-facing response."""
    reply = state.get("patient_response") or ""
    lookup = state.get("phi_lookup_table") or {}

    if lookup:
        reply = reidentify_first_name(reply, lookup)

    return {"patient_response": reply}
