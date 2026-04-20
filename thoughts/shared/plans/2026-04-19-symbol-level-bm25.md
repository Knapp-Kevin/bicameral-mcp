# Symbol-Level BM25: Fixing the Retrieval Granularity Problem

**Date**: 2026-04-19
**Status**: Planned
**Author**: Silong

## Problem

Recall is stuck at 30% despite MRR@3 reaching 0.79. Analysis of all 20
unmatched symbols reveals **three compounding failures**, not one:

### Root Cause Analysis: 20 Unmatched Symbols

| Root Cause | Count | % | Example |
|-----------|-------|---|---------|
| COMPOUND_NAME | 15 | 75% | "payment provider" can't reconstitute `PaymentProviderService` |
| MULTI_SYMBOL | 2 | 10% | Found `decrease_stock` but missed `orderFulfill` |
| SHORT_NAME | 1 | 5% | `App` (3 chars) filtered by domain word minimum |
| SUBSTRING | 1 | 5% | `middlewares` found as `getMiddlewares` but not matched |
| WRONG_DOMAIN | 1 | 5% | Description says "webhook", expected symbol in "notification" |

**75% of failures are COMPOUND_NAME** — the symbol name is a concatenation
of words that appear separately in the description. Three problems
compound to make this unsolvable with the current architecture:

**Problem 1: File-level granularity drowns multi-term matches.**
`PaymentProviderService` decomposes to [payment, provider, service], but
in a 500-token file document these 3 tokens are noise. `Payment` (1 token)
matches just as well as `PaymentProviderService` (3 tokens) because both
appear in the same file document.

**Problem 2: No stemming breaks singular/plural matching.**
bm25s tokenizes without stemming. "plugin" (query) ≠ "plugins" (symbol
`PluginsManager`). "permission" ≠ "permissions" (`check_permissions`).
This blocks 5 of 15 compound name matches.

**Problem 3: Keyword blocklist strips needed query terms.**
`_KEYWORD_WORDS` contains `service`, `error`, `field`, `update`, `create`,
`event`, `model`, `type`. These are exactly the suffixes that distinguish
`CheckoutError` from `Checkout` and `PaymentProviderService` from
`Payment`. While the blocklist only affects fuzzy matching tokens (not
the BM25 query directly), it prevents the fuzzy path from finding these
symbols as graph seeds.

**Any ONE fix alone yields <40% recall. All THREE together → 70-80%.**

### Verification: Symbol-Level BM25 + Stemming Token Overlap

With both stemming and symbol-level indexing, query→symbol overlap:

| Symbol | Query Terms | Overlap | Match? |
|--------|------------|---------|--------|
| `PaymentProviderService` | payment, provider | 2/3 doc terms | YES |
| `check_permissions` | permission(→permissions) | 1/2 doc terms | YES w/ stemming |
| `PluginsManager` | plugin(→plugins) | 1/2 doc terms | YES w/ stemming |
| `CheckoutError` | checkout, error | 2/2 doc terms | YES |
| `DefaultSearchPlugin` | search, plugin | 2/3 doc terms | YES |
| `OrderService` | service | 1/2 doc terms | YES |
| `CustomFieldConfig` | custom, field | 2/3 doc terms | YES |
| `createOrUpdateProductVariantPrice` | price, update | 2/7 doc terms | YES |

Conservative estimate: 12/15 compound name misses fixed → +12 symbols
→ 30/38 = **79% symbol-level recall** (currently 47%).

## Codex Adversarial Review Findings (2026-04-19)

An adversarial review of the prior incremental PR flagged two issues
that this plan must address:

### Finding: `_KEYWORD_WORDS` blocklist strips semantically useful terms

The current keyword blocklist in `adapters/code_locator.py` contains
words like `error`, `service`, `event`, `model`, `field`, `type`,
`worker`, `query`, `struct`. These were added to prevent NL words from
fuzzy-matching short symbols (e.g. "void"→`Void`, "state"→`State`).

But they also block critical code suffixes:
- `error` → prevents "checkout error" from generating `CheckoutError` bigram
- `service` → prevents "payment provider service" from matching `PaymentProviderService`
- `event` → prevents "event bus" from generating `EventBus` bigram
- `field` → prevents "custom field" from generating `CustomField` bigram
- `worker` → prevents "search worker" from matching worker configs

**Impact on this plan**: Symbol-level BM25 sidesteps this problem
entirely — the keyword blocklist only affects the fuzzy-matching path,
which becomes a secondary channel. The primary symbol-level BM25 search
operates on the raw description text, so "checkout error" will directly
match the `CheckoutError` symbol document without any token filtering.

**Pre-implementation action**: Before Phase 1, audit `_KEYWORD_WORDS`
and remove terms that are semantically meaningful as code suffixes
(`error`, `service`, `event`, `model`, `field`, `type`, `worker`,
`query`). Keep only true NL noise words (`void`, `return`, `state`,
`currently`, `causes`, etc.). This improves the fallback fuzzy path
regardless of whether symbol-level BM25 is implemented.

### Finding: Benchmark integrity — eval/fixture changes may inflate metrics

The prior PR relaxed ground truth fixtures (removed phantom symbols,
broadened file patterns) and changed the eval metric (case-insensitive
matching, all-component extraction). While each change is individually
justifiable, together they risk masking whether the pipeline actually
improved.

**Action for this plan**: Phase 5 must include a **dual-benchmark
evaluation**:
1. Run eval on the ORIGINAL fixtures (pre-PR, commit `f06b5df`) to
   prove the symbol-level BM25 pipeline improves recall on the harder,
   unchanged benchmark
2. Run eval on the corrected fixtures to show the full picture
3. Report BOTH numbers in the commit message

This ensures we can claim real retrieval improvement, not just
measurement improvement.

## Solution: Three Fixes Applied Together

All three must land in the same change to reach 70%+ recall:

1. **Symbol-level BM25 index** — one doc per symbol, not per file
2. **Stemming in BM25 tokenization** — handles singular/plural mismatches
3. **Keyword blocklist cleanup** — unblocks semantically meaningful code terms

### Fix 1: Symbol-Level BM25 Index

Index one BM25 document per **symbol** instead of per file. The query
"payment provider authorize calls" directly matches the document for
`PaymentProviderService` because its document text contains
`PaymentProviderService payment provider service`.

### Current vs Proposed Architecture

```
CURRENT (file-level):
  description → tokens → fuzzy match → graph seeds
                                      ↓
                       BM25(files) → pick symbols from files → return
                       ~500 docs      130 lines of Stage 2 logic

PROPOSED (symbol-level):
  description → BM25(symbols) → return top-K symbols directly
                ~2500 docs      Stage 2 eliminated
                              ↓
                + graph channel fusion for multi-file coverage
```

### What Each Symbol Document Contains

```python
# One document per symbol in the SQLite index
doc = " ".join([
    expand_identifiers(symbol.name),           # "PaymentProviderService payment provider service"
    expand_identifiers(symbol.qualified_name),  # "modules.payment.PaymentProviderService ..."
    symbol.type,                                # "class"
    symbol.parent_qualified_name or "",         # "modules.payment"
    symbol.signature or "",                     # "export default class PaymentProviderService extends ..."
    symbol.file_path,                           # "packages/modules/payment/src/services/payment-provider.ts"
])
```

Each document is ~50-100 tokens (vs ~500 for file-level). Total index
size is similar: 2500 docs * 50 tokens ≈ 500 docs * 250 tokens.

### Why This Fixes Recall

| Failure | Current | With Symbol BM25 |
|---------|---------|-------------------|
| `PaymentProviderService` not found | BM25 finds file, Stage 2 picks `Payment` (shorter, higher fuzzy score) | BM25 directly ranks `PaymentProviderService` above `Payment` because more query terms match |
| `CheckoutError` not found | BM25 finds checkout file, picks `Checkout` variable | Symbol doc for `CheckoutError` contains "checkout error" — direct hit |
| `DefaultSearchPlugin` not found | BM25 finds search files, picks `reindex` functions | Symbol doc for `DefaultSearchPlugin` contains "default search plugin" — direct hit |
| `check_permissions` not found | BM25 finds channel files (wrong area) | Symbol doc for `check_permissions` contains "check permissions" — query matches directly |
| `createOrUpdateProductVariantPrice` not found | BM25 finds variant files, picks `price` variable | Symbol doc contains full function name — `expand_identifiers` splits it into matching terms |

## Implementation Plan

### Phase 1: Symbol-Level BM25 Index (~1.5 hours)

**File**: `code_locator/retrieval/bm25s_client.py`

Add a new method `index_symbols()` alongside existing `index()`:

```python
def index_symbols(self, output_dir: str, symbol_db, k1=1.5, b=0.75):
    """Build BM25 index at symbol granularity."""
    conn = symbol_db._connect()
    rows = conn.execute("""
        SELECT id, name, qualified_name, type, file_path,
               signature, parent_qualified_name
        FROM symbols
    """).fetchall()

    documents = []
    symbol_ids = []
    for row in rows:
        doc = " ".join(filter(None, [
            expand_identifiers(row["name"]),
            expand_identifiers(row["qualified_name"]),
            row["type"],
            expand_identifiers(row["parent_qualified_name"] or ""),
            row["signature"] or "",
            row["file_path"].replace("/", " ").replace(".", " "),
        ]))
        documents.append(doc)
        symbol_ids.append(row["id"])

    tokens = bm25s.tokenize(documents, stopwords="en")
    bm25 = bm25s.BM25(k1=k1, b=b)
    bm25.index(tokens)

    # Persist alongside file-level index
    index_path = Path(output_dir) / "bm25_symbol_index.pkl"
    with open(index_path, "wb") as f:
        pickle.dump({"bm25": bm25, "symbol_ids": symbol_ids}, f)
```

### Fix 2: Stemming in BM25 Tokenization

bm25s.tokenize accepts a `stemmer` parameter. Use Snowball stemmer
so "plugin"→"plugin" matches "plugins"→"plugin", and "permission"
matches "permissions":

```python
import Stemmer  # PyStemmer package
stemmer = Stemmer.Stemmer("english")

# Apply to BOTH index and query tokenization:
tokens = bm25s.tokenize(documents, stopwords="en", stemmer=stemmer)
```

This must be applied consistently to both `index_symbols()` and
`search_symbols()`. The existing file-level `index()` should also
get stemming for consistency.

**Dependency**: `pip install PyStemmer` (already a bm25s optional dep).

Add `search_symbols()`:

```python
def search_symbols(self, query: str, top_k: int = 20) -> list[dict]:
    """Search symbol-level BM25 index. Returns ranked symbol IDs."""
    stemmer = Stemmer.Stemmer("english")
    query_tokens = bm25s.tokenize(
        [expand_identifiers(query)], stopwords="en", stemmer=stemmer,
    )
    results, scores = self._symbol_bm25.retrieve(query_tokens, k=top_k)
    return [
        {"symbol_id": self._symbol_ids[idx], "score": float(score)}
        for idx, score in zip(results[0], scores[0])
        if score > 0
    ]
```

### Phase 2: Wire Into Grounding Pipeline (~1.5 hours)

**File**: `adapters/code_locator.py`

Replace the two-stage `_ground_single()` with symbol-level retrieval:

```python
def _ground_single(self, description, db, max_files, fuzzy_threshold,
                   max_symbols, hits=None, mapping_symbol_names=None):
    # Primary: symbol-level BM25
    sym_hits = self._search_tool.bm25.search_symbols(description, top_k=max_symbols * 3)

    # Resolve symbol IDs to regions
    code_regions = []
    seen_files = set()
    for hit in sym_hits[:max_symbols]:
        row = db.lookup_by_id(hit["symbol_id"])
        if row:
            code_regions.append({
                "symbol": row["qualified_name"] or row["name"],
                "file_path": row["file_path"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "type": row["type"],
                "purpose": description,
            })
            seen_files.add(row["file_path"])

    # Optional: fuse with graph channel for multi-file coverage
    if len(seen_files) < 2 and sym_hits:
        top_ids = [h["symbol_id"] for h in sym_hits[:3]]
        # Graph traversal from top symbols to find related symbols in other files
        ...

    return code_regions
```

This reduces `_ground_single` from ~130 lines to ~30 lines. The coverage
tier loop in `ground_mappings()` still works — it just calls the simpler
`_ground_single` at each tier.

### Phase 3: Dual-Index Fusion (~1 hour)

Keep file-level BM25 as a secondary channel. Fuse symbol-level and
file-level results via RRF:

```python
# In SearchCodeTool.execute():
channels = {
    "bm25_symbols": self.bm25.search_symbols(query, top_k=20),  # NEW
    "bm25_files": self.bm25.search(query, top_k=20),             # existing
    "graph": self._graph_retrieve(symbol_ids) if symbol_ids else [],
}
# RRF fusion with weights:
# symbols: 2.0 (primary), files: 0.5 (fallback), graph: 1.2 (structural)
```

The file-level channel acts as a safety net for symbols the symbol-level
index might miss (e.g., symbols mentioned only in file body, not in
their own name/signature).

### Phase 4: Index Lifecycle (~30 min)

**File**: `code_locator_runtime.py`

After `build_index()` and `bm25.index()`, also call `bm25.index_symbols()`:

```python
bm25 = Bm25sClient()
bm25.index(repo, index_dir, symbol_db=_sdb)       # file-level (existing)
bm25.index_symbols(index_dir, symbol_db=_sdb)      # symbol-level (new)
```

Lazy-load the symbol index in `Bm25sClient._load()`.

### Phase 0: Keyword Blocklist Audit (prerequisite, ~20 min)

**File**: `adapters/code_locator.py`

Before building symbol-level BM25, fix the `_KEYWORD_WORDS` blocklist
that suppresses semantically meaningful code terms. Remove: `error`,
`service`, `event`, `events`, `model`, `field`, `fields`, `type`,
`types`, `worker`, `query`, `queries`, `struct`, `create`, `update`,
`delete`. Keep: `void`, `return`, `returns`, `throw`, `throws`, `state`,
`status`, `call`, `calls`, `value`, `values`, `class`, `object`,
`function`, `method`, and all the NL-only words (`currently`, `causes`,
etc.).

Run eval BEFORE and AFTER this change to measure the isolated impact
on the fuzzy-matching path. This improvement helps even if symbol-level
BM25 is never shipped.

### Phase 5: Dual-Benchmark Eval + Tune (~1.5 hours)

**Dual-benchmark requirement** (from adversarial review):

1. Checkout the ORIGINAL fixtures at commit `f06b5df` (pre-PR baseline)
   into a temp file. Run eval against those fixtures with the new
   symbol-level pipeline. This proves retrieval improved on the harder
   benchmark.
2. Run eval against the current (corrected) fixtures. This shows the
   full picture.
3. Report BOTH sets of numbers in the commit message.

Additional steps:
- Tune RRF channel weights (symbol vs file vs graph)
- Verify MRR >= 0.75, target recall >= 45% on corrected fixtures
- Verify recall improves on original fixtures too (even if absolute
  number is lower due to phantom symbols)
- Run full test suite

## Expected Impact

| Metric | Before | After (projected) |
|--------|--------|-------------------|
| MRR@3 | 0.786 | ~0.85 (symbol-level more precise) |
| Recall | 29.9% | **~70%** (three fixes together) |
| FP Rate | 30-55% | ~15-25% (fewer irrelevant symbols) |
| `_ground_single` complexity | 130 lines, 2 stages | ~30 lines, 1 stage |

### Why 70% and not higher

- 6/30 decisions have empty `expected_symbols` → always recall=0
- 1 decision (`VendureConfig`) has 0 query term overlap — unfixable
- 1 decision (`AbstractNotificationProviderService`) has wrong domain
- 2 decisions need cross-symbol awareness (finding BOTH `decrease_stock`
  AND `orderFulfill` from one description)
- Theoretical ceiling with current ground truth: ~80%

### Why this time is different from incremental tuning

The prior changes (keyword blocklist, fuzzy scorer, BM25 params) each
addressed ONE of the three problems in isolation. None moved recall
because all three problems compound:

- Keyword blocklist fix alone: query has "service" but file-level BM25
  still drowns it → no gain
- Symbol-level BM25 alone: "permission" doesn't match "permissions"
  without stemming → partial gain
- Stemming alone: matches the right tokens but file-level BM25 still
  picks `Payment` over `PaymentProviderService` → no gain

All three applied together break the compounding failure mode.

## Risks

1. **Symbol documents may be too short for BM25**: Very short documents
   can cause BM25 scoring anomalies. Mitigate by ensuring minimum
   document length (repeat symbol name if doc < 10 tokens).

2. **Loss of file-level context**: Some decisions describe file-level
   concepts ("the payment module"). Mitigate by keeping file-level BM25
   as an RRF channel.

3. **Index rebuild required**: All repos need re-indexing. The symbol
   data is already in SQLite — no re-parsing needed, just BM25 rebuild.

4. **Test breakage**: `test_fc2_multi_region_grounding.py` mocks
   `search_code` — symbol-level search would need new mocks. Coverage
   loop tests mock `_ground_single` directly — they still work.

5. **Benchmark validity**: Prior PR changed both the pipeline AND the
   eval metric/fixtures. To avoid conflating measurement improvement
   with retrieval improvement, Phase 5 requires dual-benchmark eval
   (original + corrected fixtures). If recall only improves on the
   corrected fixtures, the gain is suspect.

## Files Modified

| File | Change |
|------|--------|
| `code_locator/retrieval/bm25s_client.py` | Add `index_symbols()`, `search_symbols()`, dual-index loading |
| `adapters/code_locator.py` | Simplify `_ground_single()` to use symbol-level results |
| `code_locator/tools/search_code.py` | Add symbol BM25 channel to RRF fusion |
| `code_locator_runtime.py` | Call `index_symbols()` during rebuild |
| `code_locator/config.py` | Add `symbol_bm25_enabled: bool = True` feature flag |
| `tests/test_fc2_multi_region_grounding.py` | Update mocks for new search path |

## Timeline

Total: ~6 hours across 2 sessions.

- Session 1 (3.5h): Phase 0 (keyword audit) + Phases 1-2 (symbol index + pipeline)
- Session 2 (2.5h): Phases 3-5 (dual-index fusion + dual-benchmark eval + tune)
