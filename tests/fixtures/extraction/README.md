# M1 ground-truth extraction fixtures

**Ground truth** for the M1 decision-relevance eval's precision/recall metric.
Each JSON file in this directory represents what an ideal decision extraction
from one transcript should look like. The M1 runner
(`tests/eval_decision_relevance.py`) compares the current skill's Haiku
extraction against these fixtures to compute per-transcript and aggregate
precision / recall / F1.

## Model B rationale

We separated "simulation" (what the current `bicameral-ingest` skill + Haiku
extracts in CI on every run) from "ground truth" (what we consider a correct
extraction of each transcript). Ground truth is:

- **Pregenerated offline** with a stronger model (Opus 4.6) via
  `tests/regen_extraction_fixtures.py`.
- **Committed to git** in this directory, one file per `source_ref`.
- **Hand-editable** — if Opus gets a decision wrong or misses one, just edit
  the JSON directly and commit. Opus is the bootstrap, not the oracle.

The point of the M1 metric is to answer "can the bicameral skill + MCP +
Haiku approximate what Opus produces?". Phase 5 skill-spec A/B branches
change `SKILL.md` and compare precision/recall deltas against this fixed
target.

## File format

One file per transcript, named `<source_ref>.json`. `source_ref` matches
keys in `pilot/mcp/tests/fixtures/expected/decisions.py:TRANSCRIPT_SOURCES`.

```json
{
  "source_ref": "medusa-payment-timeout",
  "transcript_path": "pilot/ml/data/transcripts/medusa-payment-timeout.md",
  "repo_key": "medusa",
  "generated_by": "claude-opus-4-6-20251015",
  "generated_at": "2026-04-13T22:30:00+00:00",
  "skill_md_sha": "abcd1234ef56",
  "decisions": [
    { "description": "..." }
  ],
  "action_items": [
    { "text": "...", "owner": "..." }
  ]
}
```

Fields:

- `source_ref` / `transcript_path` / `repo_key` — provenance.
- `generated_by` — the model ID used at bootstrap (or `human-edited` after
  corrections).
- `generated_at` — wall-clock timestamp of the last regeneration.
- `skill_md_sha` — first 12 chars of the SKILL.md hash at generation time,
  so you can see at a glance whether the fixture is stale vs the current
  skill prompt.
- `decisions[].description` — a single self-contained sentence. This is
  what the M1 metric fuzzy-matches against.
- `action_items[]` — owner may be null if unnamed in the transcript.

## How to regenerate

From `pilot/mcp`:

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
.venv/bin/python tests/regen_extraction_fixtures.py --all
```

Options:

- `--source-ref <ref>` — regenerate one transcript only.
- `--model <id>` — override the default (`claude-opus-4-6-20251015`). Cheaper
  models work but degrade ground-truth quality.
- `--force` — overwrite existing fixtures without prompting.
- `--dry-run` — don't write files, just print what would change.

Cost (approximate): ~**\$1.75** for a full-corpus regeneration with Opus 4.6.
One-shot, rarely repeated.

After running, `git diff pilot/mcp/tests/fixtures/extraction/` shows the new
or changed fixtures. Review, hand-edit if needed, commit, push.

## When to hand-edit

- Opus missed an obvious decision — add it to `decisions`.
- Opus included a decision that isn't implementation-relevant — remove it.
- Opus split one decision into two, or merged two into one, and you
  disagree — rewrite the entry.
- A transcript has been updated and an old decision no longer applies —
  edit both the transcript and the fixture, commit together.

Do **not** hand-edit `generated_by` / `generated_at` / `skill_md_sha` —
those are provenance fields. If you hand-edit the decisions, change
`generated_by` to `human-edited` so the audit trail is honest.

## How CI uses this

The `M1 relevance gate — extraction + grounding` step in
`.github/workflows/test-mcp-regression.yml` runs the runner with
`--skill-variant from-skill-md`. The runner:

1. Calls Haiku 4.5 on each transcript via the current SKILL.md → gets
   simulated decisions.
2. Ingests those decisions through the MCP pipeline → computes
   `grounded_pct`.
3. Loads the ground-truth fixture for this `source_ref` from this
   directory (silently skips the metric if no fixture exists).
4. Fuzzy-matches simulated vs ground-truth decisions via rapidfuzz
   `token_set_ratio` with threshold 70 → computes precision / recall / F1.

If no fixtures are committed yet, the metric is reported as "skipped" and
only `grounded_pct` shows up in the artifact. CI stays green.
