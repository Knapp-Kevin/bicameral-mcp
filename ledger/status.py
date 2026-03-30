"""Content-hash based status derivation (Branch Problem — Approach 2).

Status is NEVER stored as a fact. It is re-derived at query time by comparing:
    sha256(git show <ref>:<file>[start_line:end_line])
    vs
    code_region.content_hash (stored baseline from last link_commit)

This makes Bicameral immune to rebase, squash, and cherry-pick.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def hash_lines(content: str, start_line: int, end_line: int) -> str:
    """SHA-256 of the specific line range (1-indexed, inclusive)."""
    lines = content.splitlines()
    # Convert to 0-indexed
    start = max(0, start_line - 1)
    end = min(len(lines), end_line)
    region = "\n".join(lines[start:end])
    return hashlib.sha256(region.encode()).hexdigest()


def get_git_content(
    file_path: str,
    start_line: int,
    end_line: int,
    repo_path: str,
    ref: str = "HEAD",
) -> str | None:
    """Extract content of file[start:end] at a given git ref.

    Returns None if the file/ref doesn't exist (symbol not yet committed).
    Uses disk read for working tree (ref='working_tree').
    """
    abs_repo = Path(repo_path).resolve()
    abs_file = abs_repo / file_path

    if ref == "working_tree":
        if not abs_file.exists():
            return None
        try:
            return abs_file.read_text(errors="replace")
        except OSError:
            return None

    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{file_path}"],
            cwd=abs_repo,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def compute_content_hash(
    file_path: str,
    start_line: int,
    end_line: int,
    repo_path: str,
    ref: str = "HEAD",
) -> str | None:
    """Compute sha256 of file[start_line:end_line] at git ref.

    Returns None if the file doesn't exist at that ref (symbol not yet in code).
    """
    content = get_git_content(file_path, start_line, end_line, repo_path, ref)
    if content is None:
        return None
    return hash_lines(content, start_line, end_line)


def derive_status(
    stored_hash: str,
    actual_hash: str | None,
) -> str:
    """Derive intent status from hash comparison.

    - actual_hash is None → symbol absent at this ref → 'pending'
    - stored_hash is empty → never been indexed → 'ungrounded'
    - actual_hash == stored_hash → code unchanged → 'reflected' (or last set status)
    - actual_hash != stored_hash → code changed since baseline → 'drifted'

    Note: 'reflected' vs 'drifted' from hash alone is best-effort.
    Phase 3 will add an LLM drift judge for semantic comparison.
    """
    if not stored_hash:
        return "ungrounded"
    if actual_hash is None:
        return "pending"
    if actual_hash == stored_hash:
        return "reflected"
    return "drifted"


def get_changed_files(commit_hash: str, repo_path: str) -> list[str]:
    """Return list of files changed in a commit (relative to repo root)."""
    try:
        result = subprocess.run(
            ["git", "show", commit_hash, "--name-only", "--format="],
            cwd=Path(repo_path).resolve(),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            logger.warning("[status] git show failed for %s: %s", commit_hash, result.stderr[:200])
            return []
        return [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("[status] git show error: %s", e)
        return []


def resolve_head(repo_path: str) -> str | None:
    """Return current HEAD SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(repo_path).resolve(),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None
