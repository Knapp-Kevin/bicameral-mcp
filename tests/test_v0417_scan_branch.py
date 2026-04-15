"""v0.4.17 — bicameral.scan_branch regression tests.

Locks in the contract for the multi-file drift audit introduced in
v0.4.17. Covers three layers:

  1. Logic-only tests via monkeypatching ``ctx.ledger`` methods — dedup
     by intent_id, status counts, range_truncated cap, honest empty
     path, default base ref resolution. Fast, deterministic, no git.
  2. Integration against the real surreal ledger + seeded git repo —
     a single-file range actually sees the decision the scan is meant
     to report, so the fan-out → dedup → classify pipeline runs under
     realistic conditions.
  3. Refactor regression — ``handle_detect_drift`` still produces a
     ``DetectDriftResponse`` that matches pre-v0.4.17 output after
     ``raw_decisions_to_drift_entries`` was extracted.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from textwrap import dedent
from unittest.mock import AsyncMock, patch

import pytest

from adapters.ledger import get_ledger, reset_ledger_singleton
from context import BicameralContext
from contracts import DriftEntry, ScanBranchResponse
from handlers.detect_drift import (
    handle_detect_drift,
    raw_decisions_to_drift_entries,
)
from handlers.ingest import handle_ingest
from handlers.scan_branch import _default_base_ref, handle_scan_branch


# ── Layer 1: logic-only tests (monkeypatched ledger) ────────────────


class _FakeLedger:
    """Mock ledger that returns pre-canned responses for the three
    methods scan_branch calls: ``get_decisions_for_file``,
    ``get_undocumented_symbols``."""

    def __init__(self, per_file: dict[str, list[dict]] | None = None):
        self._per_file = per_file or {}
        self.calls: list[str] = []

    async def get_decisions_for_file(self, file_path: str) -> list[dict]:
        self.calls.append(file_path)
        return self._per_file.get(file_path, [])

    async def get_undocumented_symbols(self, file_path: str) -> list[str]:
        return []


class _FakeCtx:
    """Minimal BicameralContext replacement for logic tests."""
    def __init__(self, ledger: _FakeLedger, repo_path: str = "/tmp/fake-repo"):
        self.ledger = ledger
        self.repo_path = repo_path
        self.guided_mode = False


def _sample_decision(
    intent_id: str,
    description: str,
    status: str = "pending",
    symbol: str = "X",
    file_path: str = "pricing.py",
    lines: tuple[int, int] = (1, 10),
) -> dict:
    return {
        "intent_id": intent_id,
        "description": description,
        "status": status,
        "code_region": {
            "symbol": symbol,
            "lines": list(lines),
        },
        "source_ref": f"src-{intent_id}",
        "source_excerpt": f"excerpt for {intent_id}",
        "meeting_date": "2026-04-15",
    }


@pytest.mark.asyncio
async def test_scan_branch_honest_empty_path_no_matches(monkeypatch):
    """Empty ledger + no changed files → clean empty response."""
    ctx = _FakeCtx(_FakeLedger())
    # Force an empty changed-files range so nothing is swept
    monkeypatch.setattr(
        "handlers.scan_branch.get_changed_files_in_range",
        lambda base, head, repo: [],
    )
    monkeypatch.setattr(
        "handlers.scan_branch.resolve_ref",
        lambda ref, repo: "deadbeef0" if ref == "main" else "cafef00d0",
    )
    # Stub link_commit so we don't touch real git
    async def _noop_link(ctx, commit_hash):
        from contracts import LinkCommitResponse
        return LinkCommitResponse(
            commit_hash="cafef00d0",
            synced=False,
            reason="already_synced",
        )
    monkeypatch.setattr("handlers.scan_branch.handle_link_commit", _noop_link)

    resp = await handle_scan_branch(ctx, base_ref="main", head_ref="HEAD")
    assert isinstance(resp, ScanBranchResponse)
    assert resp.decisions == []
    assert resp.files_changed == []
    assert resp.drifted_count == 0
    assert resp.pending_count == 0
    assert resp.ungrounded_count == 0
    assert resp.reflected_count == 0
    assert resp.sweep_scope == "range_diff"
    assert resp.range_size == 0
    assert resp.action_hints == []


@pytest.mark.asyncio
async def test_scan_branch_head_only_fallback_when_base_missing(monkeypatch):
    """Unresolvable base → sweep_scope=head_only, no range diff ran."""
    ctx = _FakeCtx(_FakeLedger())

    def _resolve(ref, repo):
        return None if ref == "main" else "cafef00d0"

    monkeypatch.setattr("handlers.scan_branch.resolve_ref", _resolve)
    monkeypatch.setattr(
        "handlers.scan_branch.get_changed_files_in_range",
        lambda base, head, repo: None,  # unreachable range
    )
    async def _noop_link(ctx, commit_hash):
        from contracts import LinkCommitResponse
        return LinkCommitResponse(
            commit_hash="cafef00d0",
            synced=False,
            reason="already_synced",
        )
    monkeypatch.setattr("handlers.scan_branch.handle_link_commit", _noop_link)

    resp = await handle_scan_branch(ctx, base_ref="main")
    assert resp.sweep_scope == "head_only"
    assert resp.files_changed == []


@pytest.mark.asyncio
async def test_scan_branch_multi_file_dedup_by_intent_id(monkeypatch):
    """A single decision whose code_region touches two different files
    should appear ONCE in the response, not twice."""
    same_decision = _sample_decision("i1", "shared decision", status="drifted")
    per_file = {
        "a.py": [same_decision],
        "b.py": [same_decision],  # same intent_id — dedup target
    }
    ctx = _FakeCtx(_FakeLedger(per_file))

    monkeypatch.setattr(
        "handlers.scan_branch.get_changed_files_in_range",
        lambda base, head, repo: ["a.py", "b.py"],
    )
    monkeypatch.setattr(
        "handlers.scan_branch.resolve_ref",
        lambda ref, repo: "beef0" if ref != "HEAD" else "cafe0",
    )
    async def _noop_link(ctx, commit_hash):
        from contracts import LinkCommitResponse
        return LinkCommitResponse(
            commit_hash="cafe0", synced=False, reason="already_synced",
        )
    monkeypatch.setattr("handlers.scan_branch.handle_link_commit", _noop_link)

    resp = await handle_scan_branch(ctx, base_ref="main")
    assert len(resp.decisions) == 1
    assert resp.decisions[0].intent_id == "i1"
    assert resp.drifted_count == 1
    assert resp.sweep_scope == "range_diff"
    assert resp.range_size == 2
    assert sorted(resp.files_changed) == ["a.py", "b.py"]


@pytest.mark.asyncio
async def test_scan_branch_status_counts_match_entries(monkeypatch):
    """Four decisions across two files with mixed statuses → count
    fields match the entries list exactly."""
    per_file = {
        "a.py": [
            _sample_decision("i1", "d1", status="drifted"),
            _sample_decision("i2", "d2", status="reflected"),
        ],
        "b.py": [
            _sample_decision("i3", "d3", status="pending"),
            _sample_decision("i4", "d4", status="ungrounded"),
        ],
    }
    ctx = _FakeCtx(_FakeLedger(per_file))
    monkeypatch.setattr(
        "handlers.scan_branch.get_changed_files_in_range",
        lambda base, head, repo: ["a.py", "b.py"],
    )
    monkeypatch.setattr(
        "handlers.scan_branch.resolve_ref",
        lambda ref, repo: "beef0" if ref != "HEAD" else "cafe0",
    )
    async def _noop_link(ctx, commit_hash):
        from contracts import LinkCommitResponse
        return LinkCommitResponse(
            commit_hash="cafe0", synced=False, reason="already_synced",
        )
    monkeypatch.setattr("handlers.scan_branch.handle_link_commit", _noop_link)

    resp = await handle_scan_branch(ctx, base_ref="main")
    assert len(resp.decisions) == 4
    assert resp.drifted_count == 1
    assert resp.reflected_count == 1
    assert resp.pending_count == 1
    assert resp.ungrounded_count == 1
    statuses = sorted(d.status for d in resp.decisions)
    assert statuses == ["drifted", "pending", "reflected", "ungrounded"]


@pytest.mark.asyncio
async def test_scan_branch_fires_review_drift_hint(monkeypatch):
    """Any drifted entry → response.action_hints contains a
    review_drift hint."""
    per_file = {
        "a.py": [_sample_decision("i1", "drifted decision", status="drifted")],
    }
    ctx = _FakeCtx(_FakeLedger(per_file))
    monkeypatch.setattr(
        "handlers.scan_branch.get_changed_files_in_range",
        lambda base, head, repo: ["a.py"],
    )
    monkeypatch.setattr(
        "handlers.scan_branch.resolve_ref",
        lambda ref, repo: "beef0" if ref != "HEAD" else "cafe0",
    )
    async def _noop_link(ctx, commit_hash):
        from contracts import LinkCommitResponse
        return LinkCommitResponse(
            commit_hash="cafe0", synced=False, reason="already_synced",
        )
    monkeypatch.setattr("handlers.scan_branch.handle_link_commit", _noop_link)

    resp = await handle_scan_branch(ctx, base_ref="main")
    assert len(resp.action_hints) >= 1
    kinds = [h.kind for h in resp.action_hints]
    assert "review_drift" in kinds
    # Normal mode — hint should be advisory, not blocking
    review_drift = next(h for h in resp.action_hints if h.kind == "review_drift")
    assert review_drift.blocking is False


@pytest.mark.asyncio
async def test_scan_branch_fires_ground_decision_hint(monkeypatch):
    """Ungrounded decisions → ground_decision hint."""
    per_file = {
        "a.py": [_sample_decision("i1", "ungrounded", status="ungrounded")],
    }
    ctx = _FakeCtx(_FakeLedger(per_file))
    monkeypatch.setattr(
        "handlers.scan_branch.get_changed_files_in_range",
        lambda base, head, repo: ["a.py"],
    )
    monkeypatch.setattr(
        "handlers.scan_branch.resolve_ref",
        lambda ref, repo: "beef0" if ref != "HEAD" else "cafe0",
    )
    async def _noop_link(ctx, commit_hash):
        from contracts import LinkCommitResponse
        return LinkCommitResponse(
            commit_hash="cafe0", synced=False, reason="already_synced",
        )
    monkeypatch.setattr("handlers.scan_branch.handle_link_commit", _noop_link)

    resp = await handle_scan_branch(ctx, base_ref="main")
    kinds = [h.kind for h in resp.action_hints]
    assert "ground_decision" in kinds


@pytest.mark.asyncio
async def test_scan_branch_range_truncated_at_cap(monkeypatch):
    """More than _MAX_SWEEP_FILES changed files → sweep_scope=range_truncated
    and range_size is capped."""
    from handlers.scan_branch import _MAX_SWEEP_FILES

    huge_range = [f"f{i}.py" for i in range(_MAX_SWEEP_FILES + 50)]
    ctx = _FakeCtx(_FakeLedger({}))  # all files empty — we're testing the cap, not content
    monkeypatch.setattr(
        "handlers.scan_branch.get_changed_files_in_range",
        lambda base, head, repo: huge_range,
    )
    monkeypatch.setattr(
        "handlers.scan_branch.resolve_ref",
        lambda ref, repo: "beef0" if ref != "HEAD" else "cafe0",
    )
    async def _noop_link(ctx, commit_hash):
        from contracts import LinkCommitResponse
        return LinkCommitResponse(
            commit_hash="cafe0", synced=False, reason="already_synced",
        )
    monkeypatch.setattr("handlers.scan_branch.handle_link_commit", _noop_link)

    resp = await handle_scan_branch(ctx, base_ref="main")
    assert resp.sweep_scope == "range_truncated"
    assert resp.range_size == _MAX_SWEEP_FILES
    assert len(resp.files_changed) == _MAX_SWEEP_FILES


@pytest.mark.asyncio
async def test_scan_branch_default_base_ref_uses_authoritative_env(monkeypatch):
    """When base_ref is omitted, the handler reads
    BICAMERAL_AUTHORITATIVE_REF from the environment."""
    monkeypatch.setenv("BICAMERAL_AUTHORITATIVE_REF", "release-2026-04")
    assert _default_base_ref() == "release-2026-04"

    monkeypatch.delenv("BICAMERAL_AUTHORITATIVE_REF", raising=False)
    assert _default_base_ref() == "main"


@pytest.mark.asyncio
async def test_scan_branch_working_tree_flag_threads_through(monkeypatch):
    """use_working_tree flag is reflected in response.source."""
    ctx = _FakeCtx(_FakeLedger({}))
    monkeypatch.setattr(
        "handlers.scan_branch.get_changed_files_in_range",
        lambda base, head, repo: [],
    )
    monkeypatch.setattr(
        "handlers.scan_branch.resolve_ref",
        lambda ref, repo: "beef0" if ref != "HEAD" else "cafe0",
    )
    async def _noop_link(ctx, commit_hash):
        from contracts import LinkCommitResponse
        return LinkCommitResponse(
            commit_hash="cafe0", synced=False, reason="already_synced",
        )
    monkeypatch.setattr("handlers.scan_branch.handle_link_commit", _noop_link)

    resp_head = await handle_scan_branch(ctx, base_ref="main", use_working_tree=False)
    assert resp_head.source == "HEAD"

    resp_wt = await handle_scan_branch(ctx, base_ref="main", use_working_tree=True)
    assert resp_wt.source == "working_tree"


# ── Layer 2: regression guard on the detect_drift refactor ──────────


def test_raw_decisions_to_drift_entries_pure_helper():
    """The extracted helper must produce the same per-entry shape as
    the pre-v0.4.17 in-line loop. This test locks in the shape so
    scan_branch and detect_drift can't diverge on a per-decision field."""
    raw = [
        {
            "intent_id": "i-reflected",
            "description": "reflected decision",
            "status": "reflected",
            "code_region": {"symbol": "Foo", "lines": [10, 20]},
            "source_ref": "sprint-1",
            "source_excerpt": "r excerpt",
            "meeting_date": "2026-04-01",
        },
        {
            "intent_id": "i-drifted",
            "description": "drifted decision",
            "status": "drifted",
            "code_region": {"symbol": "Bar", "lines": [30, 40]},
            "source_ref": "sprint-2",
            "source_excerpt": "d excerpt",
            "meeting_date": "2026-04-02",
        },
        {
            "intent_id": "i-pending",
            "description": "pending decision",
            "status": "pending",
            "code_region": {"symbol": "Baz", "lines": [50, 60]},
            "source_ref": "sprint-3",
            "source_excerpt": "p excerpt",
            "meeting_date": "2026-04-03",
        },
        {
            "intent_id": "i-ungrounded",
            "description": "ungrounded decision",
            "status": "ungrounded",
            "code_region": {},
            "source_ref": "sprint-4",
            "source_excerpt": "",
            "meeting_date": "",
        },
    ]
    entries, counts = raw_decisions_to_drift_entries(raw)

    assert len(entries) == 4
    assert counts == {
        "drifted": 1,
        "pending": 1,
        "ungrounded": 1,
        "reflected": 1,
    }
    # Drifted entries get the synthetic drift_evidence
    drifted = next(e for e in entries if e.status == "drifted")
    assert drifted.drift_evidence
    assert drifted.symbol == "Bar"
    assert drifted.lines == (30, 40)
    # Ungrounded / reflected have no drift evidence
    reflected = next(e for e in entries if e.status == "reflected")
    assert reflected.drift_evidence == ""
    # Empty code_region falls back to (0, 0) lines
    ungrounded = next(e for e in entries if e.status == "ungrounded")
    assert ungrounded.lines == (0, 0)


# ── Layer 3: integration against real surreal ledger + git repo ─────


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _seed_repo(repo_root: Path, body: str) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    _git(repo_root, "init", "-q", "-b", "main")
    _git(repo_root, "config", "user.email", "t@e.com")
    _git(repo_root, "config", "user.name", "t")
    (repo_root / "pricing.py").write_text(dedent(body).strip() + "\n")
    _git(repo_root, "add", ".")
    _git(
        repo_root,
        "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "seed",
    )


@pytest.fixture
def _isolated_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", "memory://")
    repo_root = tmp_path / "repo"
    _seed_repo(
        repo_root,
        """
        def calculate_discount(order_total):
            if order_total >= 100:
                return order_total * 0.10
            return 0
        """,
    )
    monkeypatch.setenv("REPO_PATH", str(repo_root))
    monkeypatch.setenv("BICAMERAL_AUTHORITATIVE_REF", "main")
    monkeypatch.chdir(repo_root)
    reset_ledger_singleton()
    yield repo_root
    reset_ledger_singleton()


def _payload_with_decision(repo: str, description: str) -> dict:
    return {
        "query": description,
        "repo": repo,
        "mappings": [
            {
                "span": {
                    "span_id": "v0417-scan-0",
                    "source_type": "transcript",
                    "text": description,
                    "source_ref": "v0417-scan-branch-test",
                    "meeting_date": "2026-04-15",
                },
                "intent": description,
                "symbols": ["calculate_discount"],
                "code_regions": [
                    {
                        "file_path": "pricing.py",
                        "symbol": "calculate_discount",
                        "type": "function",
                        "start_line": 1,
                        "end_line": 4,
                        "purpose": "pricing rule",
                    }
                ],
                "dependency_edges": [],
            }
        ],
    }


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_scan_branch_same_ref_is_empty(_isolated_ledger):
    """When base_ref == head_ref, there's nothing to scan — empty
    response with sweep_scope=head_only. This is the honest
    fall-through path."""
    ledger = get_ledger()
    await ledger.connect()
    ctx = BicameralContext.from_env()

    # Use HEAD as both base and head — no range.
    resp = await handle_scan_branch(ctx, base_ref="HEAD", head_ref="HEAD")
    assert resp.decisions == []
    assert resp.files_changed == []
    assert resp.sweep_scope == "head_only"
    assert resp.drifted_count == 0


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_scan_branch_single_file_range_end_to_end(_isolated_ledger):
    """Full integration: ingest a decision, commit a second version
    of the file, scan the branch. The decision should appear in the
    response because the range includes pricing.py."""
    ledger = get_ledger()
    await ledger.connect()
    ctx = BicameralContext.from_env()

    # Capture the seed commit as the base ref
    base_sha = _git(_isolated_ledger, "rev-parse", "HEAD")

    # Ingest a decision that maps to pricing.py:calculate_discount
    await handle_ingest(ctx, _payload_with_decision(
        repo=str(_isolated_ledger),
        description="Apply 10% discount on orders of $100 or more",
    ))

    # Make a second commit that touches pricing.py so the range
    # includes it. Also invalidates the pollution guard.
    (_isolated_ledger / "pricing.py").write_text(
        "def calculate_discount(order_total):\n"
        "    if order_total >= 100:\n"
        "        return order_total * 0.15  # rate changed\n"
        "    return 0\n"
    )
    _git(_isolated_ledger, "add", "pricing.py")
    _git(
        _isolated_ledger,
        "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "bump discount rate",
    )

    resp = await handle_scan_branch(
        ctx, base_ref=base_sha, head_ref="HEAD",
    )
    # The range should be range_diff (not head_only) since base != head
    assert resp.sweep_scope == "range_diff"
    # pricing.py is in the range
    assert "pricing.py" in resp.files_changed
    # At least one decision surfaced (the one we just ingested)
    assert len(resp.decisions) >= 1
    # Descriptions include our ingested text
    descriptions = [d.description for d in resp.decisions]
    assert any("10%" in d or "discount" in d.lower() for d in descriptions)


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_detect_drift_still_works_after_helper_refactor(_isolated_ledger):
    """Regression guard: handle_detect_drift must still return a
    valid DetectDriftResponse after raw_decisions_to_drift_entries
    was extracted. Byte-identical output isn't required (the refactor
    changed nothing observable), but the shape must be preserved."""
    ledger = get_ledger()
    await ledger.connect()
    ctx = BicameralContext.from_env()

    await handle_ingest(ctx, _payload_with_decision(
        repo=str(_isolated_ledger),
        description="Apply 10% discount on orders of $100 or more",
    ))

    resp = await handle_detect_drift(ctx, file_path="pricing.py")
    assert resp.file_path == "pricing.py"
    assert resp.source in ("working_tree", "HEAD")
    assert isinstance(resp.decisions, list)
    assert resp.drifted_count >= 0
    assert resp.pending_count >= 0
    # The sample decision should show up in the per-file drift response
    assert len(resp.decisions) >= 1
    # Each entry should be a DriftEntry with the v0.4.14 source_excerpt
    # field plumbed through
    entry = resp.decisions[0]
    assert isinstance(entry, DriftEntry)
    assert hasattr(entry, "source_excerpt")
    assert hasattr(entry, "meeting_date")
