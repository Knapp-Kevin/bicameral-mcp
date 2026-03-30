"""Handler for /detect_drift MCP tool.

Code review check: given a file path, surface all decisions that touch symbols
in that file, highlighting any that diverge from current content.
Auto-triggers link_commit(HEAD) first.

Phase 0: mock reverse traversal (decisions for fixture files)
Phase 1: real symbol extraction via code locator's extract_symbols() (tree-sitter,
         no LLM). Replaces mock undocumented_symbols with live symbol enumeration.
         Decisions still come from mock ledger.
Phase 2: real reverse traversal via SurrealDB `touches` edge + content-hash
         comparison. extract_symbols() moves to ingest-time (CodeIndexFlow).
"""

from __future__ import annotations

import os
from pathlib import Path

from adapters.code_locator import get_code_locator
from adapters.ledger import get_ledger
from contracts import DetectDriftResponse, DriftEntry, LinkCommitResponse
from handlers.link_commit import handle_link_commit


async def handle_detect_drift(
    file_path: str,
    use_working_tree: bool = True,
) -> DetectDriftResponse:
    # Auto-trigger link_commit(HEAD) first
    sync_status: LinkCommitResponse = await handle_link_commit("HEAD")

    ledger = get_ledger()
    repo_path = os.getenv("REPO_PATH", ".")

    raw_decisions = await ledger.get_decisions_for_file(file_path)

    # Phase 1: real symbol extraction via tree-sitter; Phase 0: mock
    if os.getenv("USE_REAL_CODE_LOCATOR", "0") == "1":
        adapter = get_code_locator()
        abs_path = str((Path(repo_path) / file_path).resolve())
        all_symbols = await adapter.extract_symbols(abs_path)
        # Symbols tracked by decisions
        decision_symbols = {
            d.get("code_region", {}).get("symbol", "") for d in raw_decisions
        }
        undocumented = [
            s["name"] for s in all_symbols if s["name"] not in decision_symbols
        ]
    else:
        undocumented = await ledger.get_undocumented_symbols(file_path)

    entries: list[DriftEntry] = []
    drifted_count = 0
    pending_count = 0

    for d in raw_decisions:
        region = d.get("code_region", {})
        status = d.get("status", "ungrounded")

        # Phase 2: compare content hash vs working tree / HEAD here
        # For now (Phase 0): use stored status from fixture data
        drift_evidence = ""
        if status == "drifted":
            drifted_count += 1
            drift_evidence = "Content hash mismatch detected (mock)"
        elif status == "pending":
            pending_count += 1

        entries.append(DriftEntry(
            intent_id=d["intent_id"],
            description=d["description"],
            status=status,
            symbol=region.get("symbol", ""),
            lines=tuple(region.get("lines", (0, 0))),
            drift_evidence=drift_evidence,
            source_ref=d.get("source_ref", ""),
        ))

    source = "working_tree" if use_working_tree else "HEAD"

    return DetectDriftResponse(
        file_path=file_path,
        sync_status=sync_status,
        source=source,
        decisions=entries,
        drifted_count=drifted_count,
        pending_count=pending_count,
        undocumented_symbols=undocumented,
    )
