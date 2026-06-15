"""
Summarization prompts — compress completed UC context for handoff.

Used when a patient transitions from UC1 → UC3 or UC2 → UC3 mid-session.
The summary replaces a growing message history so the next UC starts with
only the essential context, not the full conversation transcript.
"""
from __future__ import annotations
from app.core.llm import LLMConfig, LLMRequest, LLMMessage
from app.core.config import SMALL_MODEL, DEFAULT_PROVIDER

_MODEL = SMALL_MODEL
_PROVIDER = DEFAULT_PROVIDER

# ── UC1 → UC3 handoff summary ──────────────────────────────────────────────────

_UC1_SYSTEM = """\
You are a clinical documentation specialist preparing a handoff note.
A patient has just completed a symptom triage session and agreed to book
a follow-up appointment. Summarise the interaction for the appointment
booking system.

SUMMARY STRUCTURE (plain prose, 3–5 sentences, no bullet points):
1. Chief complaint (what symptoms the patient described)
2. Duration and severity of symptoms
3. Acuity level assessed (Low / Medium / High)
4. Reason an appointment is recommended

RULES:
• Do not use the patient's name.
• Do not include the medical disclaimer.
• Do not add advice or recommendations beyond what was discussed.
• Write in past tense, clinical but accessible language.
• Maximum 5 sentences.
"""


def build_uc1_summary_request(messages: list, acuity: str) -> LLMRequest:
    transcript = "\n".join(
        f"{getattr(m, 'role', 'unknown').upper()}: {getattr(m, 'content', str(m))}"
        for m in messages[-10:]
    )
    return LLMRequest(
        config=LLMConfig(
            provider=_PROVIDER,
            model=_MODEL,
            max_tokens=200,
            temperature=0.0,
        ),
        messages=[LLMMessage(
            role="user",
            content=(
                f"Acuity assessed: {acuity}\n\n"
                f"Conversation transcript:\n{transcript}\n\n"
                "Write the handoff summary now."
            ),
        )],
        system_prompt=_UC1_SYSTEM,
    )


# ── UC2 → UC3 handoff summary ──────────────────────────────────────────────────

_UC2_SYSTEM = """\
You are a clinical documentation specialist preparing a handoff note.
A patient's prescription refill could not be fulfilled automatically and
they need a doctor's appointment. Summarise the interaction.

SUMMARY STRUCTURE (plain prose, 2–4 sentences):
1. Medications requested (include names and dosages)
2. Why the prescription could not be issued automatically
3. What the patient needs the appointment for

RULES:
• Do not use the patient's name.
• Do not include the medical disclaimer.
• Write in past tense.
• Maximum 4 sentences.
"""


def build_uc2_summary_request(messages: list, medications: list[dict]) -> LLMRequest:
    med_list = ", ".join(
        f"{m['name']} {m.get('dosage', '')}".strip() for m in medications
    )
    transcript = "\n".join(
        f"{getattr(m, 'role', 'unknown').upper()}: {getattr(m, 'content', str(m))}"
        for m in messages[-8:]
    )
    return LLMRequest(
        config=LLMConfig(
            provider=_PROVIDER,
            model=_MODEL,
            max_tokens=150,
            temperature=0.0,
        ),
        messages=[LLMMessage(
            role="user",
            content=(
                f"Medications requested: {med_list}\n\n"
                f"Conversation transcript:\n{transcript}\n\n"
                "Write the handoff summary now."
            ),
        )],
        system_prompt=_UC2_SYSTEM,
    )
