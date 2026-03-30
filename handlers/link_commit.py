"""Handler for /link_commit MCP tool.

Heartbeat of the ledger — syncs a commit's changes into the graph.
Idempotent: calling twice for the same commit is a no-op.

Phase 0: backed by MockLedgerAdapter (no SurrealDB, no git ops)
Phase 2: backed by SurrealDBLedgerAdapter with real git diff parsing
"""

from __future__ import annotations

import os

from adapters.ledger import get_ledger
from contracts import LinkCommitResponse


async def handle_link_commit(commit_hash: str = "HEAD") -> LinkCommitResponse:
    ledger = get_ledger()
    repo_path = os.getenv("REPO_PATH", ".")

    result = await ledger.ingest_commit(commit_hash, repo_path)

    return LinkCommitResponse(
        commit_hash=result["commit_hash"],
        synced=result["synced"],
        reason=result["reason"],
        regions_updated=result.get("regions_updated", 0),
        decisions_reflected=result.get("decisions_reflected", 0),
        decisions_drifted=result.get("decisions_drifted", 0),
        undocumented_symbols=result.get("undocumented_symbols", []),
    )
