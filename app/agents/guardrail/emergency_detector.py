"""Emergency escalation detection — keyword hard-match + soft-signal classifier."""
from __future__ import annotations

HARD_ESCALATION_TERMS = [
    # Cardiac
    "chest pain", "chest pressure", "chest tightness", "heart attack", "cardiac arrest",
    "left arm pain", "jaw pain",
    # Respiratory
    "can't breathe", "cannot breathe", "difficulty breathing", "trouble breathing",
    "shortness of breath", "throat closing", "anaphylaxis",
    # Stroke / neuro
    "stroke", "face drooping", "face is drooping", "sudden weakness", "sudden numbness",
    "can't speak", "cannot speak", "arm is numb", "arm went numb",
    "cannot move my", "can't move my", "slurred speech",
    "worst headache of my life", "worst headache i've ever had", "thunderclap headache",
    "stiff neck", "neck stiffness",
    # Pre-syncope
    "feel like i might pass out", "i might pass out", "might pass out", "about to pass out",
    "going to pass out", "feel like i'm going to faint",
    # Bleeding
    "can't stop bleeding", "cannot stop bleeding", "cannot stop the bleeding",
    "can't stop the bleeding", "bleeding heavily", "severe bleeding",
    # Overdose / accidental ingestion
    "overdose", "took too many pills", "swallowed too much",
    "accidentally took", "accidental overdose", "took double", "double dose",
    "took too much medication", "took too much of my",
    # Mental health crisis — explicit
    "kill myself", "killing myself", "want to die", "suicidal",
    "end my life", "ending my life", "ended my life",
    "hurting myself", "self-harm", "self harm", "cutting myself", "take my own life",
    "i want to kill", "planning to kill", "going to kill myself",
    # Mental health crisis — soft / indirect (high-lethality signals)
    "don't want to be here anymore", "do not want to be here",
    "not sure i want to be here", "not sure if i want to be here",
    "want to disappear forever", "thinking about disappearing",
    "better off without me", "better without me", "everyone would be better off",
    "no reason to live", "no point in living", "no reason to continue",
    "any reason to continue", "reason to continue",
    "can't go on anymore", "cannot go on",
    "wish i was dead", "wish i were dead", "wish i wasn't alive",
    "end it all", "ending it all",
    "did not wake up", "if i didn't wake up", "if i don't wake up",
    "goodbye letter", "giving away my things",
    "have a plan to", "have a plan to end", "means to end",
    # Overdose intent
    "pills in front of me", "thinking of taking all of them", "about to take all of them",
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
    from app.core.classifier import top_label
    best, score = top_label(text, SOFT_ESCALATION_LABELS)
    if best == SOFT_ESCALATION_LABELS[0] and score > 0.70:
        signals.append(f"model:emergency_signal(score={score:.2f})")
        return True, signals

    return False, []
