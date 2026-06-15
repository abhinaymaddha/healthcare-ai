"""
Clarification node — LLM prompt for iterative intake form collection.

The clarification node asks one focused question per turn until intent is
confirmed and enough clinical detail is collected to route safely.
"""
from __future__ import annotations
import json
import logging
from typing import Optional
from pydantic import BaseModel
from app.core.llm import LLMConfig, LLMRequest, LLMMessage
from app.core.config import SMALL_MODEL, DEFAULT_PROVIDER

logger = logging.getLogger(__name__)

_MODEL = SMALL_MODEL
_PROVIDER = DEFAULT_PROVIDER

# ── Output schema ──────────────────────────────────────────────────────────────

class ClarificationResult(BaseModel):
    extracted: dict = {}
    intent_confirmed: Optional[str] = None
    clarification_complete: bool = False
    response: str = ""

    @classmethod
    def parse(cls, raw: str) -> "ClarificationResult":
        try:
            text = raw.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text.strip())
            return cls(
                extracted=data.get("extracted") or {},
                intent_confirmed=data.get("intent_confirmed"),
                clarification_complete=bool(data.get("clarification_complete", False)),
                response=data.get("response", ""),
            )
        except Exception as exc:
            logger.warning("ClarificationResult.parse failed: %s | raw=%r", exc, raw[:200])
        return cls(response="Could you tell me a bit more about what you're experiencing?")


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """\
You are a clinical intake specialist for a telehealth triage assistant.
A patient message has triggered multiple possible workflows, or the intent
is unclear. Ask ONE focused question per turn to clarify what the patient
needs and collect the most critical missing clinical detail.

INTENT DEFINITIONS
------------------
UC1: Patient needs health guidance for symptoms they are experiencing
UC2: Patient wants to refill an existing prescription
UC3: Patient wants to book a doctor's appointment

OUTPUT — valid JSON only, no other text:
{
  "extracted": {
    "primary_concern": "string or null",
    "severity":        "mild|moderate|severe|null",
    "duration":        "string or null",
    "onset":           "sudden|gradual|null",
    "emergency_signs": true|false|null
  },
  "intent_confirmed":      "UC1|UC2|UC3|null",
  "clarification_complete": false,
  "response":              "your message to the patient"
}

QUESTION PRIORITY (ask in this order, skip if already known)
-------------------------------------------------------------
1. EMERGENCY SAFETY (ALL intents) — if any symptoms are mentioned and
   emergency_signs is not yet established, ask ONE question covering:
   chest tightness, sudden vision changes, weakness or numbness in arms
   or legs, or a headache that is the worst they have ever had.
2. SEVERITY (UC1 ONLY) — how bad is the primary symptom on a mild/moderate/severe scale.
3. DURATION (UC1 ONLY) — how long has this been going on.
4. PRIMARY NEED (if intent still unclear) — is it guidance, a refill, or an appointment?

COMPLETION RULES — set clarification_complete=true as soon as ALL conditions are met:
    UC1: intent_confirmed="UC1" AND severity known AND duration known
    UC2: intent_confirmed="UC2" AND the medication name or condition is clear
    UC3: intent_confirmed="UC3" AND the reason for the visit is clear
         AND (no symptoms were mentioned OR emergency_signs is already established)

RULES
-----
- Ask exactly ONE question per turn. Never combine two questions.
- For UC2 and UC3: do NOT ask about severity or duration — those are clinical
  questions for the doctor, not needed for routing. Mark complete as soon as
  the completion rule above is satisfied.
- If emergency_signs=true: set intent_confirmed=null,
  clarification_complete=false, and ask the patient to describe the sign
  so the next turn can escalate properly.
- Be warm, brief, and human. Do not explain the triage process to the patient.
- Acknowledge distress in one sentence before asking if the patient seems upset.
- Format: plain prose only, no lists, no markdown.
"""


# ── Request builder ────────────────────────────────────────────────────────────

def build_clarification_request(
    conversation_context: str,
    form: dict,
    detected_intents: list[str],
) -> LLMRequest:
    known = {k: v for k, v in form.items() if v is not None and k != "original_message"}
    user_content = (
        f"CONVERSATION:\n{conversation_context}\n\n"
        f"POSSIBLE INTENTS: {', '.join(detected_intents)}\n"
        f"INFORMATION COLLECTED SO FAR: {json.dumps(known) if known else 'nothing yet'}\n\n"
        "Extract any new information from the last patient message. "
        "Then decide: is clarification complete? If not, ask the next priority question."
    )
    return LLMRequest(
        config=LLMConfig(
            provider=_PROVIDER,
            model=_MODEL,
            max_tokens=300,
            temperature=0.3,
        ),
        messages=[LLMMessage(role="user", content=user_content)],
        system_prompt=_SYSTEM,
        json_mode=True,
    )
