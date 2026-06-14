"""Safety compliance check and response formatter."""
from __future__ import annotations
import re
import logging
from models.state import TriageState
from guardrail.phi_detector import reidentify_first_name
from prompts.safety import DISCLAIMER, SAFE_FALLBACK

logger = logging.getLogger(__name__)

DIAGNOSIS_PATTERNS = [
    # "you have [condition]" — exclude "you have been" (past-perfect, not diagnostic)
    re.compile(r"\byou\s+(likely |probably |definitely |clearly |obviously )?(have|have got)\b(?!\s+been\b)", re.IGNORECASE),
    # "this sounds/looks/appears/seems like [X]" or "appears to be [X]"
    re.compile(r"\bthis (sounds|looks|appears|seems) (like|to be)\b", re.IGNORECASE),
    # "this could be / might be / is [X]" in a diagnostic assertion context
    re.compile(r"\bthis (could be|might be|is (likely|probably|definitely|clearly))\b", re.IGNORECASE),
    # Explicit diagnosis language
    re.compile(r"\byou('re| are) (suffering from|diagnosed with|presenting with)\b", re.IGNORECASE),
    re.compile(r"\b(the |your )?(diagnosis|condition) is\b", re.IGNORECASE),
    re.compile(r"\bI (would |can )?(diagnose|conclude)\b", re.IGNORECASE),
]

PRESCRIPTION_PATTERNS = [
    re.compile(r"\btake\s+\d+\s*(mg|ml|mcg|units?)\b", re.IGNORECASE),
    re.compile(r"\bstop taking\b", re.IGNORECASE),
    re.compile(r"\bI prescribe\b", re.IGNORECASE),
    re.compile(r"\bincrease (your|the) (dose|dosage)\b", re.IGNORECASE),
]


async def safety_compliance_node(state: TriageState) -> dict:
    reply = state.get("patient_response") or ""
    intent = state.get("current_intent", "?")

    disclaimer_added = False
    if intent == "UC1":
        if DISCLAIMER not in reply:
            reply = reply.rstrip() + f"\n\n{DISCLAIMER}"
            disclaimer_added = True

    violations = []
    for p in DIAGNOSIS_PATTERNS:
        m = p.search(reply)
        if m:
            violations.append(f"diagnosis:{m.group(0)!r}")
    for p in PRESCRIPTION_PATTERNS:
        m = p.search(reply)
        if m:
            violations.append(f"prescription:{m.group(0)!r}")

    if violations:
        logger.warning(
            "  [SAFETY] VIOLATIONS detected — %s → replacing with safe fallback", violations
        )
        return {
            "patient_response": SAFE_FALLBACK,
            "response_blocked": True,
            "block_reason": f"compliance_fail:{','.join(violations)}",
        }

    logger.info(
        "  [SAFETY] OK (intent=%s, disclaimer_added=%s)", intent, disclaimer_added
    )
    return {"patient_response": reply}


async def response_formatter_node(state: TriageState) -> dict:
    """Re-identify first name and finalize patient-facing response."""
    reply = state.get("patient_response") or ""
    lookup = state.get("phi_lookup_table") or {}

    if lookup:
        reply = reidentify_first_name(reply, lookup)

    return {"patient_response": reply}
