"""
UC2 Prescription Refill — medication extraction prompt + output schema.

Prompt engineering decisions:
- Schema printed verbatim in prompt so model knows exact field names
- Names are preserved verbatim as stated by the patient; no brand→generic
  substitution is made at extraction time. Alternatives can be offered
  during confirmation, but that is a clinical/formulary decision, not
  an extraction one.
- Concrete few-shot example with two medications shows multi-med handling
- json_mode=True enforces valid JSON at the API level (OpenRouter/OpenAI)
- MedicationExtractionResult.parse() handles malformed output gracefully
"""
from __future__ import annotations
import json
import logging
from typing import Optional
from pydantic import BaseModel
from models.llm import LLMConfig, LLMRequest, LLMMessage

logger = logging.getLogger(__name__)

_MODEL = "anthropic/claude-haiku-4-5"
_PROVIDER = "openrouter"

# ── Output schema ─────────────────────────────────────────────────────────────

class Medication(BaseModel):
    name: str
    dosage: Optional[str] = None
    quantity: Optional[int] = None
    pack: Optional[str] = None      # filled in by tools layer, not the LLM


class MedicationExtractionResult(BaseModel):
    medications: list[Medication] = []

    @classmethod
    def parse(cls, raw: str) -> "MedicationExtractionResult":
        try:
            text = raw.strip()
            # Strip markdown code fences if the model ignored json_mode
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text.strip())
            meds = data.get("medications", data) if isinstance(data, dict) else data
            if isinstance(meds, list):
                return cls(medications=[Medication(**m) for m in meds])
        except Exception as exc:
            logger.warning("MedicationExtractionResult.parse failed: %s | raw=%r", exc, raw[:200])
        return cls(medications=[])


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """\
You are a clinical data extraction specialist for a telehealth prescription system.
Extract all medication refill requests from the patient message and return
structured JSON. Return NOTHING except valid JSON — no explanation, no markdown.

OUTPUT SCHEMA
-------------
{
  "medications": [
    {
      "name": "string  — exactly as stated by the patient",
      "dosage": "string | null  — as stated by patient, include units",
      "quantity": null
    }
  ]
}

EXTRACTION RULES
----------------
1. Extract ALL medications mentioned in a single message.
2. Preserve the medication name EXACTLY as the patient stated it. Do NOT
   substitute brand names for generic equivalents or vice versa. If the
   patient says "Tylenol", record "Tylenol". If the patient says
   "paracetamol", record "paracetamol". Brand-vs-generic decisions require
   clinical and formulary authorization — they must never be made silently
   at extraction time.
3. If the patient says "my blood pressure medication" without naming it,
   use the descriptive phrase as the name (e.g. "blood pressure medication").
4. Include dosage exactly as stated; use null if not mentioned.
5. Always set quantity to null — the system resolves standard pack sizes.
6. If no medication is mentioned, return: {"medications": []}

EXAMPLE
-------
Patient message: "I need to refill my Glucophage 500mg and my Zestril"
Output:
{
  "medications": [
    {"name": "Glucophage", "dosage": "500mg", "quantity": null},
    {"name": "Zestril", "dosage": null, "quantity": null}
  ]
}
"""


# ── Request builder ────────────────────────────────────────────────────────────

def build_extraction_request(de_identified_message: str) -> LLMRequest:
    return LLMRequest(
        config=LLMConfig(
            provider=_PROVIDER,
            model=_MODEL,
            max_tokens=300,
            temperature=0.0,
        ),
        messages=[LLMMessage(
            role="user",
            content=f'Patient message: "{de_identified_message}"\n\nExtract medications:',
        )],
        system_prompt=_SYSTEM,
        json_mode=True,
    )
