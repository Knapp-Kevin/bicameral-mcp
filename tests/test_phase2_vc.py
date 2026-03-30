"""Phase 2 version-control integration tests.

Simulates real git operations against a controlled temporary repo to verify
the content-hash bridge between the decision ledger and git history.

These are the hardest tests — they require:
  - USE_REAL_LEDGER=1 (SurrealDBLedgerAdapter)
  - A real git binary on PATH
  - A writable tmp directory for the controlled repo

Run:
    USE_REAL_LEDGER=1 pytest tests/test_phase2_vc.py -v

See docs/architecture/version-control-integration.md for design rationale.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from handlers.decision_status import handle_decision_status
from handlers.detect_drift import handle_detect_drift
from handlers.link_commit import handle_link_commit


# ---------------------------------------------------------------------------
# Fixture: minimal controlled git repo
# ---------------------------------------------------------------------------

@pytest.fixture
def controlled_repo(tmp_path):
    """A real git repo with two commits for deterministic VC testing.

    Commit c1: PaymentService.retry with no backoff (v1 stub)
    Commit c2: PaymentService.retry with exponential backoff (the decision implemented)
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args, **kwargs):
        return subprocess.run(
            ["git"] + list(args),
            cwd=repo,
            check=True,
            capture_output=True,
        )

    git("init")
    git("config", "user.email", "test@bicameral.ai")
    git("config", "user.name", "VC Test")

    # c1: stub implementation — no backoff
    (repo / "payments.py").write_text(
        "class PaymentService:\n"
        "    def retry(self, n=3):\n"
        "        pass  # v1: no backoff yet\n"
    )
    git("add", ".")
    git("commit", "-m", "initial: PaymentService stub")
    c1 = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).decode().strip()

    # c2: real implementation — exponential backoff added
    (repo / "payments.py").write_text(
        "class PaymentService:\n"
        "    def retry(self, n=3):\n"
        "        import time\n"
        "        for i in range(n):\n"
        "            time.sleep(2 ** i)  # exponential backoff\n"
    )
    git("add", ".")
    git("commit", "-m", "feat: add exponential backoff to PaymentService.retry")
    c2 = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).decode().strip()

    return {"repo": repo, "c1": c1, "c2": c2, "git": git}


# ---------------------------------------------------------------------------
# Fixture: enable real adapters
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def enable_real_ledger(monkeypatch, surreal_url, controlled_repo):
    """All Phase 2 VC tests run with real SurrealDB ledger."""
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("USE_REAL_CODE_LOCATOR", "0")
    monkeypatch.setenv("SURREAL_URL", surreal_url)
    monkeypatch.setenv("REPO_PATH", str(controlled_repo["repo"]))


# ---------------------------------------------------------------------------
# Test 1: pending → reflected transition on commit
# ---------------------------------------------------------------------------

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_link_commit_transitions_pending_to_reflected(controlled_repo, real_ledger):
    """After a commit that implements a pending decision, status becomes reflected.

    Sequence:
    1. Ingest decision about exponential backoff (pending — code has stub only)
    2. link_commit(c1) — baseline: stub present, no backoff → pending
    3. link_commit(c2) — backoff added → reflected
    """
    await real_ledger.connect()

    # Ingest decision mapped to PaymentService.retry
    await real_ledger.ingest_intent({
        "description": "PaymentService.retry must implement exponential backoff",
        "feature_hint": "payments",
        "symbol": "PaymentService.retry",
        "file_path": "payments.py",
        "start_line": 2,
        "end_line": 3,
    })

    # Baseline: c1 has stub, no backoff → pending
    await handle_link_commit(controlled_repo["c1"])
    status = await handle_decision_status(filter="all")
    pending = [d for d in status.decisions if d.status == "pending"]
    assert pending, f"Expected pending status after c1 (no backoff), got: {[d.status for d in status.decisions]}"

    # c2 adds backoff → should transition to reflected
    await handle_link_commit(controlled_repo["c2"])
    status = await handle_decision_status(filter="all")
    reflected = [d for d in status.decisions if d.status == "reflected"]
    assert reflected, (
        f"Expected reflected after c2 (backoff present), got: {[d.status for d in status.decisions]}"
    )


# ---------------------------------------------------------------------------
# Test 2: link_commit idempotency on real git
# ---------------------------------------------------------------------------

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_link_commit_idempotent_on_real_git(controlled_repo, real_ledger):
    """Calling link_commit twice for the same commit is a no-op.

    Validates: ledger_sync cursor prevents re-processing the same SHA.
    """
    await real_ledger.connect()

    r1 = await handle_link_commit(controlled_repo["c2"])
    r2 = await handle_link_commit(controlled_repo["c2"])

    assert r1.commit_hash == r2.commit_hash
    assert r2.reason == "already_synced", (
        f"Second link_commit for same SHA should return already_synced, got: {r2.reason}"
    )
    assert r2.regions_updated == 0, "No regions should be updated on second call"


# ---------------------------------------------------------------------------
# Test 3: detect_drift catches working tree violation
# ---------------------------------------------------------------------------

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_detect_drift_catches_working_tree_violation(controlled_repo, real_ledger):
    """detect_drift(use_working_tree=True) catches an uncommitted change that violates a decision.

    Simulates: developer removes the backoff in a WIP change. Pre-commit hook
    should surface the drift before the bad change is committed.
    """
    await real_ledger.connect()
    repo = controlled_repo["repo"]

    await real_ledger.ingest_intent({
        "description": "PaymentService.retry must implement exponential backoff",
        "feature_hint": "payments",
        "symbol": "PaymentService.retry",
        "file_path": "payments.py",
        "start_line": 2,
        "end_line": 6,
    })
    await handle_link_commit(controlled_repo["c2"])  # baseline = backoff present

    # Working tree: developer removes the backoff (bad refactor, not committed)
    (repo / "payments.py").write_text(
        "class PaymentService:\n"
        "    def retry(self, n=3):\n"
        "        pass  # backoff removed in WIP change\n"
    )

    result = await handle_detect_drift("payments.py", use_working_tree=True)

    assert result.drifted_count > 0, (
        "Working tree drift should be detected before the bad change is committed. "
        f"Got drifted_count={result.drifted_count}, decisions={result.decisions}"
    )
    drifted = [d for d in result.decisions if d.status == "drifted"]
    assert drifted, "The exponential backoff decision should be flagged as drifted"


# ---------------------------------------------------------------------------
# Test 4: rebase does not change status (content-hash stability)
# ---------------------------------------------------------------------------

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_rebase_does_not_change_status(controlled_repo, real_ledger):
    """After amend/rebase with same content, content_hash is identical → status unchanged.

    This is the core property of the content-hash bridge: it is immune to
    history rewrites that don't change actual file content.
    """
    await real_ledger.connect()
    repo = controlled_repo["repo"]

    await real_ledger.ingest_intent({
        "description": "PaymentService.retry must implement exponential backoff",
        "feature_hint": "payments",
        "symbol": "PaymentService.retry",
        "file_path": "payments.py",
    })
    await handle_link_commit(controlled_repo["c2"])
    status_before = await handle_decision_status()

    # Simulate rebase: amend the commit with the same content (new SHA, same code)
    env_patch = {"GIT_COMMITTER_DATE": "2030-01-01T00:00:00+00:00"}
    subprocess.run(
        ["git", "commit", "--amend", "--no-edit", "--reset-author"],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**__import__("os").environ, **env_patch},
    )
    new_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo
    ).decode().strip()

    assert new_sha != controlled_repo["c2"], "Amend should produce a new SHA"

    await handle_link_commit(new_sha)
    status_after = await handle_decision_status()

    before = {d.description: d.status for d in status_before.decisions}
    after = {d.description: d.status for d in status_after.decisions}
    assert before == after, (
        f"Rebase with same content should not change status.\n"
        f"Before: {before}\nAfter: {after}"
    )


# ---------------------------------------------------------------------------
# Test 5: undocumented symbol flagged
# ---------------------------------------------------------------------------

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_undocumented_symbol_flagged_on_link_commit(controlled_repo, real_ledger):
    """A new symbol added in a commit with no mapped intent is flagged as undocumented.

    This is the reverse detection case: code → no intent (vs. normal intent → code).
    """
    await real_ledger.connect()
    repo = controlled_repo["repo"]

    # Add a new method with no corresponding decision in the ledger
    (repo / "payments.py").write_text(
        "class PaymentService:\n"
        "    def retry(self, n=3):\n"
        "        import time\n"
        "        for i in range(n):\n"
        "            time.sleep(2 ** i)\n"
        "    def refund(self, amount):  # new symbol — no decision exists\n"
        "        pass\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add refund method (undocumented)"],
        cwd=repo, check=True, capture_output=True,
    )
    c3 = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).decode().strip()

    result = await handle_link_commit(c3)

    assert any("refund" in sym for sym in result.undocumented_symbols), (
        f"PaymentService.refund should appear in undocumented_symbols. "
        f"Got: {result.undocumented_symbols}"
    )


# ---------------------------------------------------------------------------
# Test 6: search_decisions auto-syncs before returning results
# ---------------------------------------------------------------------------

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_search_decisions_auto_syncs_to_head(controlled_repo, real_ledger):
    """search_decisions auto-triggers link_commit(HEAD) before searching.

    Verifies that the sync_status in the response reflects HEAD even if
    link_commit was never called manually.
    """
    from handlers.search_decisions import handle_search_decisions

    await real_ledger.connect()

    await real_ledger.ingest_intent({
        "description": "PaymentService.retry must implement exponential backoff",
        "feature_hint": "payments",
        "symbol": "PaymentService.retry",
        "file_path": "payments.py",
    })

    # Don't call link_commit manually — search_decisions should do it
    result = await handle_search_decisions(query="exponential backoff retry")

    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=controlled_repo["repo"]
    ).decode().strip()

    assert result.sync_status.commit_hash == head, (
        f"search_decisions should auto-sync to HEAD ({head}), "
        f"got sync_status.commit_hash={result.sync_status.commit_hash}"
    )
