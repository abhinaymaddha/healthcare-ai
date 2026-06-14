"""Health relevance check — keyword fast-pass then NLI for ambiguous cases."""
from __future__ import annotations

# Fast-pass: if ANY of these appear, treat as health-related without NLI call
_HEALTH_KEYWORDS = [
    "symptom", "symptoms", "pain", "ache", "fever", "cough", "headache",
    "nausea", "vomit", "fatigue", "tired", "dizzy", "rash", "bleeding",
    "swelling", "breathing", "chest", "heart", "medication", "medicine",
    "prescription", "refill", "dosage", "dose", "pill", "tablet", "inhaler",
    "appointment", "appointment booking", "doctor", "clinic", "hospital",
    "diagnos", "treatment", "therapy", "surgery", "test result", "blood pressure",
    "blood sugar", "diabetes", "asthma", "anxiety", "depression", "suicid",
    "pregnant", "pregnancy", "injury", "fracture", "infection", "antibiotic",
    "vaccine", "vaccination", "allerg", "eczema", "arthritis", "migraine",
]

_HEALTH_LABEL = (
    "The patient is describing symptoms, requesting a prescription refill, "
    "booking a medical appointment, or asking about medications or health concerns"
)
_NON_HEALTH_LABEL = (
    "The message is about weather, sports, entertainment, cooking, finance, "
    "travel, politics, technology, or other everyday non-medical topics"
)

HEALTH_LABELS = [_HEALTH_LABEL, _NON_HEALTH_LABEL]
_HEALTH_CONFIDENCE_THRESHOLD = 0.5


import logging as _logging
_logger = _logging.getLogger(__name__)


def is_health_related(text: str) -> bool:
    text_lower = text.lower()

    for kw in _HEALTH_KEYWORDS:
        if kw in text_lower:
            _logger.info("  Health: keyword-pass (%r) → HEALTH-RELATED", kw)
            return True

    from models.classifier import top_label
    best, score = top_label(text, HEALTH_LABELS)
    result = best == _HEALTH_LABEL and score >= _HEALTH_CONFIDENCE_THRESHOLD
    label_short = "health" if best == _HEALTH_LABEL else "non-health"
    _logger.info(
        "  Health: NLI → %s (score=%.2f) → %s",
        label_short, score, "HEALTH-RELATED" if result else "NOT HEALTH-RELATED",
    )
    return result
