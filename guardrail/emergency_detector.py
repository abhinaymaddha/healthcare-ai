"""Emergency escalation detection — keyword hard-match + soft-signal classifier."""
from __future__ import annotations

HARD_ESCALATION_TERMS = [
    # Cardiac
    "chest pain", "chest pressure", "chest tightness", "heart attack", "cardiac arrest",
    "left arm pain", "jaw pain",
    # Respiratory
    "can't breathe", "cannot breathe", "difficulty breathing", "trouble breathing",
    "shortness of breath", "throat closing", "anaphylaxis",
    # Stroke
    "stroke", "face drooping", "sudden weakness", "sudden numbness", "can't speak",
    # Bleeding
    "can't stop bleeding", "bleeding heavily", "severe bleeding",
    # Overdose
    "overdose", "took too many pills", "swallowed too much",
    # Mental health crisis
    "kill myself", "killing myself", "want to die", "suicidal", "end my life",
    "hurting myself", "self-harm", "self harm", "cutting myself", "take my own life",
    # Other
    "unconscious", "not breathing", "seizure", "convulsing", "epipen",
]

SOFT_ESCALATION_LABELS = [
    "a medical emergency or life-threatening crisis",
    "a routine health question or general inquiry",
]


def detect_escalation(text: str) -> tuple[bool, list[str]]:
    """Returns (needs_escalation, list_of_signals)."""
    text_lower = text.lower()
    signals = []

    for term in HARD_ESCALATION_TERMS:
        if term in text_lower:
            signals.append(f"keyword:{term}")

    if signals:
        return True, signals

    # Soft signal — uses the shared model singleton (already loaded at startup)
    from models.classifier import top_label
    best, score = top_label(text, SOFT_ESCALATION_LABELS)
    if best == SOFT_ESCALATION_LABELS[0] and score > 0.55:
        signals.append(f"model:emergency_signal(score={score:.2f})")
        return True, signals

    return False, []
