"""Handler for /bicameral.ratify MCP tool — v0.7.0.

Promotes a decision's signoff from {state:'proposed'} to {state:'ratified'}.
Calling ratify on an already-ratified decision is a no-op that returns the
existing signoff record with was_new=False.

No unratify tool. Rescinding signoff requires writing a new decision that
supersedes the previous one — clean audit trail, no hidden rollback.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from contracts import RatifyResponse
from ledger.queries import decision_exists, project_decision_status, update_decision_status

logger = logging.getLogger(__name__)


async def handle_ratify(
    ctx,
    decision_id: str,
    signer: str,
    note: str = "",
) -> RatifyResponse:
    """Promote signoff from proposed → ratified.

    Idempotent: calling ratify on an already-ratified decision returns
    was_new=False and leaves the existing signoff record untouched.

    Writes {state:'ratified', signer, session_id, ratified_at, note} to
    decision.signoff, then recomputes status via project_decision_status.
    """
    ledger = ctx.ledger
    if hasattr(ledger, "connect"):
        await ledger.connect()

    inner = getattr(ledger, "_inner", ledger)
    client = inner._client

    if not await decision_exists(client, decision_id):
        raise ValueError(f"No decision row for {decision_id}")

    # Check if already ratified (idempotency: state == 'ratified' wins)
    rows = await client.query(
        f"SELECT signoff FROM {decision_id} LIMIT 1",
    )
    existing_signoff = (rows[0].get("signoff") if rows else None) or None

    if existing_signoff and isinstance(existing_signoff, dict) and existing_signoff.get("state") == "ratified":
        projected = await project_decision_status(client, decision_id)
        return RatifyResponse(
            decision_id=decision_id,
            was_new=False,
            signoff=existing_signoff,
            projected_status=projected,
        )

    # Build the ratified signoff object
    head_ref = getattr(ctx, "authoritative_sha", "") or ""
    session_id = getattr(ctx, "session_id", None) or ""
    signoff = {
        "state": "ratified",
        "signer": signer,
        "session_id": session_id,
        "ratified_at": datetime.now(timezone.utc).isoformat(),
        "source_commit_ref": head_ref,
        "note": note,
    }

    await client.query(
        f"UPDATE {decision_id} SET signoff = $signoff",
        {"signoff": signoff},
    )

    projected = await project_decision_status(client, decision_id)
    await update_decision_status(client, decision_id, projected)

    logger.info(
        "[ratify] decision=%s signer=%s projected_status=%s",
        decision_id, signer, projected,
    )

    return RatifyResponse(
        decision_id=decision_id,
        was_new=True,
        signoff=signoff,
        projected_status=projected,
    )
