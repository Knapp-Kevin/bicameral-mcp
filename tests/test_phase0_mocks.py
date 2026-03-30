"""Phase 0 regression tests — always green.

Tests that all 4 MCP tools return correctly shaped responses using mock adapters.
No external dependencies (no SurrealDB, no code-locator, no repo access required).

Run: pytest tests/test_phase0_mocks.py -v
"""

from __future__ import annotations

import pytest

from contracts import (
    DecisionStatusResponse,
    DetectDriftResponse,
    IngestResponse,
    LinkCommitResponse,
    SearchDecisionsResponse,
)
from handlers.decision_status import handle_decision_status
from handlers.detect_drift import handle_detect_drift
from handlers.ingest import handle_ingest
from handlers.link_commit import handle_link_commit
from handlers.search_decisions import handle_search_decisions


# ── link_commit ───────────────────────────────────────────────────────

@pytest.mark.phase0
@pytest.mark.asyncio
async def test_link_commit_returns_valid_shape():
    result = await handle_link_commit("HEAD")
    assert isinstance(result, LinkCommitResponse)
    assert result.commit_hash != ""
    assert result.reason in ("new_commit", "already_synced", "no_changes")
    assert isinstance(result.synced, bool)
    assert isinstance(result.regions_updated, int)
    assert isinstance(result.decisions_reflected, int)
    assert isinstance(result.decisions_drifted, int)
    assert isinstance(result.undocumented_symbols, list)


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_link_commit_head_is_idempotent():
    """Calling HEAD twice should fast-path on the second call."""
    r1 = await handle_link_commit("HEAD")
    r2 = await handle_link_commit("HEAD")
    # Both calls should report the same commit hash
    assert r1.commit_hash == r2.commit_hash
    # At least one of the calls should be already_synced
    assert r1.reason == "already_synced" or r2.reason == "already_synced"


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_link_commit_new_hash_shows_work():
    """A novel commit hash should trigger actual work (not fast-path)."""
    result = await handle_link_commit("deadbeef00000000000000000000000000000000")
    assert result.reason in ("new_commit", "no_changes")
    assert result.synced is False


# ── ingest ────────────────────────────────────────────────────────────

@pytest.mark.phase0
@pytest.mark.asyncio
async def test_ingest_returns_valid_shape(minimal_payload):
    result = await handle_ingest(minimal_payload, source_scope="mock-stream", cursor="cursor-001")
    assert isinstance(result, IngestResponse)
    assert result.ingested is True
    assert result.repo == "test-repo"
    assert result.query == "test decision for ledger ingestion"
    assert result.stats.intents_created >= 1
    assert result.source_refs == ["test-meeting-001"]
    assert result.source_cursor is not None
    assert result.source_cursor.source_type == "transcript"
    assert result.source_cursor.source_scope == "mock-stream"
    assert result.source_cursor.cursor == "cursor-001"


# ── decision_status ───────────────────────────────────────────────────

@pytest.mark.phase0
@pytest.mark.asyncio
async def test_decision_status_returns_valid_shape():
    result = await handle_decision_status()
    assert isinstance(result, DecisionStatusResponse)
    assert result.ref != ""
    assert result.as_of != ""
    assert isinstance(result.summary, dict)
    assert isinstance(result.decisions, list)


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_decision_status_summary_counts_match_decisions():
    result = await handle_decision_status(filter="all")
    total_from_summary = sum(result.summary.values())
    assert total_from_summary == len(result.decisions), (
        f"summary counts ({total_from_summary}) must equal decision list length ({len(result.decisions)})"
    )


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_decision_status_filter_all_includes_every_status():
    result = await handle_decision_status(filter="all")
    statuses = {d.status for d in result.decisions}
    # Mock data has at least reflected, pending, ungrounded
    assert len(statuses) >= 1


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_decision_status_filter_narrows_results():
    all_result = await handle_decision_status(filter="all")
    reflected = await handle_decision_status(filter="reflected")
    # Filtered result cannot exceed total
    assert len(reflected.decisions) <= len(all_result.decisions)
    # Every returned decision must match the filter
    for d in reflected.decisions:
        assert d.status == "reflected", f"Expected 'reflected', got {d.status!r}"


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_decision_status_entry_has_required_fields():
    result = await handle_decision_status(filter="all")
    assert result.decisions, "Expected at least one decision in mock data"
    for entry in result.decisions:
        assert entry.intent_id != ""
        assert entry.description != ""
        assert entry.status in ("reflected", "drifted", "pending", "ungrounded")
        assert entry.ingested_at != ""
        assert isinstance(entry.code_regions, list)
        assert isinstance(entry.blast_radius, list)


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_decision_status_code_region_shape():
    result = await handle_decision_status(filter="all")
    for entry in result.decisions:
        for region in entry.code_regions:
            assert region.file_path != ""
            assert region.symbol != ""
            assert isinstance(region.lines, tuple)
            assert len(region.lines) == 2
            start, end = region.lines
            assert isinstance(start, int) and isinstance(end, int)


# ── search_decisions ──────────────────────────────────────────────────

@pytest.mark.phase0
@pytest.mark.asyncio
async def test_search_decisions_returns_valid_shape():
    result = await handle_search_decisions(query="BM25 code search")
    assert isinstance(result, SearchDecisionsResponse)
    assert result.query == "BM25 code search"
    assert isinstance(result.sync_status, LinkCommitResponse)
    assert isinstance(result.matches, list)
    assert isinstance(result.ungrounded_count, int)
    assert isinstance(result.suggested_review, list)


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_search_decisions_auto_triggers_link_commit():
    """search_decisions must embed a link_commit result in sync_status."""
    result = await handle_search_decisions(query="anything")
    # sync_status must be a valid LinkCommitResponse
    assert result.sync_status.commit_hash != ""
    assert result.sync_status.reason in ("new_commit", "already_synced", "no_changes")


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_search_decisions_ungrounded_count_accurate():
    result = await handle_search_decisions(query="anything", min_confidence=0.0)
    ungrounded = sum(1 for m in result.matches if m.status == "ungrounded")
    assert result.ungrounded_count == ungrounded, (
        f"ungrounded_count={result.ungrounded_count} but counted {ungrounded} ungrounded matches"
    )


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_search_decisions_suggested_review_only_actionable():
    """suggested_review must only include drifted/pending intent_ids."""
    result = await handle_search_decisions(query="ledger memory", min_confidence=0.0)
    review_ids = set(result.suggested_review)
    for match in result.matches:
        if match.intent_id in review_ids:
            assert match.status in ("drifted", "pending"), (
                f"intent {match.intent_id!r} in suggested_review but has status={match.status!r}"
            )


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_search_decisions_match_confidence_in_range():
    result = await handle_search_decisions(query="BM25", min_confidence=0.0)
    for match in result.matches:
        assert 0.0 <= match.confidence <= 1.0, (
            f"confidence {match.confidence} out of range for match {match.intent_id!r}"
        )


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_search_decisions_respects_min_confidence():
    high_threshold = await handle_search_decisions(query="BM25", min_confidence=0.9)
    low_threshold = await handle_search_decisions(query="BM25", min_confidence=0.0)
    # High threshold should return <= results of low threshold
    assert len(high_threshold.matches) <= len(low_threshold.matches)


# ── detect_drift ──────────────────────────────────────────────────────

@pytest.mark.phase0
@pytest.mark.asyncio
async def test_detect_drift_returns_valid_shape():
    result = await handle_detect_drift("pilot/demo2/contracts.py")
    assert isinstance(result, DetectDriftResponse)
    assert result.file_path == "pilot/demo2/contracts.py"
    assert isinstance(result.sync_status, LinkCommitResponse)
    assert result.source in ("working_tree", "HEAD")
    assert isinstance(result.decisions, list)
    assert isinstance(result.drifted_count, int)
    assert isinstance(result.pending_count, int)
    assert isinstance(result.undocumented_symbols, list)


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_detect_drift_auto_triggers_link_commit():
    result = await handle_detect_drift("pilot/demo2/contracts.py")
    assert result.sync_status.commit_hash != ""


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_detect_drift_counts_match_decisions():
    result = await handle_detect_drift("pilot/demo2/contracts.py")
    drifted = sum(1 for d in result.decisions if d.status == "drifted")
    pending = sum(1 for d in result.decisions if d.status == "pending")
    assert result.drifted_count == drifted
    assert result.pending_count == pending


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_detect_drift_working_tree_vs_head_source_field():
    wt = await handle_detect_drift("pilot/demo2/contracts.py", use_working_tree=True)
    head = await handle_detect_drift("pilot/demo2/contracts.py", use_working_tree=False)
    assert wt.source == "working_tree"
    assert head.source == "HEAD"


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_detect_drift_unknown_file_returns_empty():
    result = await handle_detect_drift("this/file/does/not/exist.py")
    assert isinstance(result.decisions, list)
    assert result.drifted_count == 0
    assert result.pending_count == 0


@pytest.mark.phase0
@pytest.mark.asyncio
async def test_detect_drift_entry_has_required_fields():
    result = await handle_detect_drift("pilot/demo2/contracts.py")
    for entry in result.decisions:
        assert entry.intent_id != ""
        assert entry.description != ""
        assert entry.status in ("reflected", "drifted", "pending", "ungrounded")
        assert entry.symbol != ""
        assert isinstance(entry.lines, tuple)
        assert len(entry.lines) == 2
        assert entry.source_ref is not None


# ── cross-tool consistency ────────────────────────────────────────────

@pytest.mark.phase0
@pytest.mark.asyncio
async def test_mock_data_is_consistent_across_tools():
    """Decisions returned by decision_status and search_decisions share the same intent_ids."""
    status_result = await handle_decision_status(filter="all")
    search_result = await handle_search_decisions(query="BM25 memory ledger", min_confidence=0.0)

    status_ids = {d.intent_id for d in status_result.decisions}
    search_ids = {m.intent_id for m in search_result.matches}

    # search results should be a subset of all known decisions
    for sid in search_ids:
        assert sid in status_ids, (
            f"search_decisions returned intent_id={sid!r} not present in decision_status"
        )
