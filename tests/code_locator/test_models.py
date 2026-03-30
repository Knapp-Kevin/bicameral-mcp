"""Tests for Pydantic model validation and boundaries."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from code_locator.models import (
    FoundComponent,
    NeighborInfo,
    PlannedChange,
    Provenance,
    RetrievalResult,
    ValidatedSymbol,
)


def test_planned_change_defaults():
    pc = PlannedChange(intent="add caching")
    assert pc.business_context == ""
    assert pc.confidence == 1.0
    assert pc.discussion_participants == []


def test_planned_change_confidence_bounds():
    with pytest.raises(ValidationError):
        PlannedChange(intent="x", confidence=1.5)
    with pytest.raises(ValidationError):
        PlannedChange(intent="x", confidence=-0.1)


def test_found_component_confidence_bounds():
    with pytest.raises(ValidationError):
        FoundComponent(symbol="X", file="x.py", confidence=2.0)
    with pytest.raises(ValidationError):
        FoundComponent(symbol="X", file="x.py", confidence=-1.0)


def test_validated_symbol_defaults():
    vs = ValidatedSymbol(original_candidate="foo", matched_symbol="Foo", match_score=90.0)
    assert vs.symbol_id is None
    assert vs.repo == ""
    assert vs.bridge_method == "rapidfuzz_validate"


def test_validated_symbol_score_bounds():
    with pytest.raises(ValidationError):
        ValidatedSymbol(original_candidate="x", matched_symbol="X", match_score=101.0)


def test_retrieval_result_defaults():
    rr = RetrievalResult(file_path="a.py", method="bm25")
    assert rr.line_number == 0
    assert rr.snippet == ""
    assert rr.score == 0.0
    assert rr.repo == ""
    assert rr.symbol_name == ""


def test_provenance_defaults():
    p = Provenance()
    assert p.retrieval_channels == []
    assert p.bridge_candidate == ""
    assert p.bridge_match_score == 0.0
    assert p.rrf_score == 0.0


def test_neighbor_info_construction():
    n = NeighborInfo(
        symbol_name="Order", file_path="models.py",
        line_number=10, edge_type="imports", direction="backward"
    )
    assert n.direction == "backward"
    d = n.model_dump()
    assert d["edge_type"] == "imports"
