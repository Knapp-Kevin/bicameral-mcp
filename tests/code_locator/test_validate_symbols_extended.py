"""Extended validate_symbols tests — empty candidates, qualified name match."""

from __future__ import annotations

from code_locator.tools.validate_symbols import ValidateSymbolsTool


def test_empty_candidates(indexed_db, config):
    """Empty candidates list → empty results."""
    tool = ValidateSymbolsTool(indexed_db, config)
    results = tool.execute({"candidates": []})
    assert results == []


def test_missing_candidates_key(indexed_db, config):
    """Missing candidates key → empty results."""
    tool = ValidateSymbolsTool(indexed_db, config)
    results = tool.execute({})
    assert results == []


def test_qualified_name_match(indexed_db, config):
    """Candidate matching a qualified name (e.g., 'User.get_name')."""
    tool = ValidateSymbolsTool(indexed_db, config)
    results = tool.execute({"candidates": ["User.get_name"]})

    # Should match the qualified name
    assert len(results) >= 1
    symbols = [r.matched_symbol for r in results]
    assert any("get_name" in s for s in symbols)


def test_bridge_method_field(indexed_db, config):
    """All results have bridge_method='rapidfuzz_validate'."""
    tool = ValidateSymbolsTool(indexed_db, config)
    results = tool.execute({"candidates": ["User"]})
    for r in results:
        assert r.bridge_method == "rapidfuzz_validate"


def test_symbol_id_populated(indexed_db, config):
    """Matched symbols have non-None symbol_id."""
    tool = ValidateSymbolsTool(indexed_db, config)
    results = tool.execute({"candidates": ["User"]})
    for r in results:
        assert r.symbol_id is not None
        assert isinstance(r.symbol_id, int)
