---
name: bicameral-drift
description: Check a single file for drifted decisions before committing or during code review. Surfaces all decisions that touch symbols in the file and flags divergence. Use bicameral-scan-branch for multi-file or whole-branch scope.
---

# Bicameral Drift

Code review check — surface decisions that touch a file and flag any that have drifted from intent.

## When to use

- Before committing changes to a specific file
- During code review / PR review when the user names a single file
- When the user asks "are there any drifted decisions for this file?"

Use `bicameral-scan-branch` instead for multi-file scope or when the user says
"check my branch", "scan my PR", etc.

## Steps

1. Determine the file path — from $ARGUMENTS, the currently open file, or ask the user.
2. Call `bicameral.drift`:
   ```
   bicameral.drift(
     file_path="<relative path from repo root>",
     use_working_tree=true    # pre-commit: compare against disk
                              # false for PR review: compare against HEAD
   )
   ```
3. **Resolve pending compliance checks** if `sync_status.pending_compliance_checks`
   is non-empty (see section below).
4. Present the results:
   - **Drifted**: code has changed since the decision was recorded — needs review
   - **Pending**: decision exists but no code written yet
   - **Reflected**: code matches the decision — all good
5. For drifted decisions, quote `source_excerpt` verbatim and explain what changed.

## After the call: resolve pending compliance checks

If `sync_status.pending_compliance_checks` is non-empty, the server found regions
with a new content hash but no cached compliance verdict. **Without your verdict,
those decisions stay `"pending"` indefinitely — the caller-LLM verdict is the only
path to `"reflected"` or `"drifted"` status.**

For each `PendingComplianceCheck` in the list:

1. **Read the code.** `code_body` is pre-extracted by the server (capped at ~200 lines).
   If it looks truncated, read `file_path` directly for full context.

2. **Compare** `decision_description` against `code_body`. Ask: does this code
   *functionally implement* the decision, or just share keywords?
   - `"compliant"` — code implements the decision correctly
   - `"drifted"` — code has diverged (threshold changed, behavior removed, etc.)
   - `"not_relevant"` — retrieval made a mistake; this region is unrelated to the
     decision (server will prune the `binds_to` edge)

3. **Batch all verdicts into one call:**
   ```
   bicameral.resolve_compliance(
     phase="drift",
     flow_id="<sync_status.flow_id>",
     verdicts=[{
       decision_id: "<check.decision_id>",
       region_id: "<check.region_id>",
       content_hash: "<check.content_hash — echo exactly>",
       verdict: "compliant" | "drifted" | "not_relevant",
       confidence: "high" | "medium" | "low",
       explanation: "<one sentence: why this code does/doesn't match the decision>"
     }, ...]
   )
   ```

   The `content_hash` is a compare-and-set guard — echo it exactly from the check.
   If the file changed between the drift call and your read, the server rejects the
   verdict and the region stays `"pending"` until the next sweep.

Skip this step when `pending_compliance_checks` is empty.

## Arguments

$ARGUMENTS — file path to check (relative to repo root)

## Example

User: "/bicameral:drift payments/processor.py"
→ Call `bicameral.drift` with `file_path="payments/processor.py"`, `use_working_tree=true`
→ If `sync_status.pending_compliance_checks` is non-empty, call `bicameral.resolve_compliance`
  with `phase="drift"` and verdicts for each check.
→ "2 decisions touch this file: (1) 'Webhook retry with backoff' — DRIFTED (code changed
  since decision). (2) 'Log payment failures' — reflected."
