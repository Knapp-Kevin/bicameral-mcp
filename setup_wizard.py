"""Interactive setup wizard for bicameral-mcp.

Guides the user through selecting a repo and installs the MCP server
config into Claude Code.

Usage: bicameral-mcp setup
       bicameral-mcp setup /path/to/repo
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def _detect_repo(hint: str | None = None) -> Path:
    """Detect or prompt for the repo path."""
    # If hint provided, use it
    if hint:
        p = Path(hint).resolve()
        if p.is_dir():
            return p
        print(f"  Path not found: {p}")

    # Try cwd
    cwd = Path.cwd()
    git_root = _find_git_root(cwd)

    if git_root:
        answer = input(f"\n  Detected git repo: {git_root}\n  Use this? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            return git_root

    # Manual entry
    while True:
        raw = input("\n  Enter the path to your repo: ").strip()
        if not raw:
            continue
        p = Path(raw).expanduser().resolve()
        if p.is_dir():
            return p
        print(f"  Not a directory: {p}")


def _find_git_root(start: Path) -> Path | None:
    """Walk up from start to find .git directory."""
    current = start
    for _ in range(20):
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _detect_runner() -> tuple[str, list[str]]:
    """Detect the best available Python package runner.

    Returns (command, args) for the MCP server config.
    Priority: uvx > pipx > python -m
    """
    if shutil.which("uvx"):
        return ("uvx", ["bicameral-mcp"])
    if shutil.which("pipx"):
        return ("pipx", ["run", "bicameral-mcp"])
    # Fall back to python -m
    python = "python3" if shutil.which("python3") else "python"
    return (python, ["-m", "bicameral_mcp"])


def _build_config(repo_path: Path) -> dict:
    """Build the MCP server config object."""
    command, args = _detect_runner()
    return {
        "command": command,
        "args": args,
        "env": {
            "REPO_PATH": str(repo_path),
        },
    }


def _install_claude_code(repo_path: Path) -> bool:
    """Install via `claude mcp add-json`."""
    config = _build_config(repo_path)
    config_json = json.dumps(config)

    try:
        result = subprocess.run(
            ["claude", "mcp", "add-json", "bicameral", "--scope", "user", config_json],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            print(f"  Installed in Claude Code (user scope) using {config['command']}")
            return True
        else:
            print(f"  claude mcp add-json failed: {result.stderr.strip()}")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_setup(repo_hint: str | None = None) -> int:
    """Run the interactive setup wizard."""
    print()
    print("  ┌─────────────────────────────────────────┐")
    print("  │  Bicameral MCP — Setup                   │")
    print("  │  Decision ledger for your codebase        │")
    print("  └─────────────────────────────────────────┘")
    print()

    # Step 1: Select repo
    repo_path = _detect_repo(repo_hint)
    print(f"\n  Repo: {repo_path}")

    # Step 2: Detect runner
    command, _ = _detect_runner()
    if command not in ("uvx", "pipx"):
        print(f"\n  Note: using '{command} -m bicameral_mcp' as runner.")
        print("  Make sure bicameral-mcp is installed: pip install bicameral-mcp")

    # Step 3: Install to Claude Code
    print()
    if shutil.which("claude"):
        if _install_claude_code(repo_path):
            print(f"\n  Done! Bicameral MCP is ready in Claude Code.")
            print(f"  Analyzing repo: {repo_path}")
            print()
            print("  Try these in your next conversation:")
            print('    "What decisions have been made about authentication?"')
            print('    "Check if this file has any drifted decisions"')
            print()
            return 0

    # Step 4: Fallback — show manual instructions
    config = _build_config(repo_path)
    config_json = json.dumps(config, indent=2)
    print("  Claude Code CLI not found. Run this manually:\n")
    print(f"    claude mcp add-json bicameral --scope user '{config_json}'")
    print()
    if command not in ("uvx", "pipx"):
        print("  Or install a package runner for zero-install execution:")
        print("    pip install pipx   # then re-run: bicameral-mcp setup")
        print()

    return 0
