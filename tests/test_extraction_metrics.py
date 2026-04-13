"""Offline unit tests for _extraction_metrics.

Exercises the fuzzy matching, 1:1 assignment, and aggregate math with
synthetic extracted/fixture pairs. No network, no fixture files on disk.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _extraction_metrics import (  # noqa: E402
    aggregate_extraction_metrics,
    compute_extraction_metrics,
)


def _f(descriptions: list[str]) -> dict:
    """Synthesize a fixture dict from bare description strings."""
    return {"decisions": [{"description": d} for d in descriptions]}


def _e(descriptions: list[str]) -> list[dict]:
    return [{"description": d} for d in descriptions]


def test_skipped_when_fixture_absent():
    out = compute_extraction_metrics(_e(["anything"]), None)
    assert out == {"skipped": True, "reason": "no fixture"}


def test_perfect_match_is_p1_r1_f1_1():
    fixture = _f([
        "Add 12-second timeout to payment authorize calls",
        "Emit payment.timeout event via EventBus",
    ])
    extracted = _e([
        "Add 12-second timeout to payment authorize calls",
        "Emit payment.timeout event via EventBus",
    ])
    out = compute_extraction_metrics(extracted, fixture)
    assert out["skipped"] is False
    assert out["true_positives"] == 2
    assert out["false_positives"] == 0
    assert out["false_negatives"] == 0
    assert out["precision"] == 1.0
    assert out["recall"] == 1.0
    assert out["f1"] == 1.0


def test_fuzzy_match_tolerates_word_order_and_synonyms():
    """token_set_ratio should match reasonable paraphrases above threshold."""
    fixture = _f(["Add 12-second timeout to payment authorize calls"])
    extracted = _e(["Payment authorize calls must use a 12-second timeout ceiling"])
    out = compute_extraction_metrics(extracted, fixture)
    assert out["true_positives"] == 1
    assert out["false_positives"] == 0
    assert out["false_negatives"] == 0


def test_low_similarity_is_false_positive_and_false_negative():
    fixture = _f(["Add 12-second timeout to payment authorize calls"])
    extracted = _e(["Use Redis Streams for dead letter queue"])
    out = compute_extraction_metrics(extracted, fixture)
    assert out["true_positives"] == 0
    assert out["false_positives"] == 1
    assert out["false_negatives"] == 1
    assert out["precision"] == 0.0
    assert out["recall"] == 0.0
    assert out["f1"] == 0.0


def test_partial_match_mixed_precision_and_recall():
    fixture = _f([
        "Add timeout to authorize calls",
        "Emit timeout event via EventBus",
        "Drop garbage provider responses",
    ])
    extracted = _e([
        "Add timeout to authorize calls",   # TP
        "Drop garbage provider responses",  # TP
        "Use circuit breaker for rate limiting",  # FP
    ])
    out = compute_extraction_metrics(extracted, fixture)
    assert out["true_positives"] == 2
    assert out["false_positives"] == 1
    assert out["false_negatives"] == 1  # emit timeout event
    assert 0.6 < out["precision"] < 0.7  # 2/3
    assert 0.6 < out["recall"] < 0.7  # 2/3


def test_one_to_one_matching_prevents_double_counting():
    """If two extracted items both look like one fixture item, only one wins."""
    fixture = _f(["Add 12-second timeout to payment authorize calls"])
    extracted = _e([
        "Add 12-second timeout to payment authorize calls",
        "Add a 12-second timeout to authorize calls in payments",  # very similar
    ])
    out = compute_extraction_metrics(extracted, fixture)
    assert out["true_positives"] == 1  # not 2
    assert out["false_positives"] == 1  # the second one doesn't match anything new
    assert out["false_negatives"] == 0


def test_aggregate_sums_across_scored_and_ignores_skipped():
    per_transcript = [
        {
            "skipped": False,
            "true_positives": 3, "false_positives": 1, "false_negatives": 2,
            "precision": 0.75, "recall": 0.6, "f1": 0.667,
        },
        {
            "skipped": False,
            "true_positives": 5, "false_positives": 0, "false_negatives": 1,
            "precision": 1.0, "recall": 0.833, "f1": 0.909,
        },
        {"skipped": True, "reason": "no fixture"},
    ]
    out = aggregate_extraction_metrics(per_transcript)
    assert out["skipped"] is False
    assert out["scored_transcripts"] == 2
    assert out["true_positives"] == 8
    assert out["false_positives"] == 1
    assert out["false_negatives"] == 3
    # precision = 8/9, recall = 8/11
    assert abs(out["precision"] - 8/9) < 1e-3
    assert abs(out["recall"] - 8/11) < 1e-3


def test_aggregate_all_skipped_returns_skipped():
    per_transcript = [
        {"skipped": True, "reason": "no fixture"},
        {"skipped": True, "reason": "no fixture"},
    ]
    out = aggregate_extraction_metrics(per_transcript)
    assert out["skipped"] is True


def test_empty_extraction_and_empty_fixture_gives_zero_not_error():
    out = compute_extraction_metrics([], _f([]))
    assert out["skipped"] is False
    assert out["true_positives"] == 0
    assert out["precision"] == 0.0
    assert out["recall"] == 0.0
    assert out["f1"] == 0.0
