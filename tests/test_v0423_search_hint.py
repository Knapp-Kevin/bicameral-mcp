"""v0.4.23 — ``search_hint`` recall booster regression tests.

Locks in the caller-LLM → server contract for the new ``search_hint``
field (Lever 2 of the BM25-vocab-mismatch fix). The hint lets the caller
supply synonyms / likely identifier names that the decision's natural-
language description wouldn't contain literally, so server-side BM25
fallback grounding has a fighting chance when the caller didn't resolve
explicit ``code_regions``.

Guards three surfaces:

1. **Propagation** — ``search_hint`` on a natural-format ``IngestDecision``
   survives ``_normalize_payload`` and lands on the resulting mapping.
2. **Query expansion** — ``ground_mappings`` (auto-ground) uses
   ``description + search_hint`` as the BM25 input when the field is set,
   and falls back to bare ``description`` when it's absent.
3. **Backward compatibility** — ingesting without ``search_hint`` produces
   identical behavior to pre-v0.4.23 (additive, no default change).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from handlers.ingest import _normalize_payload


# ── _normalize_payload propagation ───────────────────────────────────


def test_search_hint_propagates_from_natural_decision_to_mapping():
    """The natural-format ``IngestDecision.search_hint`` must end up on
    the resulting mapping so the server-side grounding path can read it.
    """
    out = _normalize_payload({
        "decisions": [
            {
                "description": "All email dispatchers filter via single source-of-truth check",
                "search_hint": "dispatchReminders dispatchInterventions resolveMemberStatus isActiveSubscriber",
            }
        ],
    })
    mappings = out.get("mappings", [])
    assert len(mappings) == 1
    assert mappings[0]["search_hint"].startswith("dispatchReminders"), (
        f"search_hint should survive normalization, got {mappings[0].get('search_hint')!r}"
    )


def test_search_hint_defaults_to_empty_when_omitted():
    """Omitting ``search_hint`` must produce the same mapping shape pre- and
    post-v0.4.23 (backward compat)."""
    out = _normalize_payload({
        "decisions": [{"description": "Cache user sessions in Redis"}],
    })
    mappings = out.get("mappings", [])
    assert len(mappings) == 1
    assert mappings[0].get("search_hint", "") == ""


def test_search_hint_never_pollutes_span_text():
    """``search_hint`` is query-only metadata. It must NOT leak into
    ``span.text`` — that field surfaces verbatim in briefs and status
    responses, so polluting it would show synonyms to human reviewers.
    """
    out = _normalize_payload({
        "decisions": [
            {
                "description": "Apply 10% discount on orders over $100",
                "search_hint": "calculateDiscount PricingService applyDiscount",
            }
        ],
    })
    mappings = out.get("mappings", [])
    assert len(mappings) == 1
    assert "calculateDiscount" not in mappings[0]["span"]["text"], (
        f"search_hint leaked into span.text: {mappings[0]['span']['text']!r}"
    )
    assert "calculateDiscount" not in mappings[0]["intent"], (
        f"search_hint leaked into intent: {mappings[0]['intent']!r}"
    )


def test_search_hint_passthrough_on_internal_format():
    """The internal format (pre-built ``mappings`` list) must pass
    ``search_hint`` through unchanged. The caller may set it even when
    providing explicit ``code_regions`` as a safety net for future
    re-grounding sweeps.
    """
    out = _normalize_payload({
        "mappings": [
            {
                "intent": "Use Stripe for checkout",
                "span": {"text": "...", "source_type": "transcript"},
                "symbols": ["StripeClient"],
                "code_regions": [],
                "search_hint": "StripeClient checkout payment_intent webhook",
            }
        ],
    })
    mappings = out.get("mappings", [])
    assert len(mappings) == 1
    assert mappings[0]["search_hint"].startswith("StripeClient")


# ── BM25 query construction in ground_mappings ───────────────────────


def _call_ground_mappings_with_stub(search_code_spy, mapping: dict) -> None:
    """Invoke ``ground_mappings`` with a stubbed search_code to capture
    the BM25 query string without needing a real code index.
    """
    from adapters.code_locator import RealCodeLocatorAdapter

    adapter = RealCodeLocatorAdapter.__new__(RealCodeLocatorAdapter)
    # Minimal attributes ground_mappings touches
    adapter._initialized = True
    adapter._db = MagicMock()
    # Stub the search tool so the FC-1 token count guard passes.
    adapter._search_tool = MagicMock()
    adapter._search_tool.bm25.count_corpus_tokens = MagicMock(return_value=10)
    adapter.search_code = search_code_spy
    # Stub coverage-loop tiers — set to zero matches so we exit without
    # touching the graph (the spy captures the query before that).
    adapter._COVERAGE_TIERS = [(5, 0.8, 3)]
    adapter._ground_single = MagicMock(return_value=[])

    adapter.ground_mappings([mapping])


def test_ground_mappings_concatenates_search_hint_into_bm25_query():
    """When ``search_hint`` is present, the BM25 query is
    ``description + " " + search_hint`` — wider recall on vocab-
    mismatched decisions.
    """
    captured: dict[str, str] = {}

    def spy(query: str) -> list:
        captured["query"] = query
        return []

    _call_ground_mappings_with_stub(spy, {
        "intent": "All email dispatchers filter via single source-of-truth check",
        "search_hint": "dispatchReminders dispatchInterventions resolveMemberStatus",
        "code_regions": [],
    })

    assert "All email dispatchers" in captured["query"]
    assert "dispatchReminders" in captured["query"]
    assert "resolveMemberStatus" in captured["query"]


def test_ground_mappings_uses_bare_description_when_no_hint():
    """No ``search_hint`` → BM25 query is the raw description (backward
    compatible with pre-v0.4.23)."""
    captured: dict[str, str] = {}

    def spy(query: str) -> list:
        captured["query"] = query
        return []

    _call_ground_mappings_with_stub(spy, {
        "intent": "Cache user sessions in Redis",
        "code_regions": [],
    })

    assert captured["query"] == "Cache user sessions in Redis"


def test_ground_mappings_ignores_empty_string_search_hint():
    """``search_hint = ""`` is equivalent to omitting the field —
    no query mutation."""
    captured: dict[str, str] = {}

    def spy(query: str) -> list:
        captured["query"] = query
        return []

    _call_ground_mappings_with_stub(spy, {
        "intent": "Apply 10% discount on orders over $100",
        "search_hint": "",
        "code_regions": [],
    })

    assert captured["query"] == "Apply 10% discount on orders over $100"


def test_ground_mappings_skips_grounding_when_code_regions_already_present():
    """If the caller already resolved ``code_regions`` (Lever 1 happy path),
    BM25 doesn't run at all — ``search_code`` is never called, so neither
    query composition nor the FC-1 guard matter.
    """
    spy = MagicMock()

    _call_ground_mappings_with_stub(spy, {
        "intent": "Use Stripe for checkout",
        "search_hint": "StripeClient checkout",
        "code_regions": [
            {"file_path": "src/checkout.ts", "symbol": "StripeClient",
             "start_line": 1, "end_line": 50, "type": "class"}
        ],
    })

    spy.assert_not_called()
