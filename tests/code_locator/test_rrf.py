"""Tests for Reciprocal Rank Fusion."""

from __future__ import annotations

from code_locator.fusion.rrf import rrf_fuse
from code_locator.models import RetrievalResult


def _rr(fp, ln=0, method="bm25", score=0.0, snippet="", symbol_name=""):
    return RetrievalResult(
        file_path=fp, line_number=ln, method=method,
        score=score, snippet=snippet, symbol_name=symbol_name,
    )


def test_single_channel():
    results = [_rr("a.py", method="bm25"), _rr("b.py", method="bm25")]
    fused = rrf_fuse([results], k=60)

    assert len(fused) == 2
    # rank 0: weight/(60+0+1) = 1.0/61
    assert abs(fused[0].score - 1.0 / 61) < 1e-9
    assert abs(fused[1].score - 1.0 / 62) < 1e-9


def test_two_channels_overlap():
    bm25 = [_rr("a.py", method="bm25"), _rr("b.py", method="bm25")]
    graph = [_rr("a.py", method="graph"), _rr("c.py", method="graph")]

    fused = rrf_fuse([bm25, graph], k=60)

    # a.py appears in both → fused score = 1.0/61 + 1.2/61
    a_result = next(r for r in fused if r.file_path == "a.py")
    expected = 1.0 / 61 + 1.2 / 61
    assert abs(a_result.score - expected) < 1e-9
    assert "bm25" in a_result.method
    assert "graph" in a_result.method


def test_dedup_by_key():
    bm25 = [_rr("a.py", 10, "bm25")]
    graph = [_rr("a.py", 10, "graph")]

    fused = rrf_fuse([bm25, graph], k=60)
    assert len(fused) == 1


def test_channel_weights():
    bm25 = [_rr("a.py", method="bm25")]
    graph = [_rr("b.py", method="graph")]

    weights = {"bm25": 1.0, "graph": 1.2}
    fused = rrf_fuse([bm25, graph], channel_weights=weights, k=60)

    scores = {r.file_path: r.score for r in fused}
    # graph weight 1.2 > bm25 weight 1.0
    assert scores["b.py"] > scores["a.py"]


def test_max_results():
    results = [_rr(f"f{i}.py", method="bm25") for i in range(10)]
    fused = rrf_fuse([results], max_results=3)
    assert len(fused) == 3
