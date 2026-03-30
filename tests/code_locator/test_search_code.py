"""Tests for the search_code tool."""

from __future__ import annotations

from code_locator.tools.search_code import SearchCodeTool


def test_bm25_only(indexed_db, bm25_indexed, config):
    tool = SearchCodeTool(bm25_indexed, indexed_db, config)
    results = tool.execute({"query": "process order user"})

    assert len(results) >= 1
    assert all(r.file_path for r in results)


def test_bm25_plus_graph(indexed_db, bm25_indexed, config):
    tool = SearchCodeTool(bm25_indexed, indexed_db, config)

    # Get a valid symbol_id from the db
    names = indexed_db.get_all_symbol_names()
    user_id = next(sid for sid, n, qn in names if n == "User")

    results = tool.execute({"query": "user model", "symbol_ids": [user_id]})
    assert len(results) >= 1


def test_empty_query(indexed_db, bm25_indexed, config):
    tool = SearchCodeTool(bm25_indexed, indexed_db, config)
    results = tool.execute({"query": ""})
    assert results == []


def test_graph_seed_lookup(indexed_db, bm25_indexed, config):
    tool = SearchCodeTool(bm25_indexed, indexed_db, config)

    names = indexed_db.get_all_symbol_names()
    user_id = next(sid for sid, n, qn in names if n == "User")

    results = tool.execute({"query": "user", "symbol_ids": [user_id]})
    # The seed symbol's file should appear in results
    files = [r.file_path for r in results]
    assert any("models.py" in f for f in files)
