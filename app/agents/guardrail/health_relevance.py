"""Health relevance — three-tier: non-health blocklist → health keywords → NLI bands."""
from __future__ import annotations
from enum import Enum
import logging

_logger = logging.getLogger(__name__)


class HealthRelevance(str, Enum):
    HEALTH = "health"         # clearly health-related → pass to intent router
    AMBIGUOUS = "ambiguous"   # unclear → route to clarification ("tell me more")
    NOT_HEALTH = "not_health" # clearly off-topic → block


# ── Tier 1: Fast-reject for unambiguously non-health topics ──────────────────
# ONLY include terms that have NO plausible health meaning.
# Keep this list small — the NLI handles everything in between.
_NON_HEALTH_BLOCKLIST = [
    # Sports jargon with no medical use
    "touchdown", "slam dunk", "hat trick", "offside rule", "penalty kick",
    "quarterback", "home run", "football match", "basketball game",
    "soccer game", "baseball game",
    # Finance instruments
    "stock ticker", "stock market crash", "cryptocurrency price", "bitcoin price",
    "forex trading", "mutual fund returns", "dividend yield", "hedge fund",
    "interest rate hike", "stock price", "share price", "stock market",
    "investment portfolio",
    # Entertainment
    "movie review", "film review", "album release", "concert ticket",
    "box office", "netflix show", "spotify playlist",
    "tell me a joke", "funny joke", "tell me a funny", "dad joke",
    # Politics
    "election results", "political party", "congress vote", "senate bill",
    "campaign rally", "polling data",
    # Travel (non-medical)
    "flight booking", "hotel reservation", "visa application", "travel itinerary",
    "planning my vacation", "book a flight", "travel to",
    # Technology / general knowledge (no health relevance)
    "sorting algorithm", "bubble sort", "quicksort", "binary search",
    "programming language", "machine learning model",
    "what is the capital of", "capital city of",
    "recipe for", "how to cook", "cooking instructions",
    "weather forecast", "what is the weather",
]

# ── Tier 2: Health keyword fast-pass (skip NLI for clear health messages) ────
# These are unambiguously medical — match means pass without an NLI call.
_HEALTH_KEYWORDS = [
    # Symptoms — unambiguous
    "symptom", "pain", "ache", "aching", "hurting", "sore throat",
    "fever", "cough", "headache", "migraine",
    "nausea", "vomit", "vomiting",
    "fatigue", "tired", "tiredness",
    "dizzy", "dizziness",
    "rash", "bleed", "bleeding",
    "swelling", "swollen",
    "shortness of breath",
    "chest pain", "chest pressure", "chest tightness",
    "heart palpitation", "palpitation",
    "lump", "bump", "bruise", "cut", "wound", "injury", "fracture", "sprain",
    "cramp", "spasm", "itch", "itching", "discharge",
    "numbness", "numb", "tingle", "tingling",
    "faint", "fainted", "weakness", "edema",
    "bloat", "bloating", "diarrhea", "constipat",
    "earache", "lymph node", "gland",
    "sweat", "sweating", "night sweats",
    "back pain", "backache",
    # Cardiac
    "heart", "cardiac", "palpitat",
    # Vision / neurological — explicit
    "vision loss", "blurry vision", "blurred vision",
    "slurred speech", "aphasia", "speak", "speech",
    "cannot speak", "can't speak",
    # Mental health — disappear signal
    "disappear", "disappearing",
    "indigestion", "heartburn", "stomach pain", "abdominal pain",
    # Mental health — stable
    "mental health", "anxiety disorder", "panic attack",
    "depression", "depressed", "grief",
    "insomnia", "trauma", "ptsd",
    "hopeless", "helpless", "worthless",
    "feel like a burden",
    # Mental health — crisis (must reach emergency detector fast)
    "suicid", "self-harm", "self harm", "hurt myself", "harm myself",
    "want to die", "wish i was dead",
    "don't want to be here", "not want to be here",
    "ending my life", "end my life", "end it all",
    "goodbye letter",
    "no reason to live", "no point in living",
    "can't go on", "cannot go on",
    "better off without me",
    "did not wake up",
    # Medications / prescriptions
    "medication", "medicine", "prescription", "refill", "dosage",
    "dose", "pill", "tablet", "capsule", "inhaler", "injection", "insulin",
    "antibiotic", "steroid", "antidepressant", "blood thinner",
    # Care access
    "appointment", "doctor", "physician", "clinic", "hospital", "specialist",
    "telehealth", "checkup", "check-up", "follow-up", "referral",
    # Conditions (explicit)
    "diagnos", "treatment", "surgery", "test result",
    "blood pressure", "blood sugar", "diabetes", "asthma",
    "pregnant", "pregnancy", "infection", "vaccine", "vaccination",
    "allerg", "eczema", "arthritis", "hypertension", "cholesterol",
    "cancer", "tumor", "thyroid", "kidney", "liver", "stroke", "seizure",
    # Lifestyle — explicit health framing only
    "vitamin", "supplement", "weight loss plan",
    "dehydrat", "sick", "ill", "unwell", "not feeling well",
    # Medical system / meta health references
    "medical", "health question", "health concern", "medical advice",
    "ibuprofen", "paracetamol", "acetaminophen", "amoxicillin",
]

# ── NLI labels ────────────────────────────────────────────────────────────────
_HEALTH_LABEL = (
    "The patient is describing symptoms, requesting a prescription refill, "
    "booking a medical appointment, or asking about medications or health concerns"
)
_NON_HEALTH_LABEL = (
    "The message is about weather, sports, entertainment, cooking, finance, "
    "travel, politics, technology, or other everyday non-medical topics"
)

# Raw DeBERTa entailment logit thresholds for the health label.
# >= _NLI_HIGH : confident health signal → HEALTH
# >= _NLI_LOW  : weak / unclear signal   → AMBIGUOUS (route to clarification)
# <  _NLI_LOW  : clear non-health signal → NOT_HEALTH (block)
_NLI_HIGH = 0.5
_NLI_LOW  = 0.1


def check_health_relevance(text: str) -> HealthRelevance:
    """Three-tier health relevance check: blocklist → keywords → NLI bands."""
    text_lower = text.lower()

    # Tier 1: Non-health blocklist — fast reject
    for term in _NON_HEALTH_BLOCKLIST:
        if term in text_lower:
            _logger.info("  Health: blocklist hit (%r) → NOT_HEALTH", term)
            return HealthRelevance.NOT_HEALTH

    # Tier 2: Health keyword fast-pass — skip NLI
    for kw in _HEALTH_KEYWORDS:
        if kw in text_lower:
            _logger.info("  Health: keyword-pass (%r) → HEALTH", kw)
            return HealthRelevance.HEALTH

    # Tier 3: NLI with confidence bands
    from app.core.classifier import all_scores
    scores = all_scores(text, [_HEALTH_LABEL, _NON_HEALTH_LABEL])
    health_score = scores[_HEALTH_LABEL]
    non_health_score = scores[_NON_HEALTH_LABEL]

    if health_score >= _NLI_HIGH:
        result = HealthRelevance.HEALTH
    elif health_score >= _NLI_LOW:
        result = HealthRelevance.AMBIGUOUS
    else:
        result = HealthRelevance.NOT_HEALTH

    _logger.info(
        "  Health: NLI health=%.2f non_health=%.2f → %s",
        health_score, non_health_score, result.value,
    )
    return result


def is_health_related(text: str) -> bool:
    """Backward-compatible wrapper — returns False only for NOT_HEALTH."""
    return check_health_relevance(text) != HealthRelevance.NOT_HEALTH
