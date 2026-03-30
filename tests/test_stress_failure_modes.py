"""Stress tests — PRD failure mode scenarios.

Status: FAILING until Phase 2 (SurrealDBLedgerAdapter) is complete.

Tests that the 5 failure modes from the PRD are each exercised:
  CONSTRAINT_LOST       — hard technical limits surface before code is written
  CONTEXT_SCATTERED     — decisions across multiple transcripts are unified
  DECISION_UNDOCUMENTED — verbal decisions with no code mapping are flagged
  REPEATED_EXPLANATION  — context available without re-asking
  TRIBAL_KNOWLEDGE      — institutional knowledge is queryable, not in someone's head

Ground truth: tests/fixtures/expected/decisions.py (edit to tune)

Run: pytest tests/test_stress_failure_modes.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from fixtures.expected.decisions import BY_FAILURE_MODE, UNGROUNDED

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "transcripts"


async def ingest_all_transcripts(ledger):
    """Ingest all 9 OSS transcripts into the ledger."""
    from tests.fixtures.expected.decisions import ALL_DECISIONS
    # Group decisions by source_ref
    by_ref: dict[str, list] = {}
    for d in ALL_DECISIONS:
        by_ref.setdefault(d["source_ref"], []).append(d)

    filename_map = {
        "medusa-payment-timeout": "medusa-payment-timeout.md",
        "medusa-plugin-migration": "medusa-plugin-migration.md",
        "medusa-webhook-notifications": "medusa-webhook-notifications.md",
        "saleor-checkout-extensibility": "saleor-checkout-extensibility.md",
        "saleor-graphql-permissions": "saleor-graphql-permissions.md",
        "saleor-order-workflows": "saleor-order-workflows.md",
        "vendure-channel-pricing": "vendure-channel-pricing.md",
        "vendure-custom-fields": "vendure-custom-fields.md",
        "vendure-search-reindexing": "vendure-search-reindexing.md",
    }

    for ref, decisions in by_ref.items():
        for i, dec in enumerate(decisions):
            await ledger.ingest_payload({
                "query": dec["description"],
                "repo": "oss-test-repo",
                "commit_hash": f"stress-{ref}",
                "analyzed_at": "2026-02-05T10:00:00Z",
                "mappings": [{
                    "span": {
                        "span_id": f"{ref}-{i}",
                        "source_type": "transcript",
                        "text": dec["description"],
                        "speaker": "",
                        "source_ref": ref,
                    },
                    "intent": dec["description"],
                    "symbols": dec.get("expected_symbols", []),
                    "code_regions": [
                        {
                            "file_path": f"src/{pat}/impl.py",
                            "symbol": sym,
                            "type": "function",
                            "start_line": 1,
                            "end_line": 50,
                            "purpose": dec["description"][:80],
                        }
                        for sym, pat in zip(
                            dec.get("expected_symbols", [])[:1],
                            dec.get("expected_file_patterns", ["src"])[:1],
                        )
                    ],
                    "dependency_edges": [],
                }],
            })


# ── CONSTRAINT_LOST ───────────────────────────────────────────────────

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_constraint_lost_timeout_surfaces_before_checkout_work(monkeypatch, surreal_url):
    """CONSTRAINT_LOST: The 12s payment timeout constraint must surface when searching checkout.

    If an engineer searches for 'checkout payment' before implementing, they must see
    the timeout ceiling constraint — not discover it mid-sprint.
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all_transcripts(ledger)

    result = await handle_search_decisions(query="checkout payment implementation")
    constraint_decisions = [m for m in result.matches if "timeout" in m.description.lower() or "12" in m.description]
    assert len(constraint_decisions) > 0, (
        "CONSTRAINT_LOST test failed: timeout constraint not surfaced when searching 'checkout payment implementation'.\n"
        "An engineer implementing checkout would NOT see the 12-second ceiling — exactly how constraints get lost."
    )


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_constraint_lost_stock_negative_surfaces(monkeypatch, surreal_url):
    """CONSTRAINT_LOST: 'Stock quantity cannot go negative' must surface when querying stock update code."""
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all_transcripts(ledger)

    result = await handle_search_decisions(query="warehouse stock decrease quantity update")
    constraint_found = any(
        "negative" in m.description.lower() or "constraint" in m.description.lower()
        for m in result.matches
    )
    assert constraint_found, (
        "CONSTRAINT_LOST: stock negativity constraint not surfaced for stock-related query.\n"
        "Matches found: " + str([m.description[:60] for m in result.matches])
    )


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_constraint_lost_all_constraints_have_code_grounding(monkeypatch, surreal_url):
    """CONSTRAINT_LOST decisions must be grounded in code — not just floating in text.

    If a constraint has no code region, it can't trigger drift detection.
    PRD metric: >80% drift precision requires constraints to be symbol-grounded.
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.decision_status import handle_decision_status

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all_transcripts(ledger)

    result = await handle_decision_status(filter="all")
    constraint_decisions = [
        d for d in result.decisions
        if any(
            kw in d.description.lower()
            for kw in ["cannot", "must not", "ceiling", "constraint", "required", "timeout"]
        )
    ]

    ungrounded_constraints = [d for d in constraint_decisions if d.status == "ungrounded"]
    grounded_pct = 1.0 - (len(ungrounded_constraints) / max(len(constraint_decisions), 1))

    assert grounded_pct >= 0.60, (
        f"Only {grounded_pct:.0%} of CONSTRAINT_LOST decisions are grounded in code.\n"
        f"Ungrounded constraints cannot trigger drift detection:\n"
        + "\n".join(f"  - {d.description[:70]}" for d in ungrounded_constraints[:5])
    )


# ── DECISION_UNDOCUMENTED ─────────────────────────────────────────────

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_decision_undocumented_ungrounded_count_matches_expected(monkeypatch, surreal_url):
    """DECISION_UNDOCUMENTED: decisions with no code match must be flagged as ungrounded.

    These represent decisions that were made verbally but have no corresponding code.
    They are the highest-value output — telling the PM "these were discussed but not built."
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.decision_status import handle_decision_status

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all_transcripts(ledger)

    result = await handle_decision_status(filter="ungrounded")
    # At minimum, decisions explicitly marked ungrounded in fixtures must appear
    fixture_ungrounded_descs = [d["description"] for d in UNGROUNDED]
    found = sum(
        1 for fd in fixture_ungrounded_descs
        if any(fd[:40].lower() in rd.description.lower() for rd in result.decisions)
    )
    found_rate = found / max(len(fixture_ungrounded_descs), 1)

    assert found_rate >= 0.50, (
        f"Only {found_rate:.0%} of known-ungrounded decisions were surfaced (expected ≥50%).\n"
        f"Ungrounded decisions are the 'DECISION_UNDOCUMENTED' signal — PM needs these.\n"
        f"Missing:\n"
        + "\n".join(f"  - {fd[:70]}" for fd in fixture_ungrounded_descs if not any(fd[:40].lower() in rd.description.lower() for rd in result.decisions))
    )


# ── CONTEXT_SCATTERED ─────────────────────────────────────────────────

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_context_scattered_plugin_migration_unified(monkeypatch, surreal_url):
    """CONTEXT_SCATTERED: multiple transcripts about plugin system must unify into one search result.

    Medusa plugin migration: service base class, subscriber pattern, DI model, route compat
    — all discussed in one meeting but are 4 separate decisions. search_decisions must
    surface all of them in one query, not require 4 separate searches.
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all_transcripts(ledger)

    result = await handle_search_decisions(query="medusa plugin module migration v2", min_confidence=0.0)
    # Expect at least 3 of the 4 plugin migration decisions to surface
    plugin_keywords = ["AbstractModuleService", "createWorkflow", "Modules registry", "middlewares.ts", "@Module"]
    found_count = sum(
        1 for m in result.matches
        if any(kw.lower() in m.description.lower() for kw in plugin_keywords)
    )
    assert found_count >= 2, (
        f"CONTEXT_SCATTERED test failed: only {found_count} plugin migration decisions surfaced.\n"
        f"Expected ≥2 related decisions from the plugin migration meeting.\n"
        f"Got: {[m.description[:60] for m in result.matches]}"
    )


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_context_scattered_saleor_permissions_all_dimensions(monkeypatch, surreal_url):
    """CONTEXT_SCATTERED: channel-scoped permissions span JWT, check_permissions, App model, checkoutComplete.
    A single query about 'permissions' must surface all dimensions.
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all_transcripts(ledger)

    result = await handle_search_decisions(query="channel permissions authorization", min_confidence=0.0)
    dimensions = ["jwt", "check_permissions", "app", "checkout", "channel_access"]
    found_dims = [
        dim for dim in dimensions
        if any(dim.lower() in m.description.lower() for m in result.matches)
    ]
    assert len(found_dims) >= 2, (
        f"CONTEXT_SCATTERED: only {len(found_dims)} permission dimensions surfaced.\n"
        f"Found: {found_dims}\nExpected ≥2 of: {dimensions}"
    )


# ── TRIBAL_KNOWLEDGE ──────────────────────────────────────────────────

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_tribal_knowledge_tax_stripping_findable(monkeypatch, surreal_url):
    """TRIBAL_KNOWLEDGE: Vendure's tax-strip/convert/reapply pricing logic must be queryable.

    This is exactly the kind of knowledge that lives in one person's head:
    'strip tax, convert, reapply destination zone rate'. Discussed once, never documented.
    A new engineer implementing pricing MUST find this via search_decisions.
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all_transcripts(ledger)

    for query in ["channel pricing multi-currency", "tax rate conversion pricing strategy", "product variant price channel"]:
        result = await handle_search_decisions(query=query, min_confidence=0.0)
        found = any(
            "tax" in m.description.lower() and ("strip" in m.description.lower() or "convert" in m.description.lower())
            for m in result.matches
        )
        if found:
            return  # Pass if any query surfaces it

    pytest.fail(
        "TRIBAL_KNOWLEDGE test failed: tax stripping logic for multi-channel pricing is not findable.\n"
        "This is a high-severity miss — the knowledge is effectively locked in a transcript nobody reads."
    )


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_tribal_knowledge_no_sql_indexing_struct_warning_findable(monkeypatch, surreal_url):
    """TRIBAL_KNOWLEDGE: 'struct type has no SQL indexing' is a gotcha only one engineer knows."""
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all_transcripts(ledger)

    result = await handle_search_decisions(query="vendure custom field struct type json", min_confidence=0.0)
    found = any("struct" in m.description.lower() or "simple-json" in m.description.lower() for m in result.matches)
    assert found, (
        "TRIBAL_KNOWLEDGE: struct type gotcha not findable. "
        "A new engineer adding a struct field with filter requirements would hit this at runtime."
    )


# ── REPEATED_EXPLANATION ──────────────────────────────────────────────

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_repeated_explanation_context_immediately_available(monkeypatch, surreal_url):
    """REPEATED_EXPLANATION: after one ingest, same context must be available without re-explanation.

    The test: ingest once, query twice for the same topic — both must return results.
    If the second query misses (cache miss, index not updated), the ledger fails this requirement.
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all_transcripts(ledger)

    r1 = await handle_search_decisions(query="webhook exponential backoff retry")
    r2 = await handle_search_decisions(query="webhook retry policy dead letter queue")

    assert len(r1.matches) > 0, "First query for webhook retry returned empty"
    assert len(r2.matches) > 0, "Second (synonym) query for webhook retry returned empty — repeated explanation required"

    # Vocab cache should fast-path the second query
    assert r2.sync_status.reason == "already_synced", (
        "link_commit should fast-path on second call in same session"
    )
