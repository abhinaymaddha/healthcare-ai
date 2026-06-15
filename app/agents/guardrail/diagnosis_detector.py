"""Diagnosis demand detection — keyword hard-match + soft-signal classifier."""
from __future__ import annotations

HARD_DIAGNOSIS_TERMS = [
    "diagnose me",
    "give me a diagnosis",
    "what is my diagnosis",
    "tell me what disease",
    "tell me what condition",
    "tell me what illness",
    "what disease do i have",
    "what condition do i have",
    "what illness do i have",
    "what do i have",
    "just tell me what i have",
    "what is wrong with me",
    "is it pneumonia",
    "is it covid",
    "is it cancer",
    "is it diabetes",
    "is it lupus",
    "is it flu",
    "do you think it is",
    "skip the disclaimers",
    "skip safety",
    "forget the legal",
    "i give you permission to diagnose",
    "i authorize you to diagnose",
    "override your safety",
    "no restrictions",
]

SOFT_DIAGNOSIS_LABELS = [
    "patient is demanding the AI provide a specific medical diagnosis",
    "patient is describing symptoms and asking for general health guidance",
]


def detect_diagnosis_demand(text: str) -> tuple[bool, str | None]:
    """Returns (is_diagnosis_demand, signal_description)."""
    text_lower = text.lower()

    for term in HARD_DIAGNOSIS_TERMS:
        if term in text_lower:
            return True, f"keyword:{term}"

    from app.core.classifier import top_label
    best, score = top_label(text, SOFT_DIAGNOSIS_LABELS)
    if best == SOFT_DIAGNOSIS_LABELS[0] and score > 0.75:
        return True, f"model:diagnosis_demand(score={score:.2f})"

    return False, None
