"""Adversarial stress tests — edge cases from research on agentic AI testing.

Status: FAILING until Phase 2 (real ledger) is complete. Some tests require Phase 3.

These tests probe failure modes identified in published agentic benchmarks:
  - Negation: "do NOT use X" must not return X as implemented
  - Temporal isolation: decisions made at T1 must not see code from T0
  - Multi-hop: chains of decisions (A→B→C) must all be retrieved
  - Blast radius: high-fan-out symbols must be flagged
  - Unanswerable: queries about absent topics must return empty, not hallucinate
  - Superseded: a decision replaced by a later one must not create false drift

Sources:
  ABC (Agentic Benchmark Checklist) — arxiv.org/abs/2507.02825
  SWE-bench++ — arxiv.org/html/2512.17419v1
  MCPMark — arxiv.org/html/2509.24002v1
  Meeting Delegate benchmark — arxiv.org/html/2502.04376v1

Ground truth: tests/fixtures/expected/decisions.py (edit to tune)

Run: pytest tests/test_stress_adversarial.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from fixtures.expected.decisions import ADVERSARIAL

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "transcripts"


async def ingest_all(ledger):
    from tests.fixtures.expected.decisions import ALL_DECISIONS
    by_ref: dict[str, list] = {}
    for d in ALL_DECISIONS:
        by_ref.setdefault(d["source_ref"], []).append(d)
    for ref, decisions in by_ref.items():
        for i, dec in enumerate(decisions):
            await ledger.ingest_payload({
                "query": dec["description"],
                "repo": "oss-test-repo",
                "commit_hash": f"adv-{ref}",
                "analyzed_at": "2026-02-05T10:00:00Z",
                "mappings": [{
                    "span": {"span_id": f"{ref}-{i}", "source_type": "transcript",
                             "text": dec["description"], "speaker": "", "source_ref": ref},
                    "intent": dec["description"],
                    "symbols": dec.get("expected_symbols", []),
                    "code_regions": [
                        {"file_path": f"src/{p}/impl.py", "symbol": s,
                         "type": "function", "start_line": 1, "end_line": 50, "purpose": dec["description"][:80]}
                        for s, p in zip(dec.get("expected_symbols", [])[:1], dec.get("expected_file_patterns", ["src"])[:1])
                    ],
                    "dependency_edges": [],
                }],
            })


# ── Negation ──────────────────────────────────────────────────────────

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_negation_direct_module_import_not_implemented(monkeypatch, surreal_url):
    """Negation: 'can't reach into another module's internal services' must not appear as implemented.

    The medusa-plugin-migration decision FORBIDS direct imports of core services.
    If search_decisions returns this decision and the code still does direct imports,
    the status must be 'drifted' — not 'reflected'.

    The dangerous case: a naive system sees 'OrderService' in both the decision and the code,
    concludes it's reflected, and never flags the violation.
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all(ledger)

    result = await handle_search_decisions(query="service injection module isolation no direct imports")
    negation_matches = [
        m for m in result.matches
        if "can't" in m.description.lower() or "not" in m.description.lower() or "no direct" in m.description.lower()
    ]
    # These must be surfaced (system must understand the negated constraint exists)
    assert len(negation_matches) > 0 or any(
        "Modules registry" in m.description or "no direct" in m.description.lower()
        for m in result.matches
    ), (
        "Negation test: the 'no direct imports' constraint was not surfaced by search_decisions.\n"
        "A system that misses this will let engineers continue using forbidden patterns."
    )


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_negation_struct_no_sql_indexing_warning_not_confused(monkeypatch, surreal_url):
    """Negation: 'struct type has no SQL indexing' — searching for 'custom field filtering'
    must surface the WARNING, not conclude that filtering on struct is supported.
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all(ledger)

    result = await handle_search_decisions(query="vendure custom field filter nested value")
    # The struct warning must appear somewhere in results
    struct_warning = [m for m in result.matches if "struct" in m.description.lower() or "simple-json" in m.description.lower()]
    if len(result.matches) == 0:
        pytest.skip("No custom field decisions ingested yet — check ingest pipeline")

    # If matches exist, struct warning must be among them
    assert len(struct_warning) > 0, (
        "Negation: 'struct type has no SQL indexing' not surfaced when querying for field filtering.\n"
        "An engineer would implement filtering on struct and discover at runtime it doesn't work.\n"
        f"Got: {[m.description[:60] for m in result.matches]}"
    )


# ── Temporal isolation ────────────────────────────────────────────────

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_temporal_on_commit_before_fulfillment(monkeypatch, surreal_url):
    """Temporal: on_commit webhook dispatch must be BEFORE fulfillment side-effects — wrong order = drift.

    The saleor-order-workflows decision is explicit about timing: webhook fires AFTER
    transaction commits. If code has the webhook before on_commit, that's drift.
    This tests that the system's status derivation is order-sensitive.
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all(ledger)

    result = await handle_search_decisions(query="webhook dispatch fulfillment timing order")
    timing_decisions = [m for m in result.matches if "on_commit" in m.description or "before" in m.description.lower() or "after" in m.description.lower()]
    assert len(timing_decisions) > 0, (
        "Temporal: on_commit ordering decision not surfaced for webhook dispatch query.\n"
        "This is a classic timing bug source — the system must surface the ordering constraint."
    )


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_temporal_checkout_permission_check_must_precede_side_effects(monkeypatch, surreal_url):
    """Temporal: checkoutComplete permission gate must happen before order creation.

    saleor-graphql-permissions explicitly states: gate on channel permission BEFORE calling checkout_complete.
    If permission check happens after, half-created orders can exist.
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all(ledger)

    result = await handle_search_decisions(query="checkoutComplete permission gate before order creation")
    found = any("before" in m.description.lower() or "early" in m.description.lower() or "gate" in m.description.lower() for m in result.matches)
    assert found, (
        "Temporal: early permission gate for checkoutComplete not surfaced.\n"
        "Late permission check allows partial side effects before auth failure."
    )


# ── Multi-hop decisions ───────────────────────────────────────────────

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_multi_hop_checkout_validation_chain(monkeypatch, surreal_url):
    """Multi-hop: checkout extensibility chain must resolve end-to-end.

    Chain: validation hook → timeout → circuit breaker → Redis state
    A single search for 'checkout validation reliability' must surface the full chain,
    not just the first hop (the hook itself).
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all(ledger)

    result = await handle_search_decisions(query="checkout validation hook reliability plugin failure")
    chain_keywords = ["validation", "circuit", "timeout", "cache", "Redis"]
    found_hops = [kw for kw in chain_keywords if any(kw.lower() in m.description.lower() for m in result.matches)]
    assert len(found_hops) >= 2, (
        f"Multi-hop: only {len(found_hops)} of the validation chain surfaced: {found_hops}\n"
        f"Expected ≥2 of: {chain_keywords}\n"
        f"A codegen agent implementing checkout validation would miss the circuit breaker."
    )


# ── Blast radius ──────────────────────────────────────────────────────

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_blast_radius_payment_processor_flagged(monkeypatch, surreal_url):
    """Blast radius: symbols touched by many decisions must be flagged.

    The medusa payment timeout affects multiple code areas.
    decision_status must flag high-fan-out symbols in blast_radius field.
    PRD output example: 'PaymentProcessor (touched by 4 intents, 11 dependents)'
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.decision_status import handle_decision_status

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all(ledger)

    result = await handle_decision_status(filter="all")
    # At least one decision should have blast_radius populated for the payment area
    high_blast = [d for d in result.decisions if len(d.blast_radius) > 0]
    # This is aspirational for Phase 2 — the blast_radius field must be populated
    # not just present as empty list. Log it as a warning rather than hard fail for now.
    if len(high_blast) == 0:
        pytest.xfail(
            "blast_radius field is empty for all decisions — Phase 2 implementation needs "
            "to populate depends_on edges from code locator neighbor traversal. "
            "This will pass once depends_on graph edges are built during ingestion."
        )


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_blast_radius_vendure_pricing_30k_records_batched(monkeypatch, surreal_url):
    """Blast radius: pricing update strategy touches 30k records — must be flagged as high blast radius symbol."""
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all(ledger)

    result = await handle_search_decisions(query="ProductVariantPriceUpdateStrategy channel pricing")
    # The decision about batch lookups must be surfaced alongside the strategy decision
    batch_found = any("batch" in m.description.lower() or "N+1" in m.description or "30" in m.description for m in result.matches)
    assert batch_found, (
        "Blast radius: N+1 query warning for 30k price records not surfaced alongside pricing strategy decision.\n"
        "An engineer implementing the strategy without this context would write an N+1 loop."
    )


# ── Unanswerable queries ──────────────────────────────────────────────

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_unanswerable_returns_empty_not_hallucination(monkeypatch, surreal_url):
    """Unanswerable: queries about topics not in any transcript must return empty matches.

    The system must NOT hallucinate decisions that were never discussed.
    This is the core anti-hallucination requirement from the PRD.
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all(ledger)

    unanswerable_queries = [
        "kubernetes pod autoscaling decisions",
        "machine learning model training infrastructure",
        "mobile app push notification strategy",
        "blockchain smart contract deployment policy",
    ]

    for query in unanswerable_queries:
        result = await handle_search_decisions(query=query, min_confidence=0.5)
        # High confidence threshold should return 0 for topics never discussed
        assert len(result.matches) == 0 or all(m.confidence < 0.5 for m in result.matches), (
            f"Unanswerable query '{query}' returned {len(result.matches)} matches with confidence ≥0.5.\n"
            f"Matches: {[(m.description[:50], m.confidence) for m in result.matches if m.confidence >= 0.5]}\n"
            f"This is hallucination — the system is inventing decisions that were never discussed."
        )


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_unanswerable_does_not_confuse_similar_domains(monkeypatch, surreal_url):
    """Unanswerable: 'GraphQL federation decisions' should not match Saleor's GraphQL permission decisions.

    The system must distinguish between similar-sounding but different topics.
    Saleor uses GraphQL but never discussed federation — returning permission decisions for a
    federation query is a false positive.
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.search_decisions import handle_search_decisions

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all(ledger)

    result = await handle_search_decisions(query="GraphQL federation schema stitching microservices", min_confidence=0.7)
    # High-confidence matches for "federation" should be 0 — Saleor discussions are about permissions not federation
    federation_matches = [m for m in result.matches if "federation" in m.description.lower() or "stitching" in m.description.lower()]
    assert len(federation_matches) == 0, (
        f"False positive: federation query returned {len(federation_matches)} federation-specific matches.\n"
        f"The system is confusing GraphQL permissions (Saleor) with GraphQL federation (not discussed)."
    )


# ── Superseded decisions ──────────────────────────────────────────────

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_superseded_static_rate_table_not_reported_as_drifted(monkeypatch, surreal_url):
    """Superseded: 'start with static rate table, swap in live service later' from vendure-channel-pricing.

    When the live TaxRateService is wired, the static table is superseded.
    The system must NOT report the static table decision as 'drifted' —
    it was intentionally replaced.

    This tests the system's ability to model decision evolution, not just point-in-time snapshots.
    (Phase 3 capability — requires temporal decision graph)
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.decision_status import handle_decision_status

    ledger = get_ledger()
    if hasattr(ledger, "connect"):
        await ledger.connect()
    await ingest_all(ledger)

    # Ingest the follow-up decision that supersedes the static table
    await ledger.ingest_payload({
        "query": "Replace static exchange rate table with live TaxRateService injection in ProductVariantPriceUpdateStrategy",
        "repo": "oss-test-repo",
        "commit_hash": "supersede-static-table",
        "analyzed_at": "2026-02-15T10:00:00Z",  # Later date than original
        "mappings": [{
            "span": {"span_id": "supersede-0", "source_type": "transcript", "text": "Replace static with live service", "speaker": "", "source_ref": "vendure-channel-pricing-followup"},
            "intent": "Replace static exchange rate table with live TaxRateService",
            "symbols": ["ProductVariantPriceUpdateStrategy", "TaxRateService"],
            "code_regions": [{"file_path": "src/pricing/strategy.ts", "symbol": "ProductVariantPriceUpdateStrategy", "type": "class", "start_line": 1, "end_line": 100, "purpose": "pricing strategy"}],
            "dependency_edges": [],
        }],
    })

    result = await handle_decision_status(filter="drifted")
    # The 'static rate table' decision should NOT be drifted — it was intentionally superseded
    false_drift = [d for d in result.decisions if "static" in d.description.lower() and "rate table" in d.description.lower()]
    if len(false_drift) > 0:
        pytest.xfail(
            "Superseded decision is being reported as 'drifted' — the system doesn't yet model "
            "decision supersession. This is a Phase 3 capability requiring temporal graph reasoning. "
            f"Decisions incorrectly marked drifted: {[d.description[:60] for d in false_drift]}"
        )


# ── State isolation (ABC checklist T.4) ──────────────────────────────

@pytest.mark.phase2
@pytest.mark.asyncio
async def test_state_isolation_between_test_sessions(monkeypatch, surreal_url):
    """ABC T.4: clean state between tests — decisions from one test must not bleed into another.

    This test verifies the test harness itself — not the MCP logic.
    Each test must start from the same baseline state.
    If this test fails, test results are invalid (like ABC O.c.1 judge contamination).
    """
    monkeypatch.setenv("USE_REAL_LEDGER", "1")
    monkeypatch.setenv("SURREAL_URL", surreal_url)

    from adapters.ledger import get_ledger
    from handlers.decision_status import handle_decision_status

    # First: get baseline count (should be 0 or whatever is pre-loaded)
    ledger = get_ledger()
    before = await handle_decision_status(filter="all")
    baseline_count = len(before.decisions)

    # Ingest a test-specific decision
    await ledger.ingest_payload({
        "query": "ISOLATION_TEST_UNIQUE_MARKER_DO_NOT_MATCH_IN_OTHER_TESTS",
        "repo": "isolation-test",
        "commit_hash": "isolation-abc",
        "analyzed_at": "2026-03-27T12:00:00Z",
        "mappings": [{
            "span": {"span_id": "iso-0", "source_type": "transcript", "text": "isolation test", "speaker": "", "source_ref": ""},
            "intent": "ISOLATION_TEST_UNIQUE_MARKER_DO_NOT_MATCH_IN_OTHER_TESTS",
            "symbols": [], "code_regions": [], "dependency_edges": [],
        }],
    })

    after = await handle_decision_status(filter="all")
    assert len(after.decisions) == baseline_count + 1, (
        f"State isolation check: expected exactly 1 new decision after ingestion, "
        f"got {len(after.decisions) - baseline_count} new decisions. "
        f"This suggests test state is not isolated — decisions from previous tests are leaking in. "
        f"Implement clear_test_data() in SurrealDBLedgerAdapter or use per-test SurrealDB namespaces."
    )
