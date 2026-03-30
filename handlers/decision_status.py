"""Handler for /decision_status MCP tool.

Surfaces implementation status of all tracked decisions.
Read-only — does NOT auto-trigger link_commit.

Phase 0: backed by MockLedgerAdapter fixture data
Phase 2: backed by SurrealDBLedgerAdapter with real graph traversal
"""

from __future__ import annotations

from datetime import datetime, timezone

from adapters.ledger import get_ledger
from contracts import CodeRegionSummary, DecisionStatusEntry, DecisionStatusResponse


async def handle_decision_status(
    filter: str = "all",
    since: str | None = None,
    ref: str = "HEAD",
) -> DecisionStatusResponse:
    ledger = get_ledger()
    decisions_raw = await ledger.get_all_decisions(filter=filter)

    entries: list[DecisionStatusEntry] = []
    summary: dict[str, int] = {"reflected": 0, "drifted": 0, "pending": 0, "ungrounded": 0}

    for d in decisions_raw:
        # Filter by since if provided
        if since and d.get("ingested_at", "") < since:
            continue

        status = d.get("status", "ungrounded")
        summary[status] = summary.get(status, 0) + 1

        regions = [
            CodeRegionSummary(
                file_path=r["file_path"],
                symbol=r["symbol"],
                lines=tuple(r["lines"]),
                purpose=r.get("purpose", ""),
            )
            for r in d.get("code_regions", [])
        ]

        entries.append(DecisionStatusEntry(
            intent_id=d["intent_id"],
            description=d["description"],
            status=status,
            source_type=d.get("source_type", ""),
            source_ref=d.get("source_ref", ""),
            ingested_at=d.get("ingested_at", ""),
            code_regions=regions,
            drift_evidence=d.get("drift_evidence", ""),
            blast_radius=d.get("blast_radius", []),
        ))

    return DecisionStatusResponse(
        ref=ref,
        as_of=datetime.now(timezone.utc).isoformat(),
        summary=summary,
        decisions=entries,
    )
