"""Precision/recall metrics for the M1 decision-relevance eval.

Compares a skill-extraction output against a pregenerated ground-truth
fixture using rapidfuzz token-set ratio on decision descriptions.

Fixture format (one JSON file per transcript):

    pilot/mcp/tests/fixtures/extraction/<source_ref>.json
    {
      "source_ref": "medusa-payment-timeout",
      "generated_by": "claude-opus-4-6-20251015",
      "generated_at": "2026-04-13T22:30:00Z",
      "decisions": [ {"description": "..."}, ... ],
      "action_items": [ {"text": "...", "owner": "..."}, ... ]
    }

The fixture is **hand-editable**. Opus 4.6 is only the bootstrap tool via
``tests/regen_extraction_fixtures.py``; the committed JSON is the ground
truth, and humans may correct it over time.

Metric:

    For each extracted decision d_actual, find its best fuzzy match in the
    fixture's ``decisions`` via ``rapidfuzz.fuzz.token_set_ratio``. A match
    is counted when the score meets ``MATCH_THRESHOLD``. Matching is 1:1 —
    once a fixture item is matched it's removed from the candidate pool so
    the actual can't double-match.

      true positives  = matched extracted decisions
      false positives = unmatched extracted decisions
      false negatives = unmatched fixture decisions
      precision       = TP / (TP + FP)
      recall          = TP / (TP + FN)
      f1              = 2 * P * R / (P + R)

Skipped (metric reports ``None``) when the fixture file is absent, so
fixture-less transcripts don't break CI before the ground-truth set is
bootstrapped.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "extraction"
MATCH_THRESHOLD = 70  # rapidfuzz token_set_ratio, 0–100 scale


def fixture_path(source_ref: str) -> Path:
    return FIXTURES_DIR / f"{source_ref}.json"


def load_fixture(source_ref: str) -> dict | None:
    """Return the committed ground-truth fixture or None if absent."""
    p = fixture_path(source_ref)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _descs(items: list[dict]) -> list[str]:
    return [str(d.get("description", "")).strip() for d in items if d.get("description")]


def compute_extraction_metrics(
    extracted_decisions: list[dict],
    fixture: dict | None,
) -> dict[str, Any]:
    """Match extracted decisions against fixture decisions.

    Returns ``{"skipped": True, "reason": "no fixture"}`` when the fixture
    is absent, otherwise a dict with precision, recall, f1, tp/fp/fn counts,
    and the unmatched lists (useful for debugging and calibration).
    """
    if fixture is None:
        return {"skipped": True, "reason": "no fixture"}

    actual = _descs(extracted_decisions)
    expected = _descs(fixture.get("decisions") or [])

    unmatched_expected = list(expected)
    matched: list[tuple[str, str, float]] = []
    unmatched_actual: list[str] = []

    for a in actual:
        if not unmatched_expected:
            unmatched_actual.append(a)
            continue
        # Find best match in remaining expected pool
        best_i = -1
        best_score = -1.0
        for i, e in enumerate(unmatched_expected):
            score = fuzz.token_set_ratio(a, e)
            if score > best_score:
                best_score = score
                best_i = i
        if best_score >= MATCH_THRESHOLD:
            matched.append((a, unmatched_expected[best_i], best_score))
            unmatched_expected.pop(best_i)
        else:
            unmatched_actual.append(a)

    tp = len(matched)
    fp = len(unmatched_actual)
    fn = len(unmatched_expected)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "skipped": False,
        "fixture_decisions": len(expected),
        "extracted_decisions": len(actual),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "match_threshold": MATCH_THRESHOLD,
        "unmatched_actual": unmatched_actual,
        "unmatched_expected": unmatched_expected,
    }


def aggregate_extraction_metrics(per_transcript: list[dict]) -> dict[str, Any]:
    """Aggregate per-transcript metric dicts into repo/overall totals.

    Transcripts with ``skipped=True`` are excluded from aggregation. If every
    transcript is skipped, returns ``{"skipped": True, "reason": "..."}``.
    """
    scored = [r for r in per_transcript if not r.get("skipped", False)]
    if not scored:
        return {"skipped": True, "reason": "no scored transcripts"}

    tp = sum(r["true_positives"] for r in scored)
    fp = sum(r["false_positives"] for r in scored)
    fn = sum(r["false_negatives"] for r in scored)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "skipped": False,
        "scored_transcripts": len(scored),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }
