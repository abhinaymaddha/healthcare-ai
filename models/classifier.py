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
        try:
            # Use cached weights without any HuggingFace network calls
            _classifier = CrossEncoder(
                "cross-encoder/nli-deberta-v3-xsmall",
                local_files_only=True,
            )
        except Exception:
            # First run: weights not cached yet — download once, then cache
            logger.info("Cache miss — downloading from HuggingFace Hub (one-time)...")
            _classifier = CrossEncoder("cross-encoder/nli-deberta-v3-xsmall")
        logger.info("Classifier ready.")
    return _classifier


def all_scores(text: str, labels: list[str]) -> dict[str, float]:
    """Return entailment score for every label."""
    clf = get_classifier()
    raw = clf.predict([(text, label) for label in labels])
    scores = np.array(raw)
    if scores.ndim == 2:
        entailment_scores = scores[:, _entailment_idx]
    else:
        entailment_scores = scores
    return dict(zip(labels, [float(s) for s in entailment_scores]))


def top_label(text: str, labels: list[str]) -> tuple[str, float]:
    """Return (best_label, entailment_score)."""
    score_map = all_scores(text, labels)
    best = max(score_map, key=score_map.__getitem__)
    return best, score_map[best]
