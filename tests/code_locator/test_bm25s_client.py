"""Tests for Bm25sClient edge cases."""

from __future__ import annotations

import pytest

from code_locator.retrieval.bm25s_client import Bm25sClient


def test_is_loaded_property():
    client = Bm25sClient()
    assert client.is_loaded is False

    # After indexing an empty repo, is_loaded should be True
    # (tested below)


def test_search_unloaded_returns_empty():
    """Searching before load/index returns []."""
    client = Bm25sClient()
    results = client.search("anything")
    assert results == []


def test_index_empty_repo(tmp_path):
    """Indexing a directory with no source files."""
    empty_dir = tmp_path / "empty_repo"
    empty_dir.mkdir()
    out_dir = tmp_path / "bm25_out"

    client = Bm25sClient()
    client.index(str(empty_dir), str(out_dir))

    assert client.is_loaded is True
    # Search on empty index returns []
    results = client.search("anything")
    assert results == []


def test_load_missing_index(tmp_path):
    """Loading from a dir with no bm25_index.pkl raises FileNotFoundError."""
    client = Bm25sClient()
    with pytest.raises(FileNotFoundError):
        client.load(str(tmp_path))


def test_index_and_load_roundtrip(tmp_repo, tmp_path):
    """Index, save, load from disk, search."""
    out_dir = tmp_path / "bm25_rt"
    client1 = Bm25sClient()
    client1.index(tmp_repo, str(out_dir))

    client2 = Bm25sClient()
    client2.load(str(out_dir))
    assert client2.is_loaded is True

    results = client2.search("user model class")
    assert len(results) >= 1
    assert all(r.method == "bm25" for r in results)
    assert all(r.line_number == 0 for r in results)  # file-level granularity


def test_search_respects_num_results(bm25_indexed):
    """num_results caps output length."""
    results_1 = bm25_indexed.search("user", num_results=1)
    results_all = bm25_indexed.search("user", num_results=100)
    assert len(results_1) <= 1
    assert len(results_all) >= len(results_1)
    # The fixture has multiple files mentioning "user" → should have results
    assert len(results_all) >= 1
