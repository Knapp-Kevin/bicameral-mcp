---
name: bicameral-drift
description: DEPRECATED in v0.4.17 — prefer bicameral-scan-branch for multi-file drift audits. This skill remains available for single-file scope when the user explicitly names one file. Fires only on file-scoped phrasings ("is pricing.py drifted?", "check discount.py before I commit"). For "what's drifted on this branch" / "scan my PR" / any whole-branch check, route to bicameral-scan-branch.
---

# Bicameral Drift — single-file only (DEPRECATED v0.4.17)

> **⚠ DEPRECATED — prefer `bicameral-scan-branch` for the default "check drift" case.**
>
> This skill and its backing tool (`bicameral.drift`) still work for
> single-file scope, but the multi-file counterpart `bicameral.scan_branch`
> is the correct answer for virtually every real code-review flow.
> Fan-out loops of `bicameral.drift` across N files are now an
> anti-pattern — `bicameral.scan_branch` does the same work in one
> call, dedupes decisions across files, and gives the user a single
> report instead of N separate ones.
>
> **Removal planned for v0.4.18** alongside the `bicameral.doctor`
> composition tool.

## When to fire (single-file only)

Only when the user **explicitly names one file** and the scope is obviously single-file:

- *"is `src/pricing/discount.py` drifted?"*
- *"check `checkout.py` before I commit"*
- *"did the rate limiter drift?"* — only when the user clearly means one file they just named

If the user says any of:

- *"what's drifted on this branch"*
- *"scan my PR"*
- *"check for drift"* (no file named)
- *"is anything broken before I merge"*
- *"review the changes I made"*

→ **route to `bicameral.scan_branch`** instead. Don't fire this skill. Don't fan out N drift calls in parallel as a workaround — that's the exact pattern scan_branch was built to replace.

## When NOT to fire

- **Multi-file scope** — always use `bicameral.scan_branch`. See above.
- **Topic-scoped questions** — *"what was decided about rate limiting?"* — use `bicameral.search`.
- **Ledger-wide status** — *"show me every drifted decision"* — use `bicameral.status filter=drifted`.
- **Auto-firing on generic "drift" requests** — never reach for this tool when the user hasn't pinned a specific file.

## Tool call

```
bicameral.drift(
  file_path="<relative path from repo root>",
  use_working_tree=true,   # default: compare against disk (pre-commit)
)
```

- `file_path` — required, repo-relative
- `use_working_tree` — `true` (default) for pre-commit sweep (compare against disk), `false` for PR review (compare against HEAD)

## Response shape

The handler returns a `DetectDriftResponse` with:

- `file_path`, `source` (working_tree / HEAD), `sync_status`
- `decisions` — list of `DriftEntry` for every decision that touches this file's symbols
- `drifted_count` / `pending_count`
- `undocumented_symbols` — symbols in the file with no decision mapping

## How to render

1. Lead with the drifted decisions, if any. Surface `description`, `symbol:start_line-end_line`, `source_ref` + `meeting_date`, `source_excerpt` verbatim, and `drift_evidence`.
2. Then pending decisions (specified but not yet built).
3. Then reflected decisions (compactly — count is usually enough).
4. Undocumented symbols at the bottom.

## Example

**User**: *"is `src/pricing/discount.py` drifted?"*

**Call**: `bicameral.drift(file_path="src/pricing/discount.py")`

**Response**:

```
src/pricing/discount.py — 1 drifted decision.

⚠ DRIFTED: Apply 10% discount on orders ≥ $100
  DiscountService.calculate:42-67
  Source: sprint-14-planning · 2026-03-12
  "discounts are 10% on orders of $100 or more. below that, no discount."
  Drift: content hash mismatch — the function body no longer matches
  the stored baseline.

2 decisions pending, 4 reflected. 1 symbol in the file is undocumented:
calculate_shipping.
```

## Migration to scan_branch (recommended)

If the user wants to check multiple files, switch to `bicameral.scan_branch` without asking them. The transition is invisible from their end — they get better output in fewer calls.

```
# Before (v0.4.16 and earlier, anti-pattern)
bicameral.drift("file1.py")
bicameral.drift("file2.py")
bicameral.drift("file3.py")

# After (v0.4.17+)
bicameral.scan_branch()   # sweeps every file changed on the branch, deduped
```

## Arguments

$ARGUMENTS — the file path to check, repo-relative.
