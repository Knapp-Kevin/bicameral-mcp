"""Interactive setup wizard for bicameral-mcp.

Guides the user through selecting a repo and installs the MCP server
config into Claude Code, Claude Desktop, and/or Cursor.

Usage: bicameral-mcp setup
       bicameral-mcp setup /path/to/repo
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
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


def _detect_clients() -> list[str]:
    """Detect which MCP clients are available."""
    clients = []
    if shutil.which("claude"):
        clients.append("claude-code")
    if _claude_desktop_config_path().parent.exists():
        clients.append("claude-desktop")
    # Could add cursor detection here
    return clients or ["claude-code"]  # default to claude-code instructions


def _claude_desktop_config_path() -> Path:
    """Return the Claude Desktop config file path."""
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif platform.system() == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    else:
        return Path.home() / ".config" / "claude" / "claude_desktop_config.json"


def _build_config(repo_path: Path) -> dict:
    """Build the MCP server config object."""
    return {
        "command": "uvx",
        "args": ["bicameral-mcp"],
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
            print("  Installed in Claude Code (user scope)")
            return True
        else:
            print(f"  claude mcp add-json failed: {result.stderr.strip()}")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _install_claude_desktop(repo_path: Path) -> bool:
    """Install by writing to claude_desktop_config.json."""
    config_path = _claude_desktop_config_path()

    if not config_path.parent.exists():
        return False

    # Read existing config
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}
    else:
        existing = {}

    servers = existing.setdefault("mcpServers", {})
    servers["bicameral"] = _build_config(repo_path)

    config_path.write_text(json.dumps(existing, indent=2))
    print(f"  Installed in Claude Desktop: {config_path}")
    print("  Restart Claude Desktop to activate.")
    return True


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

    # Step 2: Detect clients
    clients = _detect_clients()
    installed = []

    # Step 3: Install
    print()
    if "claude-code" in clients:
        if _install_claude_code(repo_path):
            installed.append("Claude Code")

    if "claude-desktop" in clients:
        if _install_claude_desktop(repo_path):
            installed.append("Claude Desktop")

    # Step 4: Fallback — show manual instructions
    if not installed:
        config = _build_config(repo_path)
        config_json = json.dumps({"mcpServers": {"bicameral": config}}, indent=2)
        print("  Could not auto-install. Add this to your MCP config:\n")
        print(f"  {config_json}")
        print()
        print("  Config file locations:")
        print("    Claude Code:    claude mcp add-json bicameral --scope user '<json>'")
        print(f"    Claude Desktop: {_claude_desktop_config_path()}")
        print()

    # Step 5: Summary
    if installed:
        print(f"\n  Done! Bicameral MCP is ready in: {', '.join(installed)}")
        print(f"  Analyzing repo: {repo_path}")
        print()
        print("  Try these in your next conversation:")
        print('    "What decisions have been made about authentication?"')
        print('    "Check if this file has any drifted decisions"')
        print()

    return 0
