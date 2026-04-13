#!/usr/bin/env python3
"""M1 decision-relevance eval — measures ungrounded rate end-to-end.

Ingests each transcript in the fixture registry (TRANSCRIPT_SOURCES) into a
fresh in-memory ledger, records how many decisions ground to real code, and
emits a per-transcript + per-repo JSON report. Used as a CI regression gate
(warn-only initially) and as the ruler for Phase 5 skill-spec A/B.

Usage:
    cd pilot/mcp
    .venv/bin/python tests/eval_decision_relevance.py \\
        --multi-repo '{"medusa":"test-results/.repos/medusa", \\
                       "saleor":"test-results/.repos/saleor", \\
                       "vendure":"test-results/.repos/vendure"}' \\
        -o test-results/m1-relevance.json

Flags:
    --multi-repo      JSON map repo_key -> repo path. Only source_refs whose
                      TRANSCRIPT_SOURCES.repo_key is in this map will run.
    --source-ref      Restrict to a single transcript (debugging).
    --skill-variant   'none'          : ingest fixture decisions directly
                                        (pure grounding-pipeline test).
                      'from-skill-md' : run headless LLM extraction from the
                                        current .claude/skills/bicameral-ingest/
                                        SKILL.md, then ingest the result.
                                        (Phase 4 — not implemented yet.)
    --min-grounded-pct    Regression gate. Exit non-zero if below (aggregate).
    --max-repo-variance   Regression gate. Exit non-zero if repo variance
                          exceeds threshold.
    -o / --output         Write JSON report to this path.
    --verbose             Print per-decision rows.

The fixture is the single source of truth for corpus + oracle. Adding a new
transcript = one entry in TRANSCRIPT_SOURCES. No runner changes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# Ensure pilot/mcp is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fixtures.expected.decisions import ALL_DECISIONS, TRANSCRIPT_SOURCES

# Repo root (parent of pilot/mcp/) — used to resolve fixture-relative transcript paths.
REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_transcript(rel_path: str) -> str:
    """Resolve a transcript path relative to the bicameral repo root."""
    p = (REPO_ROOT / rel_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"transcript not found: {p}")
    return p.read_text(encoding="utf-8")


def _decisions_for_source_ref(source_ref: str) -> list[dict]:
    return [d for d in ALL_DECISIONS if d.get("source_ref") == source_ref]


def _build_payload_from_fixture(source_ref: str) -> dict:
    """Build an ingest payload from the fixture oracle for this source_ref.

    Used by --skill-variant none. Each fixture entry's `description` becomes
    one decision. The runner bypasses the LLM extraction stage and feeds these
    directly into handle_ingest so we're measuring the grounding pipeline
    (code_graph.ground_mappings + ledger) in isolation.
    """
    fixture_decisions = _decisions_for_source_ref(source_ref)
    return {
        "source": "transcript",
        "title": source_ref,
        "decisions": [{"description": d["description"]} for d in fixture_decisions],
    }


def _build_payload_from_skill_md(transcript_text: str, source_ref: str) -> dict:
    """Call the headless extraction driver (Step 1 of the current SKILL.md)
    and shape the result as a natural-format ingest payload."""
    # tests/ has no __init__.py; import as a sibling module via the dir on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _extract_headless import extract_from_current_skill  # type: ignore[import-not-found]

    extracted = extract_from_current_skill(
        transcript_text,
        source_ref=source_ref,
    )
    decisions = [
        {"description": d.get("description", "")}
        for d in (extracted.get("decisions") or [])
        if d.get("description")
    ]
    action_items = [
        {"text": a.get("text", ""), "owner": a.get("owner")}
        for a in (extracted.get("action_items") or [])
        if a.get("text")
    ]
    return {
        "source": "transcript",
        "title": source_ref,
        "decisions": decisions,
        "action_items": action_items,
    }


async def _ingest_one(
    ctx,
    source_ref: str,
    transcript_text: str,
    skill_variant: str,
) -> dict:
    """Run a single transcript through handle_ingest and return per-decision rows."""
    from handlers.ingest import handle_ingest

    if skill_variant == "none":
        payload = _build_payload_from_fixture(source_ref)
    elif skill_variant == "from-skill-md":
        payload = _build_payload_from_skill_md(transcript_text, source_ref)
    else:
        raise ValueError(f"unknown skill-variant: {skill_variant!r}")

    # Tag the payload with the source_ref so per-transcript queries work cleanly.
    payload["title"] = source_ref

    result = await handle_ingest(ctx, payload)
    stats = result.stats

    fixture = {d["description"]: d for d in _decisions_for_source_ref(source_ref)}

    return {
        "source_ref": source_ref,
        "intents_created": stats.intents_created,
        "grounded": stats.grounded,
        "ungrounded": stats.ungrounded,
        "grounded_pct": round(stats.grounded_pct, 4),
        "grounding_deferred": stats.grounding_deferred,
        "ungrounded_intents": list(result.ungrounded_intents),
        "fixture_size": len(fixture),
    }


async def _run_repo(
    repo_key: str,
    repo_path: str,
    source_refs: list[str],
    skill_variant: str,
    surreal_url: str,
    verbose: bool,
) -> dict:
    """Run all transcripts for a single repo under a fresh ctx/ledger."""
    from adapters.ledger import reset_ledger_singleton
    from context import BicameralContext

    os.environ["REPO_PATH"] = str(Path(repo_path).resolve())
    os.environ["SURREAL_URL"] = surreal_url
    os.environ.setdefault("USE_REAL_LEDGER", "1")

    per_transcript: list[dict] = []

    for source_ref in source_refs:
        src = TRANSCRIPT_SOURCES[source_ref]
        transcript_text = _load_transcript(src["transcript"])

        # Fresh ledger per transcript — prevents cross-contamination.
        reset_ledger_singleton()
        ctx = BicameralContext.from_env()
        if hasattr(ctx.ledger, "connect"):
            await ctx.ledger.connect()

        row = await _ingest_one(ctx, source_ref, transcript_text, skill_variant)
        per_transcript.append(row)

        if verbose:
            print(
                f"  [{repo_key}] {source_ref}: "
                f"{row['grounded']}/{row['intents_created']} "
                f"grounded ({row['grounded_pct']:.0%})"
            )

    totals = {
        "intents_created": sum(r["intents_created"] for r in per_transcript),
        "grounded": sum(r["grounded"] for r in per_transcript),
        "ungrounded": sum(r["ungrounded"] for r in per_transcript),
    }
    totals["grounded_pct"] = round(
        (totals["grounded"] / totals["intents_created"]) if totals["intents_created"] else 0.0,
        4,
    )

    return {
        "repo_key": repo_key,
        "repo_path": str(Path(repo_path).resolve()),
        "transcripts": per_transcript,
        "totals": totals,
    }


async def run(args) -> tuple[dict, int]:
    repo_map: dict[str, str] = json.loads(args.multi_repo) if args.multi_repo else {}
    if not repo_map:
        print("error: --multi-repo is required", file=sys.stderr)
        return {}, 2

    # Build work plan: group source_refs by repo_key, honoring --source-ref filter.
    plan: dict[str, list[str]] = defaultdict(list)
    skipped_source_refs: list[str] = []

    for source_ref, src in TRANSCRIPT_SOURCES.items():
        if args.source_ref and source_ref != args.source_ref:
            continue
        if src["repo_key"] not in repo_map:
            skipped_source_refs.append(source_ref)
            continue
        plan[src["repo_key"]].append(source_ref)

    if not plan:
        print(
            f"error: no transcripts to run (skipped: {skipped_source_refs})",
            file=sys.stderr,
        )
        return {}, 2

    print(f"M1 decision-relevance eval (skill-variant={args.skill_variant})")
    print(f"  repos: {list(plan.keys())}")
    print(f"  transcripts: {sum(len(v) for v in plan.values())}")
    if skipped_source_refs:
        print(f"  skipped (no repo in --multi-repo): {len(skipped_source_refs)}")
    print()

    repo_reports: list[dict] = []
    for repo_key, source_refs in plan.items():
        report = await _run_repo(
            repo_key=repo_key,
            repo_path=repo_map[repo_key],
            source_refs=source_refs,
            skill_variant=args.skill_variant,
            surreal_url=args.surreal_url,
            verbose=args.verbose,
        )
        repo_reports.append(report)
        t = report["totals"]
        print(
            f"  [{repo_key}] {t['grounded']}/{t['intents_created']} "
            f"grounded ({t['grounded_pct']:.0%})"
        )

    # Aggregate.
    total_intents = sum(r["totals"]["intents_created"] for r in repo_reports)
    total_grounded = sum(r["totals"]["grounded"] for r in repo_reports)
    aggregate_pct = (total_grounded / total_intents) if total_intents else 0.0
    per_repo_pcts = [r["totals"]["grounded_pct"] for r in repo_reports]
    repo_variance = (
        round(max(per_repo_pcts) - min(per_repo_pcts), 4) if len(per_repo_pcts) > 1 else 0.0
    )

    combined = {
        "skill_variant": args.skill_variant,
        "repos": {r["repo_key"]: r for r in repo_reports},
        "aggregate": {
            "intents_created": total_intents,
            "grounded": total_grounded,
            "grounded_pct": round(aggregate_pct, 4),
            "repo_variance": repo_variance,
            "per_repo_grounded_pct": {
                r["repo_key"]: r["totals"]["grounded_pct"] for r in repo_reports
            },
        },
        "skipped_source_refs": skipped_source_refs,
    }

    print()
    print(
        f"  aggregate: {total_grounded}/{total_intents} "
        f"grounded ({aggregate_pct:.0%}, variance={repo_variance:.3f})"
    )

    # Regression gates.
    exit_code = 0
    if args.min_grounded_pct is not None and aggregate_pct < args.min_grounded_pct:
        print(
            f"\n❌ REGRESSION: grounded_pct {aggregate_pct:.3f} "
            f"< threshold {args.min_grounded_pct:.3f}",
            file=sys.stderr,
        )
        exit_code = 1
    if args.max_repo_variance is not None and repo_variance > args.max_repo_variance:
        print(
            f"\n❌ REGRESSION: repo variance {repo_variance:.3f} "
            f"> threshold {args.max_repo_variance:.3f}",
            file=sys.stderr,
        )
        exit_code = 1
    if exit_code == 0 and args.min_grounded_pct is not None:
        print(
            f"\n✅ PASS: grounded_pct {aggregate_pct:.3f} "
            f"≥ threshold {args.min_grounded_pct:.3f}"
        )

    return combined, exit_code


def main():
    parser = argparse.ArgumentParser(description="M1 decision-relevance evaluation")
    parser.add_argument(
        "--multi-repo",
        type=str,
        required=True,
        help='JSON map repo_key -> path, e.g. \'{"medusa":"test-results/.repos/medusa"}\'',
    )
    parser.add_argument(
        "--source-ref",
        type=str,
        default=None,
        help="Restrict to a single source_ref (debugging).",
    )
    parser.add_argument(
        "--skill-variant",
        type=str,
        default="none",
        choices=["none", "from-skill-md"],
        help="'none' = ingest fixture decisions directly; 'from-skill-md' = Phase 4 LLM extraction.",
    )
    parser.add_argument(
        "--min-grounded-pct",
        type=float,
        default=None,
        help="Regression gate: fail if aggregate grounded_pct below this.",
    )
    parser.add_argument(
        "--max-repo-variance",
        type=float,
        default=None,
        help="Regression gate: fail if repo variance exceeds this.",
    )
    parser.add_argument(
        "--surreal-url",
        type=str,
        default="memory://",
        help="SurrealDB URL (default memory:// for isolated eval).",
    )
    parser.add_argument("--output", "-o", help="Write JSON report to file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Per-decision rows")
    args = parser.parse_args()

    combined, exit_code = asyncio.run(run(args))

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(combined, indent=2))
        print(f"\n  report written to {out}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
