"""
Intent classification prompt — few-shot, structured JSON output.

Used when the local NLI classifier scores below the confidence threshold
and a Haiku call is made to confirm the intent.
"""
from __future__ import annotations
import json
import logging
from typing import Literal
from pydantic import BaseModel
from models.llm import LLMConfig, LLMRequest, LLMMessage

logger = logging.getLogger(__name__)

_MODEL = "anthropic/claude-haiku-4-5"
_PROVIDER = "openrouter"

# ── Output schema ─────────────────────────────────────────────────────────────

class IntentResult(BaseModel):
    intent: Literal["UC1", "UC2", "UC3"]

    @classmethod
    def parse(cls, raw: str) -> "IntentResult":
        try:
            data = json.loads(raw.strip())
            return cls(intent=data["intent"])
        except Exception:
            # Last-resort: scan for UC token in the raw string
            for uc in ("UC1", "UC2", "UC3"):
                if uc in raw.upper():
                    return cls(intent=uc)  # type: ignore[arg-type]
            logger.warning("IntentResult.parse: could not extract intent from: %r", raw[:100])
            return cls(intent="UC1")   # safe default


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """\
You are a medical intent classifier for a telehealth triage system.
Classify the patient message into exactly one of three categories.

CATEGORIES
----------
UC1 – Symptom Check
  The patient is describing a symptom, health concern, illness, pain,
  mental health issue, or any physical condition they need guidance on.

UC2 – Prescription Refill
  The patient wants to refill, renew, or reorder an existing prescription
  or medication. May also mention a symptom alongside the refill request.

UC3 – Appointment Booking
  The patient explicitly wants to book, schedule, or reschedule a
  medical appointment or consultation.

TIE-BREAKING RULES
------------------
- Message contains symptoms AND a refill request → UC2
  (the refill is the actionable task; symptoms will surface in context)
- Message contains symptoms AND an appointment request → UC3
- Message intent is completely unclear → default to UC1

OUTPUT FORMAT
-------------
Return ONLY valid JSON — no explanation, no markdown, nothing else:
{"intent": "UC1"}

EXAMPLES
--------
"I have had a persistent cough for two weeks"
→ {"intent": "UC1"}

"My knee has been swelling and I'm in a lot of pain"
→ {"intent": "UC1"}

"I've been feeling very anxious and not sleeping"
→ {"intent": "UC1"}

"I need to refill my metformin 500mg"
→ {"intent": "UC2"}

"Can I get a refill for my blood pressure tablets"
→ {"intent": "UC2"}

"I need my inhaler refilled and also have a bad chest cough"
→ {"intent": "UC2"}

"I want to book an appointment with my doctor"
→ {"intent": "UC3"}

"Can I schedule a telehealth consultation for next week"
→ {"intent": "UC3"}

"I have a rash and want to see a doctor as soon as possible"
→ {"intent": "UC3"}
"""


# ── Request builder ────────────────────────────────────────────────────────────

def build_intent_request(message: str) -> LLMRequest:
    return LLMRequest(
        config=LLMConfig(
            provider=_PROVIDER,
            model=_MODEL,
            max_tokens=20,
            temperature=0.0,
        ),
        messages=[LLMMessage(
            role="user",
            content=f'Patient message: "{message}"\n\nClassify:',
        )],
        system_prompt=_SYSTEM,
        json_mode=True,
    )
