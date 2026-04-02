"""
Grounding State Machine — Gap Coverage Tests

Exhaustively documents every known way the ingest → ground → persist pipeline
can silently fail, producing permanently-ungrounded intents with no recovery path.

State machine:

    ingest() ──► [ungrounded]  ──► (auto-ground) ──► [pending] ──► link_commit() ──► [reflected]
                                                                                   └──► [drifted]

Gaps occur when:
  A. An intent enters [ungrounded] and has no automatic path out.
  B. A transition fires incorrectly (false positive / false negative).
  C. A diagnostic signal is missing (caller cannot tell *why* grounding failed).

─────────────────────────────────────────────────────────────────────────────
Gap catalogue (all gaps documented below as tests):

  GAP-01  Index unavailable at ingest time → silent no-op, permanent ungrounded
  GAP-02  symbols[] set but resolution fails → auto-ground skips → ungrounded
  GAP-03  AUTO_GROUND_THRESHOLD compared against raw BM25 scores (always passes)
  GAP-04  No re-grounding pass → stale ungrounded intents never recover
  GAP-05  Partial index (BM25 missing, symbol DB present) → stage-1 silent fail
  GAP-06  Empty REPO_PATH + missing CODE_LOCATOR_SQLITE_DB → auto-ground skips all
  GAP-07  IngestResponse carries no grounding_deferred/grounding_skipped signal
  GAP-08  symbols[] partially resolves → unresolved names silently dropped
  GAP-09  link_commit does not trigger re-grounding for ungrounded intents
─────────────────────────────────────────────────────────────────────────────

Run:
    cd pilot/mcp && .venv/bin/python -m pytest tests/test_grounding_state_machine_gaps.py -v
"""
from __future__ import annotations

import os
import sys
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("USE_REAL_LEDGER", "1")
os.environ.setdefault("SURREAL_URL", "memory://")

from adapters.ledger import get_ledger, reset_ledger_singleton
from handlers.ingest import handle_ingest
from handlers.decision_status import handle_decision_status
from code_locator.indexing.index_builder import build_index
from code_locator.indexing.sqlite_store import SymbolDB


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("SURREAL_URL", "memory://")
    reset_ledger_singleton()
    yield
    reset_ledger_singleton()


@pytest.fixture
def indexed_repo(tmp_path, monkeypatch):
    """Temp repo with source files + both symbol DB and BM25 index built."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".bicameral").mkdir()

    (repo / "payments").mkdir()
    (repo / "payments" / "handler.py").write_text(
        "def process_payment(amount, currency):\n"
        "    \"\"\"Process a payment.\"\"\"\n"
        "    return {'status': 'ok', 'amount': amount}\n"
        "\n"
        "def process_refund(order_id, reason):\n"
        "    \"\"\"Process a refund.\"\"\"\n"
        "    return {'refunded': True}\n"
    )

    db_path = str(repo / ".bicameral" / "code-graph.db")
    monkeypatch.setenv("REPO_PATH", str(repo))
    monkeypatch.delenv("CODE_LOCATOR_SQLITE_DB", raising=False)

    stats = build_index(str(repo), db_path)
    assert stats.symbols_extracted > 0, "Test setup broken: no symbols extracted"

    from code_locator.retrieval.bm25s_client import Bm25sClient
    bm25 = Bm25sClient()
    bm25.index(str(repo), str(repo / ".bicameral"))

    return str(repo), db_path


@pytest.fixture
def symbol_db_only_repo(tmp_path, monkeypatch):
    """Repo with symbol DB but NO BM25 index (partial index state)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".bicameral").mkdir()

    (repo / "auth").mkdir()
    (repo / "auth" / "login.py").write_text(
        "def authenticate_user(username, password):\n"
        "    \"\"\"Authenticate a user.\"\"\"\n"
        "    return True\n"
    )

    db_path = str(repo / ".bicameral" / "code-graph.db")
    monkeypatch.setenv("REPO_PATH", str(repo))
    monkeypatch.delenv("CODE_LOCATOR_SQLITE_DB", raising=False)
    monkeypatch.delenv("USE_REAL_CODE_LOCATOR", raising=False)

    build_index(str(repo), db_path)
    # Intentionally NOT building BM25 index — simulates partial index state

    return str(repo), db_path


def _payload(intent: str, repo: str, symbols: list[str] | None = None,
             code_regions: list[dict] | None = None) -> dict:
    return {
        "repo": repo,
        "commit_hash": "HEAD",
        "mappings": [{
            "span": {
                "text": intent,
                "source_type": "transcript",
                "source_ref": "gap-test",
            },
            "intent": intent,
            "symbols": symbols or [],
            "code_regions": code_regions or [],
        }],
    }


# ── GAP-01: Index unavailable → silent no-op ──────────────────────────


@pytest.mark.asyncio
async def test_gap01_index_unavailable_causes_silent_ungrounded(tmp_path, monkeypatch):
    """
    GAP-01: When code-graph.db does not exist at ingest time, _auto_ground_via_search
    catches the exception and silently returns the unmutated mappings list.  The intents
    are stored permanently ungrounded.  There is no flag on the response that tells the
    caller 'grounding was skipped — retry after building the index'.

    Status: KNOWN BUG (affects ≤ 0.2.11).
    Fix: surface grounding_deferred: True on IngestResponse / IngestStats.
    """
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    monkeypatch.setenv("REPO_PATH", repo)
    monkeypatch.delenv("CODE_LOCATOR_SQLITE_DB", raising=False)
    # No index built — code-graph.db does not exist

    result = await handle_ingest(_payload("Payment processing refund logic", repo))

    # The intent is silently stored as ungrounded
    assert result.stats.ungrounded == 1

    # BUG: IngestResponse should expose a signal that grounding was skipped,
    # not silently failed, so the caller knows to rebuild the index and re-ingest.
    has_deferred_signal = (
        hasattr(result.stats, "grounding_deferred") or
        hasattr(result, "grounding_deferred") or
        hasattr(result, "grounding_skipped")
    )
    if not has_deferred_signal:
        pytest.xfail(
            "GAP-01: IngestResponse has no grounding_deferred/grounding_skipped field. "
            "Caller cannot distinguish 'intent is ungroundable' from 'index not built yet'."
        )


# ── GAP-02: symbols[] set but resolution fails → auto-ground skips ────


@pytest.mark.asyncio
async def test_gap02_symbols_set_but_db_has_no_tables_raises_uncaught(tmp_path, monkeypatch):
    """
    GAP-02 (sub-gap): _resolve_symbols_to_regions wraps only the SymbolDB()
    constructor in try/except.  When SQLite creates an empty db file (no init_db()
    call), the constructor succeeds but db.lookup_by_name() raises
    sqlite3.OperationalError: no such table: symbols — unhandled, crashing the
    entire ingest call.

    Root cause: the try/except in _resolve_symbols_to_regions (lines 170-175)
    does not cover the lookup_by_name call that follows.

    Status: KNOWN BUG — the exception propagates out of handle_ingest uncaught.
    Fix: wrap the per-symbol lookup loop in a try/except, or call db.init_db()
         before lookup so the table always exists (init_db is idempotent).
    """
    repo = str(tmp_path / "repo")
    os.makedirs(repo, exist_ok=True)
    bicameral = os.path.join(repo, ".bicameral")
    os.makedirs(bicameral, exist_ok=True)
    # Create an empty (no-table) sqlite file — simulates a DB created but never init'd
    empty_db = os.path.join(bicameral, "code-graph.db")
    sqlite3.connect(empty_db).close()

    monkeypatch.setenv("REPO_PATH", repo)
    monkeypatch.delenv("CODE_LOCATOR_SQLITE_DB", raising=False)

    payload = _payload(
        "Handle subscription created events",
        repo,
        symbols=["handleSubscriptionCreated"],
    )

    # The bug: handle_ingest raises sqlite3.OperationalError instead of
    # gracefully returning ungrounded=1.
    try:
        result = await handle_ingest(payload)
        # If we get here without raising, the fix is in place — verify graceful degradation
        assert result.stats.ungrounded == 1, (
            "With empty DB and unresolvable symbol, intent should be ungrounded"
        )
    except Exception as exc:
        pytest.xfail(
            f"GAP-02: handle_ingest raises {type(exc).__name__} when DB exists but has no "
            f"tables. The lookup_by_name call in _resolve_symbols_to_regions is not "
            f"covered by the try/except block. Fix: wrap per-symbol lookup in try/except "
            f"or call db.init_db() before lookup. Error: {exc}"
        )


@pytest.mark.asyncio
async def test_gap02b_symbols_not_in_index_blocks_auto_ground(indexed_repo, monkeypatch):
    """
    GAP-02 (concrete): Symbol not in index → _resolve_symbols_to_regions leaves
    code_regions=[], symbols=['missing_fn'] intact.  _auto_ground_via_search sees
    symbols truthy and skips the BM25/fuzzy path even though it might find relevant
    code via text search on the intent description.

    Status: KNOWN BUG.
    """
    repo, _ = indexed_repo
    monkeypatch.setenv("USE_REAL_CODE_LOCATOR", "1")

    payload = _payload(
        "process payment amounts",  # matches process_payment in the index
        repo,
        symbols=["completely_missing_fn"],  # symbol not in index
        code_regions=[],
    )
    result = await handle_ingest(payload)

    # With the bug: auto-ground skips because symbols is truthy → ungrounded
    # After fix: auto-ground falls through to BM25/fuzzy and finds process_payment
    if result.stats.ungrounded == 1 and result.stats.symbols_mapped == 0:
        pytest.xfail(
            "GAP-02b: mapping with symbols=['missing_fn'] + code_regions=[] is skipped "
            "by _auto_ground_via_search. BM25/fuzzy fallback never fires. "
            "Fix: guard should be `if mapping.get('code_regions'):` only."
        )


# ── GAP-03: BM25 threshold vs raw scores ──────────────────────────────


@pytest.mark.asyncio
async def test_gap03_bm25_threshold_is_raw_score_not_normalised(indexed_repo, monkeypatch):
    """
    GAP-03: AUTO_GROUND_THRESHOLD = 0.5 is documented as '0–1 normalised' but
    search_code returns raw BM25 scores (observed: 7–12 in practice).  The threshold
    is therefore permanently meaningless — every real BM25 hit passes regardless of
    relevance quality.  This causes over-grounding rather than under-grounding, which
    is the lesser evil, but it means precision calibration cannot be done by adjusting
    AUTO_GROUND_THRESHOLD until scores are normalised.

    This test documents the current behaviour (raw scores >> 0.5) so a future
    normalisation change doesn't regress silently.
    """
    repo, _ = indexed_repo
    monkeypatch.setenv("USE_REAL_CODE_LOCATOR", "1")

    from adapters.code_locator import get_code_locator
    locator = get_code_locator()

    hits = locator.search_code("process payment")
    if not hits:
        pytest.skip("BM25 returned no hits — index may not be ready")

    top_score = hits[0].get("score", 0)

    # Document: if raw BM25 scores exceed 1.0, the 0.5 threshold is useless for
    # fine-grained relevance filtering.
    from handlers.ingest import AUTO_GROUND_THRESHOLD
    if top_score > 1.0:
        # Raw score — threshold comparison is semantically broken
        # Not an xfail because over-grounding is acceptable short-term;
        # just assert the documented behaviour so it's visible.
        assert top_score > AUTO_GROUND_THRESHOLD, (
            f"Expected raw score {top_score:.2f} > threshold {AUTO_GROUND_THRESHOLD} "
            "(threshold is effectively always-pass for real BM25 hits)"
        )


# ── GAP-04: No re-grounding pass → stale ungrounded never recovers ────


@pytest.mark.asyncio
async def test_gap04_ungrounded_intent_not_regrounded_after_index_built(
    tmp_path, monkeypatch, indexed_repo
):
    """
    GAP-04: Sequence that leaves ledger permanently poisoned:
      1. Ingest intents BEFORE index is built → ungrounded
      2. Index is built
      3. No re-grounding pass is triggered automatically

    link_commit and detect_drift do NOT re-run _auto_ground_via_search on
    existing ungrounded intents.  Once an intent is stored ungrounded, it
    stays that way forever unless the caller manually re-ingests.

    Status: KNOWN GAP — no lazy re-grounding implemented.
    Fix: in link_commit, for intents with code_regions == [], re-run
         _auto_ground_via_search before the drift check.
    """
    # Step 1: ingest into an empty repo (no index yet)
    no_index_repo = str(tmp_path / "empty_repo")
    os.makedirs(no_index_repo)
    monkeypatch.setenv("REPO_PATH", no_index_repo)
    monkeypatch.delenv("CODE_LOCATOR_SQLITE_DB", raising=False)

    result_before = await handle_ingest(
        _payload("process payment refund", no_index_repo)
    )
    assert result_before.stats.ungrounded == 1, "Should be ungrounded — no index yet"

    # Step 2: now the index exists (indexed_repo fixture built it in a different path,
    # but we point REPO_PATH at it to simulate "index built after the fact")
    indexed_path, _ = indexed_repo
    monkeypatch.setenv("REPO_PATH", indexed_path)

    # Step 3: check whether the previously ungrounded intent recovered
    status = await handle_decision_status(filter="ungrounded")
    still_ungrounded = [
        d for d in status.decisions
        if "process payment refund" in d.description.lower()
    ]

    if still_ungrounded:
        pytest.xfail(
            "GAP-04: Ungrounded intent not re-grounded after index became available. "
            "There is no lazy re-grounding pass in link_commit or detect_drift. "
            "Fix: for code_regions==[] intents, re-run _auto_ground_via_search in link_commit."
        )


# ── GAP-05: Partial index (symbol DB present, BM25 missing) ───────────


@pytest.mark.asyncio
async def test_gap05_bm25_missing_stage1_fails_silently(symbol_db_only_repo, monkeypatch):
    """
    GAP-05: If code-graph.db exists but bm25_index.pkl was never built (or was
    deleted), Stage 1 BM25 search raises an exception that is caught and logged
    at WARNING level.  Stage 2 fuzzy matching still fires against the symbol DB.

    This is not a hard failure — stage 2 provides a fallback.  But the warning
    is the only signal.  This test verifies that stage 2 still grounds the intent
    even when BM25 is unavailable, and documents the partial-index behaviour.
    """
    repo, _ = symbol_db_only_repo
    monkeypatch.setenv("USE_REAL_CODE_LOCATOR", "1")

    # authenticate_user is in the symbol DB; BM25 index doesn't exist
    result = await handle_ingest(_payload("authenticate user login", repo))

    # Stage 2 fuzzy should still find authenticate_user via token matching
    # This may xfail depending on whether the fuzzy threshold is met
    if result.stats.ungrounded == 1:
        pytest.xfail(
            "GAP-05: Stage 2 fuzzy token matching did not ground intent when BM25 "
            "index was absent. Either the threshold is too strict or validate_symbols "
            "failed silently. Partial-index state leaves intents ungrounded."
        )
    else:
        # Stage 2 succeeded — document that partial index is tolerated
        assert result.stats.symbols_mapped > 0


# ── GAP-06: Missing REPO_PATH + missing DB env → skips all auto-ground ─


@pytest.mark.asyncio
async def test_gap06_missing_repo_path_skips_auto_ground(monkeypatch):
    """
    GAP-06: _auto_ground_via_search derives db_path from:
      1. CODE_LOCATOR_SQLITE_DB env var
      2. fallback: os.path.join(repo, ".bicameral", "code-graph.db")

    When the ingest payload's 'repo' field is empty and REPO_PATH is unset,
    `repo` defaults to '.' — db_path becomes './.bicameral/code-graph.db'.
    If that path doesn't exist, the exception handler fires and returns
    mappings unchanged.  Silent failure, no diagnostic.
    """
    monkeypatch.delenv("REPO_PATH", raising=False)
    monkeypatch.delenv("CODE_LOCATOR_SQLITE_DB", raising=False)

    payload = {
        "repo": "",  # Empty — will default to os.getenv("REPO_PATH", ".")
        "commit_hash": "HEAD",
        "mappings": [{
            "span": {"text": "process payment", "source_type": "transcript", "source_ref": "gap-test"},
            "intent": "process payment",
            "symbols": [],
            "code_regions": [],
        }],
    }
    result = await handle_ingest(payload)

    # Expect ungrounded due to missing DB — and no error raised
    assert result.stats.ungrounded == 1
    # No crash is the basic safety contract
    assert result.ingested is True


# ── GAP-07: IngestResponse missing grounding_deferred signal ──────────


@pytest.mark.asyncio
async def test_gap07_ingest_response_has_no_grounding_deferred_field(tmp_path, monkeypatch):
    """
    GAP-07: IngestResponse / IngestStats has no field that distinguishes:
      - 'intent is ungroundable' (no matching code exists)
      - 'grounding was skipped because the index is not ready'

    This means a caller (e.g. MCP client, setup wizard) cannot tell the user
    "re-ingest after building the index" vs "this decision has no code counterpart".

    Status: KNOWN GAP — grounding_deferred field not yet implemented.
    Fix: add grounding_deferred: int to IngestStats; increment when
         _auto_ground_via_search catches an exception in the setup block.
    """
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    monkeypatch.setenv("REPO_PATH", repo)
    monkeypatch.delenv("CODE_LOCATOR_SQLITE_DB", raising=False)

    result = await handle_ingest(_payload("payment logic", repo))

    from contracts import IngestStats
    has_field = hasattr(IngestStats, "grounding_deferred") or hasattr(IngestStats.model_fields, "grounding_deferred") if hasattr(IngestStats, "model_fields") else False

    if not has_field:
        pytest.xfail(
            "GAP-07: IngestStats.grounding_deferred field does not exist. "
            "Callers cannot distinguish 'no match' from 'index not built'. "
            "Fix: add grounding_deferred: int = 0 to IngestStats and contracts."
        )


# ── GAP-08: symbols[] partially resolves, missing names silently dropped ─


@pytest.mark.asyncio
async def test_gap08_partial_symbol_resolution_drops_missing_names(indexed_repo, monkeypatch):
    """
    GAP-08: _resolve_symbols_to_regions iterates over symbols[] and calls
    db.lookup_by_name(name) for each.  If a name is not found, the loop
    continues silently — no warning, no flag on the mapping.

    Payload: symbols=["process_refund", "completely_missing_fn"]
    Expected: process_refund resolves, missing_fn silently dropped.
    Bug: caller has no way to know that only partial resolution succeeded.
    """
    repo, _ = indexed_repo

    payload = {
        "repo": repo,
        "commit_hash": "HEAD",
        "mappings": [{
            "span": {"text": "refund and some unknown logic", "source_type": "transcript", "source_ref": "gap-test"},
            "intent": "refund and some unknown logic",
            "symbols": ["process_refund", "fn_that_does_not_exist_anywhere"],
            "code_regions": [],
        }],
    }
    result = await handle_ingest(payload)

    # process_refund should be found → symbols_mapped > 0
    assert result.stats.symbols_mapped > 0, (
        "process_refund should resolve even when a sibling symbol is missing"
    )

    # The intent is grounded (partial resolution is acceptable)
    assert result.stats.ungrounded == 0

    # GAP: there is no field indicating that fn_that_does_not_exist_anywhere
    # was requested but not resolved.  Document this expectation:
    # result.stats.symbols_requested == 2, result.stats.symbols_resolved == 1
    # Currently both fields don't exist.


# ── GAP-09: link_commit does not trigger re-grounding ─────────────────


def _git(repo_dir: str, *args) -> str:
    result = subprocess.run(
        ["git"] + list(args), cwd=repo_dir, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


@pytest.fixture
def indexed_git_repo(tmp_path, monkeypatch):
    """Temp repo that is BOTH a real git repo AND has a built symbol+BM25 index."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".bicameral").mkdir()
    (repo / "payments").mkdir()
    (repo / "payments" / "handler.py").write_text(
        "def process_payment(amount, currency):\n"
        "    \"\"\"Process a payment.\"\"\"\n"
        "    return {'status': 'ok', 'amount': amount}\n"
    )

    _git(str(repo), "init")
    _git(str(repo), "config", "user.email", "test@bicameral.ai")
    _git(str(repo), "config", "user.name", "Gap Test")
    _git(str(repo), "add", "-A")
    _git(str(repo), "commit", "-m", "initial")

    db_path = str(repo / ".bicameral" / "code-graph.db")
    monkeypatch.setenv("REPO_PATH", str(repo))
    monkeypatch.delenv("CODE_LOCATOR_SQLITE_DB", raising=False)

    stats = build_index(str(repo), db_path)
    assert stats.symbols_extracted > 0

    from code_locator.retrieval.bm25s_client import Bm25sClient
    bm25 = Bm25sClient()
    bm25.index(str(repo), str(repo / ".bicameral"))

    return str(repo), db_path


@pytest.mark.asyncio
async def test_gap09_link_commit_does_not_reground_ungrounded_intents(indexed_git_repo, monkeypatch):
    """
    GAP-09: link_commit (via ingest_commit) processes code diffs and updates
    existing intent statuses (pending→reflected, reflected→drifted).  It does NOT
    re-run _auto_ground_via_search on intents that have code_regions == [].

    Steps:
      1. Store an intent as explicitly ungrounded by bypassing auto-ground
      2. Call link_commit on the repo's HEAD commit
      3. Verify the intent is still ungrounded (gap documented)

    Status: KNOWN GAP.
    Fix: in ingest_commit, after processing diffs, collect ungrounded intents
         and pass them through _auto_ground_via_search.
    """
    repo, _ = indexed_git_repo

    # Ingest directly into the ledger (not via handle_ingest — bypasses auto-ground)
    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()

    ungrounded_payload = {
        "repo": repo,
        "commit_hash": "HEAD",
        "mappings": [{
            "span": {"text": "process payment amounts", "source_type": "transcript", "source_ref": "gap-test"},
            "intent": "process payment amounts",
            "symbols": [],
            "code_regions": [],  # Explicitly empty — stored as ungrounded
        }],
    }
    await ledger.ingest_payload(ungrounded_payload)

    # Verify ungrounded
    status_before = await handle_decision_status(filter="ungrounded")
    ungrounded = [d for d in status_before.decisions if "process payment amounts" in d.description.lower()]
    assert len(ungrounded) == 1, "Setup: intent should be ungrounded"

    # Trigger link_commit on HEAD — this is where lazy re-grounding SHOULD fire
    from handlers.link_commit import handle_link_commit
    head = _git(repo, "rev-parse", "HEAD")
    await handle_link_commit(head)  # handle_link_commit(commit_hash: str)

    # Check if the intent was re-grounded
    status_after = await handle_decision_status(filter="all")
    still_ungrounded = [
        d for d in status_after.decisions
        if "process payment amounts" in d.description.lower() and d.status == "ungrounded"
    ]

    if still_ungrounded:
        pytest.xfail(
            "GAP-09: link_commit does not re-ground ungrounded intents. "
            "Intent 'process payment amounts' exists in the symbol index but link_commit "
            "left it ungrounded. Fix: add lazy re-grounding pass in ingest_commit "
            "for intents with code_regions == []."
        )
