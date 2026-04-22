"""v0.5.5 — region-anchored preflight retrieval tests.

Verifies that preflight surfaces decisions by REGION OVERLAP (code locator →
file_paths → pinned decisions) rather than solely by keyword match on decision
description text.

The core scenario: a decision is stored with description "High recall: no false
negatives on drift/grounding", pinned to search_code.py. The preflight topic is
"improve retrieval quality for code locator" — zero keyword overlap with the
description, so BM25 returns nothing. Region-anchored search finds the file
via the code locator, looks up the pinned decision, and surfaces it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from contracts import (
    CodeRegionSummary,
    DecisionMatch,
    LinkCommitResponse,
    SearchDecisionsResponse,
)
from handlers.preflight import (
    _merge_decision_matches,
    _region_anchored_search,
    handle_preflight,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_link_commit_response():
    return LinkCommitResponse(
        commit_hash="abc123",
        synced=True,
        reason="already_synced",
    )


def _make_region_decision(
    decision_id: str = "decision:r1",
    description: str = "High recall: no false negatives on drift/grounding",
    status: str = "reflected",
    file_path: str = "code_locator/tools/search_code.py",
    symbol: str = "SearchCodeTool",
) -> dict:
    """Raw dict as returned by get_decisions_for_files."""
    return {
        "decision_id": decision_id,
        "description": description,
        "source_type": "transcript",
        "source_ref": "meeting-2026-04-21",
        "source_excerpt": "",
        "meeting_date": "",
        "ingested_at": "2026-04-21",
        "status": status,
        "product_signoff": None,
        "code_region": {
            "file_path": file_path,
            "symbol": symbol,
            "lines": (52, 99),
            "purpose": description,
            "content_hash": "abc",
        },
    }


def _make_ctx(
    code_locator_hits: list[dict] | None = None,
    region_decisions: list[dict] | None = None,
    bm25_matches: list[DecisionMatch] | None = None,
    guided_mode: bool = True,
) -> SimpleNamespace:
    """Build a minimal fake BicameralContext."""
    # Code locator mock
    code_locator = MagicMock()
    code_locator.search_code = MagicMock(return_value=code_locator_hits or [])

    # Ledger mock
    ledger = MagicMock()
    ledger.ingest_commit = AsyncMock(return_value={
        "commit_hash": "abc123",
        "new_decisions_linked": 0,
        "drift_detected": [],
        "symbols_indexed": 0,
    })
    ledger.get_decisions_for_files = AsyncMock(return_value=region_decisions or [])
    ledger.search_by_query = AsyncMock(return_value=[])

    bm25 = bm25_matches or []
    search_resp = SearchDecisionsResponse(
        query="",
        sync_status=_make_link_commit_response(),
        matches=bm25,
        ungrounded_count=0,
        suggested_review=[],
    )
    search_resp.action_hints = []

    ctx = SimpleNamespace(
        repo_path=".",
        ledger=ledger,
        code_locator=code_locator,
        guided_mode=guided_mode,
        _sync_state={},
    )
    return ctx, search_resp


# ── Unit: _region_anchored_search ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_region_anchored_returns_pinned_decisions():
    """Code locator finds a file → ledger returns a pinned decision."""
    ctx, _ = _make_ctx(
        code_locator_hits=[
            {"file_path": "code_locator/tools/search_code.py", "score": 1.2, "symbol_name": "SearchCodeTool"},
        ],
        region_decisions=[_make_region_decision()],
    )

    matches = await _region_anchored_search(ctx, "improve retrieval quality for code locator")

    assert len(matches) == 1
    assert matches[0].decision_id == "decision:r1"
    assert matches[0].confidence == 0.9
    assert matches[0].code_regions[0].file_path == "code_locator/tools/search_code.py"


@pytest.mark.asyncio
async def test_region_anchored_deduplicates_same_decision_across_files():
    """Same decision pinned to two files → appears only once."""
    ctx, _ = _make_ctx(
        code_locator_hits=[
            {"file_path": "file_a.py", "score": 1.0},
            {"file_path": "file_b.py", "score": 0.8},
        ],
        region_decisions=[
            _make_region_decision(decision_id="decision:d1", file_path="file_a.py"),
            _make_region_decision(decision_id="decision:d1", file_path="file_b.py"),
        ],
    )

    matches = await _region_anchored_search(ctx, "some topic")
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_region_anchored_returns_empty_when_no_code_locator():
    """Missing code_locator on ctx → graceful empty result."""
    ctx = SimpleNamespace(repo_path=".", ledger=MagicMock(), guided_mode=True, _sync_state={})

    matches = await _region_anchored_search(ctx, "some topic")
    assert matches == []


@pytest.mark.asyncio
async def test_region_anchored_returns_empty_when_code_locator_raises():
    """Code locator error → fail-open, empty result."""
    code_locator = MagicMock()
    code_locator.search_code = MagicMock(side_effect=RuntimeError("index not built"))
    ctx = SimpleNamespace(
        repo_path=".", ledger=MagicMock(), code_locator=code_locator,
        guided_mode=True, _sync_state={},
    )

    matches = await _region_anchored_search(ctx, "some topic")
    assert matches == []


@pytest.mark.asyncio
async def test_region_anchored_caps_at_max_files():
    """Only the first max_files unique file paths are queried."""
    hits = [{"file_path": f"file_{i}.py", "score": 1.0} for i in range(20)]
    ctx, _ = _make_ctx(code_locator_hits=hits, region_decisions=[])

    await _region_anchored_search(ctx, "topic", max_files=5)

    called_paths = ctx.ledger.get_decisions_for_files.call_args[0][0]
    assert len(called_paths) == 5


# ── Unit: _merge_decision_matches ───────────────────────────────────────────


def _dm(decision_id: str, status: str = "reflected") -> DecisionMatch:
    return DecisionMatch(
        decision_id=decision_id,
        description="test",
        status=status,
        confidence=0.8,
        source_ref="",
        code_regions=[],
    )


def test_merge_region_first():
    """Region matches come before BM25 matches in output."""
    region = [_dm("d:region")]
    bm25 = [_dm("d:bm25")]
    merged = _merge_decision_matches(region, bm25)
    assert [m.decision_id for m in merged] == ["d:region", "d:bm25"]


def test_merge_deduplicates_by_decision_id():
    """Same decision_id in both → only region version kept (first seen)."""
    region = [_dm("d:shared")]
    bm25 = [_dm("d:shared"), _dm("d:bm25only")]
    merged = _merge_decision_matches(region, bm25)
    assert len(merged) == 2
    assert merged[0].decision_id == "d:shared"
    assert merged[1].decision_id == "d:bm25only"


# ── Integration: handle_preflight fires on region hit with zero BM25 overlap ─


@pytest.mark.asyncio
async def test_preflight_fires_on_region_hit_no_bm25():
    """Core regression: preflight surfaces a decision even when BM25 returns
    nothing because the topic has zero keyword overlap with the description.

    Region-anchored path: topic → code locator → file_path → pinned decision.
    """
    ctx, search_resp = _make_ctx(
        code_locator_hits=[
            {"file_path": "code_locator/tools/search_code.py", "score": 1.5},
        ],
        region_decisions=[_make_region_decision(status="reflected")],
        bm25_matches=[],  # BM25 finds nothing
        guided_mode=True,
    )

    with (
        patch("handlers.link_commit.handle_link_commit", new=AsyncMock(return_value=_make_link_commit_response())),
        patch("handlers.search_decisions.handle_link_commit", new=AsyncMock(return_value=_make_link_commit_response())),
        patch("handlers.preflight.handle_search_decisions", new=AsyncMock(return_value=search_resp)),
    ):
        resp = await handle_preflight(ctx, topic="improve retrieval quality for code locator")

    assert resp.fired is True
    assert "region" in resp.sources_chained
    decision_ids = [d.decision_id for d in resp.decisions]
    assert "decision:r1" in decision_ids


@pytest.mark.asyncio
async def test_preflight_region_in_sources_chained():
    """sources_chained includes 'region' when region search yields results."""
    ctx, search_resp = _make_ctx(
        code_locator_hits=[{"file_path": "some/file.py", "score": 1.0}],
        region_decisions=[_make_region_decision(status="drifted")],
        bm25_matches=[],
        guided_mode=False,  # normal mode — needs actionable signal
    )

    with (
        patch("handlers.link_commit.handle_link_commit", new=AsyncMock(return_value=_make_link_commit_response())),
        patch("handlers.search_decisions.handle_link_commit", new=AsyncMock(return_value=_make_link_commit_response())),
        patch("handlers.preflight.handle_search_decisions", new=AsyncMock(return_value=search_resp)),
    ):
        resp = await handle_preflight(ctx, topic="improve something in code locator search")

    assert "region" in resp.sources_chained


@pytest.mark.asyncio
async def test_preflight_bm25_only_still_works_when_no_code_locator():
    """No code_locator on ctx → preflight falls back to BM25 correctly."""
    bm25_match = _dm("d:bm25", status="drifted")
    search_resp = SearchDecisionsResponse(
        query="",
        sync_status=_make_link_commit_response(),
        matches=[bm25_match],
        ungrounded_count=0,
        suggested_review=[],
    )
    search_resp.action_hints = []

    # No code_locator attribute
    ctx = SimpleNamespace(
        repo_path=".",
        ledger=MagicMock(),
        guided_mode=False,
        _sync_state={},
    )

    with (
        patch("handlers.link_commit.handle_link_commit", new=AsyncMock(return_value=_make_link_commit_response())),
        patch("handlers.search_decisions.handle_link_commit", new=AsyncMock(return_value=_make_link_commit_response())),
        patch("handlers.preflight.handle_search_decisions", new=AsyncMock(return_value=search_resp)),
    ):
        resp = await handle_preflight(ctx, topic="drifted stripe webhook handler")

    assert resp.fired is True
    assert "region" not in resp.sources_chained
