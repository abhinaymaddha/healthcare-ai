"""
Emergency companion prompts — medium-size LLM keeps the patient calm
and engaged from dispatch confirmation until emergency services arrive.

Two-phase design:
  Intake  — full conversation history → situation summary + opening message
  Companion — summary + recent messages → brief, calming next response
"""
from __future__ import annotations
import json
import logging
from typing import Optional
from pydantic import BaseModel
from models.llm import LLMConfig, LLMRequest, LLMMessage
from config.llm_configs import MEDIUM_MODEL, DEFAULT_PROVIDER

logger = logging.getLogger(__name__)

_INTAKE_SYSTEM = """\
You are an emergency response coordinator. Emergency services have just been
dispatched to the patient's location.

You have been given the full conversation that led to this emergency dispatch.
Your tasks:
1. Write a concise situation summary (2-3 sentences) capturing the key medical
   facts: what symptoms were reported, any relevant history or medications
   mentioned, and the rough timeline.
2. Write a warm, calm opening message to the patient. It must:
   - Confirm that emergency services are on their way
   - Ask them to stay where they are and stay on the line
   - Ask ONE simple check-in question (e.g., "Can you tell me how you're
     feeling right now?")
   - Be SHORT — 3-4 sentences maximum. The patient is scared.

Output valid JSON only:
{
  "situation_summary": "string",
  "response": "string"
}
"""

_COMPANION_SYSTEM = """\
You are an emergency companion. Emergency services are on their way to this patient.
Your only job is to keep the patient calm, present, and safe until help arrives.

RULES — follow every one, every turn:
- Keep your response SHORT: 2-4 sentences maximum. The patient may be distressed
  or physically unable to read long messages.
- Always acknowledge what the patient just said before anything else.
- End every response with ONE simple question about how they are feeling right now,
  or a gentle instruction to stay still.
- If they seem to be in increasing distress, remind them help is close.
- If they describe unsafe behavior (trying to drive, going outside alone, moving
  when injured), gently ask them to stay still and safe where they are.
- If they say they feel better or want to end the conversation, acknowledge warmly
  and remind them to wait for the emergency team to evaluate them in person.
- NEVER give medical advice, suggest medications, or attempt a diagnosis.
- Be human, warm, and present. They are frightened.
"""


class EmergencyIntakeResult(BaseModel):
    situation_summary: str = ""
    response: str = ""

    @classmethod
    def parse(cls, raw: str) -> "EmergencyIntakeResult":
        try:
            text = raw.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text.strip())
            return cls(
                situation_summary=data.get("situation_summary", ""),
                response=data.get("response", ""),
            )
        except Exception as exc:
            logger.warning("EmergencyIntakeResult.parse failed: %s | raw=%r", exc, raw[:200])
        return cls(
            situation_summary="Emergency dispatch confirmed.",
            response=(
                "Emergency services are on their way to you. "
                "Please stay where you are and keep this conversation open. "
                "Can you tell me how you're feeling right now?"
            ),
        )


def build_intake_request(conversation_history: str) -> LLMRequest:
    user_content = (
        "FULL CONVERSATION HISTORY:\n"
        f"{conversation_history}\n\n"
        "Emergency services have been dispatched. Analyse the situation and generate "
        "the opening companion message as described."
    )
    return LLMRequest(
        config=LLMConfig(
            provider=DEFAULT_PROVIDER,
            model=MEDIUM_MODEL,
            max_tokens=400,
            temperature=0.3,
        ),
        messages=[LLMMessage(role="user", content=user_content)],
        system_prompt=_INTAKE_SYSTEM,
        json_mode=True,
    )


def build_companion_request(
    situation_summary: str,
    recent_context: str,
) -> LLMRequest:
    user_content = (
        f"SITUATION SUMMARY:\n{situation_summary}\n\n"
        f"RECENT CONVERSATION:\n{recent_context}\n\n"
        "Respond to the patient's last message."
    )
    return LLMRequest(
        config=LLMConfig(
            provider=DEFAULT_PROVIDER,
            model=MEDIUM_MODEL,
            max_tokens=200,
            temperature=0.4,
        ),
        messages=[LLMMessage(role="user", content=user_content)],
        system_prompt=_COMPANION_SYSTEM,
        json_mode=False,
    )
