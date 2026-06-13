"""Singleton zero-shot NLI classifier (cross-encoder/nli-deberta-v3-xsmall)."""
from __future__ import annotations
import logging
import numpy as np

logger = logging.getLogger(__name__)
_classifier = None
_entailment_idx = 1   # deberta-v3-xsmall: 0=contradiction, 1=entailment, 2=neutral


def get_classifier():
    global _classifier
    if _classifier is None:
        from sentence_transformers import CrossEncoder
        logger.info("Loading cross-encoder/nli-deberta-v3-xsmall (~90MB)...")
        _classifier = CrossEncoder("cross-encoder/nli-deberta-v3-xsmall")
        logger.info("Classifier ready.")
    return _classifier


def top_label(text: str, labels: list[str]) -> tuple[str, float]:
    """
    Return (best_label, entailment_score).
    DeBERTa NLI returns shape (n_pairs, 3): [contradiction, entailment, neutral].
    We compare the entailment score across all label pairs and pick the highest.
    """
    clf = get_classifier()
    raw = clf.predict([(text, label) for label in labels])
    scores = np.array(raw)

    if scores.ndim == 2:
        # Multi-class NLI output — extract entailment column
        entailment_scores = scores[:, _entailment_idx]
    else:
        # Single score per pair (binary model)
        entailment_scores = scores

    best_idx = int(entailment_scores.argmax())
    return labels[best_idx], float(entailment_scores[best_idx])
