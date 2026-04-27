"""Session-sync middleware.

Single entry point:

- ``ensure_ledger_synced(ctx)`` — lazy HEAD catch-up. Keeps the ledger current
  without requiring an explicit link_commit call before every tool.

Called at the top of every tool dispatch in server.py (except link_commit
itself). Uses a process-level SHA cache so the link_commit DB+git work only
runs when HEAD has actually moved. Safe to call concurrently; swallows all
exceptions so it never blocks a handler.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contracts import LinkCommitResponse

logger = logging.getLogger(__name__)

# Process-level cache: survives across call_tool invocations within the same
# server process. Avoids re-running link_commit when HEAD hasn't moved.
_LAST_SYNCED_SHA: str | None = None



# ── V1 A2-light: per-repo write barrier ─────────────────────────────────
# Module-level registry of per-repo asyncio.Locks. Serializes mutating
# handlers against the same repo inside a single MCP server process.
# Deliberately does NOT protect:
#   - handlers/resolve_compliance.py (destructive path — V2 scope)
#   - cross-process writers (requires sync-token CAS at commit time — V2)
# Scope is intentionally narrow; see docs/v2-desync-optimization-guide.md
# §5.7 for the V2 expansion (region fingerprint + sync-token CAS).
_repo_locks: dict[str, asyncio.Lock] = {}
_repo_locks_guard: asyncio.Lock | None = None


def _guard() -> asyncio.Lock:
    """Lazily create the guard in whatever loop the first caller runs in.

    Creating an asyncio.Lock at import time binds it to a loop that may
    not exist yet (e.g. tests using asyncio.run each spin up a fresh loop).
    Lazy creation inside a coroutine avoids the "lock bound to wrong loop"
    pitfall.
    """
    global _repo_locks_guard
    if _repo_locks_guard is None:
        _repo_locks_guard = asyncio.Lock()
    return _repo_locks_guard


async def _get_repo_lock(repo_path: str) -> asyncio.Lock:
    async with _guard():
        lock = _repo_locks.get(repo_path)
        if lock is None:
            lock = asyncio.Lock()
            _repo_locks[repo_path] = lock
        return lock


@asynccontextmanager
async def repo_write_barrier(ctx):
    """Serialize code-shape mutations against the same repo in-process.

    V1 scope: wrap `handle_bind` only. Different repos run concurrently;
    same repo is serialized. Yields a mutable ``BarrierTiming`` holder
    whose ``held_ms`` attribute is set when the barrier exits, so the
    enclosing handler can attach it to its response. Lock always releases
    on exit (including exceptions). Fail-safe: if ``ctx.repo_path`` is
    missing, falls back to key ``"."`` so the barrier still serializes.
    """
    repo = getattr(ctx, "repo_path", "") or "."
    lock = await _get_repo_lock(repo)
    timing = BarrierTiming()
    async with lock:
        t0 = time.perf_counter()
        try:
            yield timing
        finally:
            timing.held_ms = round((time.perf_counter() - t0) * 1000, 3)


class BarrierTiming:
    """Mutable timing holder yielded by ``repo_write_barrier``.

    ``held_ms`` is populated when the barrier's ``async with`` exits.
    Handlers read it after the ``async with`` block to attach the number
    to their ``SyncMetrics`` response field.
    """
    __slots__ = ("held_ms",)

    def __init__(self) -> None:
        self.held_ms: float | None = None


def _reset_repo_locks_for_tests() -> None:
    """Drop all registered repo locks. Test-only helper.

    Lets each test start with a fresh lock registry so lock identity is
    deterministic within a single test. Not exposed outside the test
    module.
    """
    global _repo_locks_guard
    _repo_locks.clear()
    _repo_locks_guard = None


async def ensure_ledger_synced(ctx) -> "LinkCommitResponse | None":
    """Sync ledger to HEAD if it has moved since the last sync in this process.

    Returns the LinkCommitResponse when a new commit was processed — callers
    should inspect pending_compliance_checks and surface them to the agent.
    Returns None when HEAD hasn't changed (no-op) or on error.
    """
    global _LAST_SYNCED_SHA

    try:
        from handlers.link_commit import handle_link_commit, _read_current_head_sha
        live_head = _read_current_head_sha(getattr(ctx, "repo_path", "") or ".")
        if live_head and live_head != _LAST_SYNCED_SHA:
            result = await handle_link_commit(ctx, "HEAD")
            _LAST_SYNCED_SHA = live_head
            logger.debug("[sync_middleware] catch-up ran for %s", live_head[:8])
            return result
    except Exception as exc:
        logger.debug("[sync_middleware] catch-up failed: %s", exc)
    return None
