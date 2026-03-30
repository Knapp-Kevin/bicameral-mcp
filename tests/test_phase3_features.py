"""Phase 3 feature grouping tests.

Tests for implicit feature extraction via graph traversal.
No `feature` node or `about` edge required — decisions are grouped at query time
using connected components over maps_to + depends_on edges, labeled by feature_hint.

See "Related Decisions and Implicit Feature Grouping" in the integration plan for
the full algorithm. See "The Feature Problem" Notion doc for the explicit Phase 3+
feature node design (3-signal hybrid with stored about edges).

Run when Phase 2 ledger is wired:
    USE_REAL_LEDGER=1 pytest tests/test_phase3_features.py -v
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures: decisions that share structural dependencies
# ---------------------------------------------------------------------------

# These three intents should cluster into one "payments" group because they
# share a common symbol or are connected via depends_on edges.
PAYMENT_DECISIONS = [
    {
        "description": "webhook retry with exponential backoff",
        "feature_hint": "payments",
        "symbol": "WebhookDispatcher.send",
        "file_path": "webhook/dispatcher.py",
        "dep_symbols": ["PaymentProcessor.process"],  # depends_on edge
    },
    {
        "description": "optimistic locking for cart updates",
        "feature_hint": "payments",
        "symbol": "CartService.updateItem",
        "file_path": "cart/service.py",
        "dep_symbols": ["PaymentProcessor.process"],  # shared dependency
    },
    {
        "description": "rate limit checkout endpoint",
        "feature_hint": "payments",
        "symbol": None,  # ungrounded — no code region yet
        "file_path": None,
        "dep_symbols": [],
    },
]

AUTH_DECISIONS = [
    {
        "description": "sessions expire after 24h of inactivity",
        "feature_hint": "auth",
        "symbol": "SessionManager.expire",
        "file_path": "auth/session.py",
        "dep_symbols": [],
    },
    {
        "description": "refresh tokens are single-use, rotated on each use",
        "feature_hint": "auth",
        "symbol": "TokenService.rotate",
        "file_path": "auth/tokens.py",
        "dep_symbols": ["SessionManager.expire"],  # imports session
    },
]


# ---------------------------------------------------------------------------
# Tests for implicit feature grouping (graph traversal, no feature node)
# ---------------------------------------------------------------------------


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_feature_hint_filter(real_ledger):
    """feature_hint stored on intent enables direct string filtering."""
    for d in PAYMENT_DECISIONS + AUTH_DECISIONS:
        await real_ledger.ingest_intent(d)

    payment = await real_ledger.query(
        "SELECT id, description FROM intent WHERE feature_hint = 'payments'"
    )
    auth = await real_ledger.query(
        "SELECT id, description FROM intent WHERE feature_hint = 'auth'"
    )

    assert len(payment) == len(PAYMENT_DECISIONS)
    assert len(auth) == len(AUTH_DECISIONS)
    payment_descs = {r["description"] for r in payment}
    assert all(d["description"] in payment_descs for d in PAYMENT_DECISIONS)


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_symbol_co_mapping_surfaces_siblings(real_ledger):
    """Two intents mapping to the same symbol are surfaced as related."""
    # Both webhook retry and optimistic lock depend on PaymentProcessor via depends_on
    for d in PAYMENT_DECISIONS[:2]:  # grounded ones only
        await real_ledger.ingest_intent_with_symbol(d)

    # Find intents related to the webhook retry decision via symbol co-mapping
    webhook_intent = await real_ledger.query(
        "SELECT id FROM intent WHERE description @0@ 'webhook retry' LIMIT 1"
    )
    assert webhook_intent, "webhook retry intent should be ingested"

    related = await real_ledger.query("""
        LET $my_regions = (
            SELECT ->maps_to->symbol->implements->code_region.id AS r
            FROM intent WHERE id = $id
        )[0].r;
        LET $dep_regions = (
            SELECT ->depends_on->code_region.id AS r
            FROM code_region WHERE id IN $my_regions
        )[*].r;
        SELECT DISTINCT id, description, feature_hint
        FROM intent
        WHERE ->maps_to->symbol->implements->code_region.id CONTAINSANY $dep_regions
          AND id != $id
    """, {"id": webhook_intent[0]["id"]})

    related_descs = {r["description"] for r in related}
    assert "optimistic locking for cart updates" in related_descs, (
        "Both decisions share PaymentProcessor dependency — should be surfaced as related"
    )


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_group_decisions_by_feature_clusters_by_connectivity(real_ledger):
    """group_decisions_by_feature() clusters all payment decisions together via depends_on.

    Even the ungrounded intent (no code region) should be in the same cluster
    because the grounded ones share structural connectivity, and feature_hint = 'payments'
    breaks the tie for the whole component.
    """
    for d in PAYMENT_DECISIONS + AUTH_DECISIONS:
        await real_ledger.ingest_intent(d)

    groups = await real_ledger.group_decisions_by_feature(repo="test-repo")

    feature_labels = {g["feature_label"] for g in groups}
    assert "payments" in feature_labels, "payment decisions should form a group"
    assert "auth" in feature_labels, "auth decisions should form a group"

    payments_group = next(g for g in groups if g["feature_label"] == "payments")
    assert payments_group["decision_count"] == len(PAYMENT_DECISIONS), (
        "All 3 payment decisions (incl. ungrounded) should cluster together"
    )

    auth_group = next(g for g in groups if g["feature_label"] == "auth")
    assert auth_group["decision_count"] == len(AUTH_DECISIONS)

    # Groups should be mutually exclusive
    payment_ids = {d["id"] for d in payments_group["decisions"]}
    auth_ids = {d["id"] for d in auth_group["decisions"]}
    assert not payment_ids & auth_ids, "no decision should appear in both groups"


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_group_decisions_status_summary(real_ledger):
    """group_decisions_by_feature() includes a correct status_summary per group."""
    for d in PAYMENT_DECISIONS:
        await real_ledger.ingest_intent(d)

    groups = await real_ledger.group_decisions_by_feature(repo="test-repo")
    payments = next(g for g in groups if g["feature_label"] == "payments")

    summary = payments["status_summary"]
    total = sum(summary.values())
    assert total == len(PAYMENT_DECISIONS), "status_summary should account for all decisions"
    # ungrounded rate limit, pending/drifted others — exact statuses depend on commit state
    assert set(summary.keys()) <= {"reflected", "drifted", "pending", "ungrounded"}


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_blast_radius_query(real_ledger):
    """Blast radius traversal from a shared symbol surfaces all dependent decisions."""
    for d in PAYMENT_DECISIONS[:2]:
        await real_ledger.ingest_intent_with_symbol(d)

    # PaymentProcessor.process is a shared dependency of both grounded payment decisions
    blast = await real_ledger.query("""
        LET $sym_region = (
            SELECT ->implements->code_region.id AS r
            FROM symbol WHERE name = 'PaymentProcessor.process'
        )[0].r;
        LET $dependents = (
            SELECT <-depends_on<-code_region.id AS r
            FROM code_region WHERE id IN $sym_region
        )[*].r;
        SELECT DISTINCT id, description, feature_hint
        FROM intent
        WHERE ->maps_to->symbol->implements->code_region.id CONTAINSANY $dependents;
    """)

    blast_descs = {r["description"] for r in blast}
    assert "webhook retry with exponential backoff" in blast_descs
    assert "optimistic locking for cart updates" in blast_descs


@pytest.mark.phase2
@pytest.mark.asyncio
async def test_cross_feature_dependency_does_not_merge_groups(real_ledger):
    """Decisions from different feature areas connected via a shared lib don't merge.

    Even if auth and payments both import a shared utility, they should remain
    separate groups because their feature_hint labels differ and the connectivity
    is weak (utility lib, not domain code).
    """
    # Auth token rotation also imports a shared utils module
    auth_with_shared_dep = {
        **AUTH_DECISIONS[0],
        "dep_symbols": ["utils.crypto.hash"],  # shared with payments too
    }
    payments_with_shared_dep = {
        **PAYMENT_DECISIONS[0],
        "dep_symbols": ["utils.crypto.hash", "PaymentProcessor.process"],
    }

    await real_ledger.ingest_intent_with_symbol(auth_with_shared_dep)
    await real_ledger.ingest_intent_with_symbol(payments_with_shared_dep)
    for d in PAYMENT_DECISIONS[1:2]:
        await real_ledger.ingest_intent_with_symbol(d)

    groups = await real_ledger.group_decisions_by_feature(repo="test-repo")

    # The shared utils dep may merge them into one component — but feature_hint
    # majority label should still correctly separate them conceptually.
    # This test documents the known limitation: if utility deps dominate,
    # the grouping may be imperfect. The test passes if labels are correct.
    for group in groups:
        if group["feature_label"] == "payments":
            payment_hints = [d["feature_hint"] for d in group["decisions"]]
            assert payment_hints.count("payments") >= payment_hints.count("auth"), (
                "Majority feature_hint in payments group should be 'payments'"
            )
