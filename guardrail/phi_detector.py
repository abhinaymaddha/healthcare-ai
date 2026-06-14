"""PHI detection and de-identification using regex + spaCy NER."""
from __future__ import annotations
import re
import hashlib

PHI_PATTERNS: dict[str, re.Pattern] = {
    "ssn":          re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"),
    "mrn":          re.compile(r"\b[Mm][Rr][Nn][-:\s]?[\w\d-]+\b"),
    "insurance_id": re.compile(
        r"\b(member\s*id|insurance\s*id|policy\s*no|policy\s*number)[-:\s]?[\w\d-]+\b",
        re.IGNORECASE,
    ),
    "aadhaar":      re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"),
    "pan":          re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "phone":        re.compile(r"\b(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
}

MASK_INDICATORS = re.compile(r"[\*xX]{3,}|redacted|masked|\[hidden\]", re.IGNORECASE)

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        import spacy
        _nlp = spacy.load("en_core_web_md")
    return _nlp


def _make_token(phi_type: str, value: str) -> str:
    short_hash = hashlib.md5(value.encode()).hexdigest()[:6]
    return f"[{phi_type.upper()}_{short_hash}]"


def detect_and_deidentify(text: str) -> tuple[str, dict, list]:
    """
    Returns (de_identified_text, lookup_table, phi_types_found).
    lookup_table maps token → original value.
    First name tokens are stored separately for re-identification.
    """
    lookup: dict[str, str] = {}
    phi_found: list[str] = []
    result = text

    # Regex-based PHI
    for phi_type, pattern in PHI_PATTERNS.items():
        matches = pattern.findall(result)
        for match in matches:
            match_str = match if isinstance(match, str) else match[0]
            if MASK_INDICATORS.search(match_str):
                continue
            token = _make_token(phi_type, match_str)
            lookup[token] = match_str
            result = result.replace(match_str, token)
            if phi_type not in phi_found:
                phi_found.append(phi_type)

    # spaCy NER for names and dates only.
    # GPE/LOC are excluded: cities and countries are not PHI, and NER
    # misclassifies medication brand names (e.g. "Ventolin") as GPE.
    nlp = _get_nlp()
    doc = nlp(result)
    for ent in reversed(doc.ents):          # reversed to preserve offsets
        if ent.label_ in ("PERSON", "DATE"):
            token = _make_token(ent.label_.lower(), ent.text)
            lookup[token] = ent.text
            result = result[:ent.start_char] + token + result[ent.end_char:]
            phi_type = ent.label_.lower()
            if phi_type not in phi_found:
                phi_found.append(phi_type)

    return result, lookup, phi_found


def reidentify_first_name(text: str, lookup: dict) -> str:
    """Replace PERSON tokens with first name only. All other tokens stay masked."""
    result = text
    for token, original in lookup.items():
        if token.startswith("[PERSON_"):
            first_name = original.strip().split()[0]
            result = result.replace(token, first_name)
    return result
