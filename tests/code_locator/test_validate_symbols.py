"""Tests for the validate_symbols tool."""

from __future__ import annotations

from code_locator.tools.validate_symbols import ValidateSymbolsTool


def test_exact_match(indexed_db, config):
    tool = ValidateSymbolsTool(indexed_db, config)
    results = tool.execute({"candidates": ["User"]})

    assert len(results) >= 1
    matched = [r for r in results if r.matched_symbol == "User"]
    assert len(matched) >= 1
    assert matched[0].match_score >= 90


def test_fuzzy_match(indexed_db, config):
    tool = ValidateSymbolsTool(indexed_db, config)
    # Use multi-word form to avoid single-word substring filter
    results = tool.execute({"candidates": ["process order"]})

    assert len(results) >= 1
    symbols = [r.matched_symbol for r in results]
    assert any("process_order" in s for s in symbols)


def test_no_match(indexed_db, config):
    tool = ValidateSymbolsTool(indexed_db, config)
    results = tool.execute({"candidates": ["NonExistentXyz123"]})
    assert results == []


def test_min_candidate_length(indexed_db, config):
    tool = ValidateSymbolsTool(indexed_db, config)
    results = tool.execute({"candidates": ["ab"]})
    assert results == []


def test_max_matches_cap(indexed_db, config):
    config.fuzzy_max_matches_per_candidate = 2
    tool = ValidateSymbolsTool(indexed_db, config)
    results = tool.execute({"candidates": ["User"]})
    assert len(results) <= 2
