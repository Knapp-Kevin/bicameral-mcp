"""Extended RRF tests — empty inputs, snippet preference, symbol propagation."""

from __future__ import annotations

from code_locator.fusion.rrf import rrf_fuse
from code_locator.models import RetrievalResult


def _rr(fp, ln=0, method="bm25", snippet="", symbol_name="", repo=""):
    return RetrievalResult(
        file_path=fp, line_number=ln, method=method,
        snippet=snippet, symbol_name=symbol_name, repo=repo,
    )


def test_empty_ranked_lists():
    assert rrf_fuse([]) == []


def test_single_empty_list():
    assert rrf_fuse([[]]) == []


def test_snippet_preference():
    """Result with snippet is preferred over one without."""
    bm25 = [_rr("a.py", 10, "bm25", snippet="")]
    graph = [_rr("a.py", 10, "graph", snippet="def foo():")]

    fused = rrf_fuse([bm25, graph])
    assert len(fused) == 1
    assert fused[0].snippet == "def foo():"


def test_symbol_name_propagated():
    """symbol_name and repo fields propagate through fusion."""
    results = [_rr("a.py", 1, "bm25", symbol_name="Foo", repo="myrepo")]
    fused = rrf_fuse([results])
    assert fused[0].symbol_name == "Foo"
    assert fused[0].repo == "myrepo"


def test_method_field_sorted_deduped():
    """method field for overlapping results is sorted and deduped."""
    bm25 = [_rr("a.py", method="bm25"), _rr("a.py", method="bm25")]
    graph = [_rr("a.py", method="graph")]

    fused = rrf_fuse([bm25, graph])
    # "bm25" appears twice but should be deduped in method
    assert fused[0].method == "bm25+graph"
