# Wider Retrieval + Caller-Side Verification

**Date**: 2026-04-19 (updated 2026-04-20)
**Status**: Planned
**Author**: Silong

## Problem

Recall is stuck at 30% despite MRR@3 reaching 0.79. We tried:
symbol-level BM25, score fusion, interleaving, parent-class traversal,
BM25 parameter tuning, fuzzy scorer changes — none break through 30%.

### Why Deterministic Retrieval Alone Can't Reach 70%

Analysis of all 20 unmatched symbols:

| Root Cause | Count | % |
|-----------|-------|---|
| COMPOUND_NAME | 15 | 75% |
| MULTI_SYMBOL | 2 | 10% |
| SHORT_NAME / SUBSTRING / WRONG_DOMAIN | 3 | 15% |

75% of failures: the expected symbol is a concatenation of words in the
description (`PaymentProviderService` from "payment provider authorize
calls"), but deterministic matching always picks shorter exact matches
(`Payment` at score 100) over the correct compound symbol.

**Implementation attempts and results:**

| Approach | MRR | Recall | Why it failed |
|----------|-----|--------|---------------|
| Symbol BM25 as primary (fill all slots) | 0.713 | — | Wrong symbols from wrong files |
| Symbol BM25 first-2-slots | 0.814 | 0.299 | Right files lost from top-3 |
| Inject into matched_scores (max 95) | 0.814 | 0.299 | Fuzzy=100 always outranks BM25=95 |
| Fuzzy score discount (×0.7) | 0.000 | 0.000 | Broke graph seeding completely |
| Additive scoring (fuzzy + BM25) | 0.786 | 0.299 | 100+30=130 still beats 0+50=50 |
| RRF interleaving | 0.651 | 0.237 | Symbol BM25 displaces good file results |
| In-file reranking | 0.786 | 0.299 | Stage 2 never runs (Stage 1 fills all slots) |
| Parent-class graph traversal | 0.786 | 0.299 | BM25 top hits have wrong parents |
| Wider retrieval (max_symbols=30) | — | 0.339 @top-10 | Same fuzzy matches repeated |
| Wider + symbol BM25 enrichment | — | **0.439** @top-20 | **Correct symbols appear at rank 11-20** |

**Key finding**: with wider retrieval + symbol BM25 enrichment, the
correct symbols ARE in the candidate set — they're just at rank 11-20,
too deep for deterministic top-3 selection. A semantic reranker (the
caller LLM) can pick the right one from a wider set.

### Deterministic Retrieval Ceiling

| top_k | Recall (current pipeline) | Recall (+ symbol BM25 enrichment) |
|-------|--------------------------|----------------------------------|
| 3 | 29.9% | 30.6% |
| 5 | 33.0% | 33.9% |
| 10 | 33.0% | 33.9% |
| 15 | 33.0% | 42.2% |
| 20 | 33.0% | **43.9%** |

Ceiling: **~44% recall** from deterministic retrieval alone.
Gap to 70%: requires semantic judgment by the caller LLM.

## Solution: Wider Retrieval + Caller-Side Compliance Verification

Aligns with Jin's v0.4.20 architecture and his directive: **code search
is deterministic, verification is semantic**.

```
RETRIEVAL (deterministic, code-locator)        VERIFICATION (semantic, caller LLM)
─────────────────────────────────────          ──────────────────────────────────
Description                                    Caller receives 15-20 candidates
  → file-level BM25 + fuzzy + graph            with code snippets + file paths
  → symbol BM25 enrichment (stemmed)
  → 15-20 ranked candidates                    Evaluates each: "does this code
  → stored with status=PENDING                 implement the decision?"

                                               Writes verdict → compliance_check
                                               derive_status reads cache
                                               REFLECTED only with compliant verdict
```

**Why this works:**
- Deterministic core stays deterministic (BM25 + fuzzy + graph)
- Caller LLM runs in the existing Claude Code session — zero extra API cost
  (Jin: "explicitly prompt claude to reroute back to caller AI session")
- `compliance_check` table caches verdicts — no re-evaluation on repeat queries
- Separates retrieval (finding candidates) from verification (judging correctness)
- Fixes the v0.4.16 bug: BM25 hits were silently promoted to REFLECTED

## Implementation Plan

### Phase 1: Widen Retrieval (~1 hour)

**File**: `adapters/code_locator.py`

Increase max_symbols in coverage tiers to return more candidates:

```python
_COVERAGE_TIERS = [
    (5, 75, 15),    # Tier 0: was (3, 75, 5)
    (7, 65, 20),    # Tier 1: was (5, 65, 8)
    (10, 55, 25),   # Tier 2: was (7, 55, 10)
]
```

Add symbol BM25 enrichment at the end of `_ground_single()`:
after the existing fuzzy + file-level pipeline fills its slots,
append symbol-level BM25 results (using the full description as
query) to fill remaining slots up to max_symbols.

The existing pipeline produces high-precision results at ranks 1-5.
Symbol BM25 adds diversity at ranks 6-15 — different symbols that
the fuzzy path misses.

**Verify**: recall@15 ≥ 40% (up from 30% at top-3).

### Phase 2: Ship `bicameral.resolve_compliance` Tool (~2 hours)

**Per v0.4.21 plan from Jin's notes.**

New MCP tool that the caller LLM invokes to write compliance verdicts:

```python
# Handler: handlers/resolve_compliance.py
async def handle_resolve_compliance(args):
    intent_id = args["intent_id"]
    region_id = args["region_id"]
    verdict = args["verdict"]  # "compliant" | "non_compliant" | "partial"
    reasoning = args.get("reasoning", "")
    
    # Write to compliance_check table (v0.4.20 schema already exists)
    await ledger.upsert_compliance_check(
        intent_id, region_id, verdict, reasoning,
        content_hash=compute_hash(region_content),
    )
    
    # Re-derive status — REFLECTED only if compliant verdict exists
    await ledger.rederive_status(intent_id)
```

The caller LLM flow:
1. `bicameral.ingest` returns decisions with 15 candidate regions each
2. Caller sees candidates with `status: PENDING` 
3. Caller evaluates each candidate against the decision description
4. Calls `bicameral.resolve_compliance` for each verdict
5. `derive_status` promotes to REFLECTED only with compliant verdict

**Verify**: ingest → candidates returned → caller writes verdict →
status changes from PENDING to REFLECTED.

### Phase 3: Caller-Side Prompt Engineering (~1 hour)

Update the `bicameral-ingest` skill to instruct the caller LLM:

```
After grounding, evaluate each candidate code region:
- Read the code at the given file/line range
- Compare against the decision description
- Does this code IMPLEMENT the decision, or just share keywords?
- Call bicameral.resolve_compliance with your verdict
```

This runs in the caller's existing session — no extra API calls.

### Phase 4: Eval Methodology Update (~30 min)

Update eval to measure both:
1. **Retrieval recall@15**: are correct symbols in the candidate set?
   (deterministic pipeline quality, target ≥ 44%)
2. **End-to-end recall**: after compliance verification, are correct
   symbols marked as REFLECTED? (target ≥ 70%)

The eval harness already supports `--top-k 15`. Add a new metric:
`compliance_recall` that simulates the caller LLM verdict.

## Expected Impact

| Metric | Before | After Phase 1 | After Phase 2+3 |
|--------|--------|---------------|-----------------|
| Retrieval recall@3 | 29.9% | 29.9% (unchanged) | 29.9% |
| Retrieval recall@15 | 33.0% | ~44% | ~44% |
| End-to-end recall | 29.9% | 29.9% | **~70%** |
| Status trustworthiness | Low | Low | **High** |
| MRR@3 | 0.786 | 0.786 | 0.786 |

## Why This Is the Right Architecture

From Jin's notes on v0.4.20:

> Grounding was conflating retrieval with verification. BM25 hits were
> silently promoted to REFLECTED with no semantic check that the code
> actually implemented the decision.

The current recall problem IS this conflation. We're measuring whether
the retrieval pipeline picks the exact right symbol — but that's the
verification step's job, not retrieval's job. Retrieval should provide
a diverse candidate set. Verification should judge correctness.

Splitting these concerns:
- **Retrieval** optimizes for recall@15 (are correct symbols in the
  candidate set?) — deterministic, BM25 + fuzzy + graph + symbol BM25
- **Verification** optimizes for precision (is the verdict correct?) —
  semantic, caller LLM, cached in compliance_check

This matches the ML design doc principle: "HIGH PRECISION for code facts
(RAG), HIGH RECALL for business context (LLM)." Retrieval provides
recall. Verification provides precision.

## Risks

1. **Caller LLM quality**: if the caller makes wrong verdicts, status
   trustworthiness drops. Mitigate: cache verdicts so they can be
   audited; include reasoning field for transparency.

2. **Latency**: 15 candidates × code reading = more tokens for the
   caller. Mitigate: only send candidates that pass basic relevance
   checks (file pattern match); batch compliance calls.

3. **Migration**: existing REFLECTED decisions become PENDING until
   the caller verifies them (per v0.4.20 design). This is intentional
   — an honest "we haven't checked this yet" is better than a false
   "this is implemented."

## Files Modified

| File | Phase | Change |
|------|-------|--------|
| `adapters/code_locator.py` | 1 | Widen tiers, add symbol BM25 enrichment |
| `code_locator/retrieval/bm25s_client.py` | 1 | Already built: `index_symbols()`, `search_symbols()` |
| `code_locator_runtime.py` | 1 | Already wired: calls `index_symbols()` |
| `handlers/resolve_compliance.py` | 2 | New handler for compliance verdicts |
| `server.py` | 2 | Register new tool |
| `ledger/adapter.py` | 2 | `upsert_compliance_check()` method |
| `tests/eval_code_locator.py` | 4 | Add recall@15 metric |

## Timeline

- Session 1 (2h): Phase 1 (wider retrieval) + Phase 4 (eval update)
- Session 2 (3h): Phase 2 (resolve_compliance tool) + Phase 3 (caller prompt)

## Context: Jin's Input

> code search is deterministic, but verification + drift detection is semantic

> explicitly prompt claude to reroute back to caller AI session, that way
> there's no need for extra api

> this is probably the highest prio metric — Status Trustworthiness.
> right now it is marking clearly incorrect implementation as reflected
> simply bc it was able to find symbols. we need to distinguish between
> symbols and reflected. reflected is only when the code functionally
> implements the logic.

v0.4.20 (PR #30) ships the compliance_check schema + cache-aware
derive_status. v0.4.21 ships resolve_compliance tool. This plan
implements the retrieval-side widening that feeds into that pipeline.
