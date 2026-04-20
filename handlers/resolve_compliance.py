"""Handler for /bicameral.resolve_compliance MCP tool.

The single caller-LLM verification write-back tool. Accepts a batch of
verdicts the caller LLM produced after evaluating ``pending_compliance_checks``
from a prior link_commit / ingest auto-chain response, and writes them
into the ``compliance_check`` cache.

Plan: 2026-04-20-ingest-time-verification.md (Phase 3).

Cache semantics (from Phase 2):
- Each verdict lands as a row keyed on
  ``(intent_id, region_id, content_hash)``.
- This handler also writes through to ``intent.status`` so users see
  the verdict take effect immediately. The plan's "status projected
  at read time" model is the long-term design (a follow-up cleanup);
  for now, persisted status mirrors the latest verdict so the existing
  drift-sweep fast-path (sync_cursor short-circuit on unchanged HEAD)
  doesn't strand the verdict invisible.
- **Multi-region aggregation caveat**: when an intent has multiple
  regions, last-verdict-wins on ``intent.status`` here. Correct
  aggregation (any-uncompliant-drifts-the-intent) requires the
  drift-sweep loop to run, which only happens when HEAD advances or
  the sync cursor is manually invalidated. Tracked as a follow-up.
- Idempotent: replaying the same batch is a no-op (UNIQUE index).
- First-write-wins: subsequent writes for the same key are silently
  treated as success but do not overwrite. Callers wanting to revise a
  verdict must delete the existing row first (a deliberate operation,
  not a side effect of resolving).

Input validation:
- Unknown ``intent_id`` or ``region_id`` are rejected (structured —
  not raised) so the caller can retry the accepted subset.
- ``content_hash`` is not validated against current/stored region hash
  — the cache is content-addressed, so a verdict for a hash that
  nothing will ever look up is harmless (one orphan cache row, GC'd
  by Phase 5a's cascade-delete).

Phase semantics:
- ``ingest`` — first-time grounding verification (post-ingest auto-chain).
- ``drift`` — re-verification after a code change touched a verified
  region.
- ``regrounding`` — symbol rename / move; reserved.
- ``supersession`` / ``divergence`` — accepted by the schema enum but
  no specific persistence path yet (write to compliance_check only).
"""
from __future__ import annotations

import logging
from typing import Iterable

from contracts import (
    ComplianceVerdict,
    ResolveComplianceAccepted,
    ResolveComplianceRejection,
    ResolveComplianceResponse,
)
from ledger.queries import (
    intent_exists,
    region_exists,
    update_intent_status,
    upsert_compliance_check,
)

logger = logging.getLogger(__name__)


_VALID_PHASES = {"ingest", "drift", "regrounding", "supersession", "divergence"}


def _coerce_verdicts(raw: Iterable[dict | ComplianceVerdict]) -> list[ComplianceVerdict]:
    """Accept dicts (from MCP JSON) or already-validated models."""
    out: list[ComplianceVerdict] = []
    for item in raw:
        if isinstance(item, ComplianceVerdict):
            out.append(item)
        else:
            out.append(ComplianceVerdict.model_validate(item))
    return out


async def handle_resolve_compliance(
    ctx,
    phase: str,
    verdicts: Iterable[dict | ComplianceVerdict],
    commit_hash: str | None = None,
) -> ResolveComplianceResponse:
    """Persist a batch of caller-LLM compliance verdicts.

    Parameters
    ----------
    ctx
        BicameralContext (provides ``ctx.ledger``).
    phase
        One of ``ingest`` / ``drift`` / ``regrounding`` / ``supersession``
        / ``divergence``. Routes the audit-trail label on each row.
    verdicts
        Iterable of ``ComplianceVerdict`` (or dicts shaped like one).
    commit_hash
        Optional provenance — usually passed for ``drift`` phase to
        record which commit triggered the verification.
    """
    if phase not in _VALID_PHASES:
        raise ValueError(
            f"Unknown phase {phase!r} — must be one of {sorted(_VALID_PHASES)}"
        )

    ledger = ctx.ledger
    if hasattr(ledger, "connect"):
        await ledger.connect()

    # Reach the underlying SurrealDB client. The team-mode wrapper exposes
    # ``_inner``; the bare adapter exposes ``_client`` directly.
    inner = getattr(ledger, "_inner", ledger)
    client = inner._client

    parsed = _coerce_verdicts(verdicts)

    accepted: list[ResolveComplianceAccepted] = []
    rejected: list[ResolveComplianceRejection] = []

    for v in parsed:
        # Validate intent + region exist BEFORE attempting to write.
        # Returning structured rejections (rather than raising) lets the
        # caller see exactly which entries failed and retry the rest.
        if not await intent_exists(client, v.intent_id):
            rejected.append(ResolveComplianceRejection(
                intent_id=v.intent_id,
                region_id=v.region_id,
                reason="unknown_intent_id",
                detail=f"no intent row for {v.intent_id}",
            ))
            continue

        if not await region_exists(client, v.region_id):
            rejected.append(ResolveComplianceRejection(
                intent_id=v.intent_id,
                region_id=v.region_id,
                reason="unknown_region_id",
                detail=f"no code_region row for {v.region_id}",
            ))
            continue

        await upsert_compliance_check(
            client,
            intent_id=v.intent_id,
            region_id=v.region_id,
            content_hash=v.content_hash,
            compliant=v.compliant,
            confidence=v.confidence,
            explanation=v.explanation,
            phase=phase,
            commit_hash=commit_hash or "",
        )

        # Write through to intent.status so the verdict is visible on the
        # next read without waiting for HEAD to advance. See the docstring
        # for the multi-region aggregation caveat — this is last-verdict-
        # wins for now.
        new_status = "reflected" if v.compliant else "drifted"
        await update_intent_status(client, v.intent_id, new_status)

        accepted.append(ResolveComplianceAccepted(
            intent_id=v.intent_id,
            region_id=v.region_id,
            phase=phase,
            compliant=v.compliant,
        ))

    logger.info(
        "[resolve_compliance] phase=%s accepted=%d rejected=%d commit=%s",
        phase, len(accepted), len(rejected), (commit_hash or "")[:8] or "n/a",
    )

    return ResolveComplianceResponse(
        phase=phase,
        accepted=accepted,
        rejected=rejected,
    )
