"""Check alignment between visual plan docs and actual implementation.

Verifies that bicameral-mcp-system.html accurately reflects:
  - Tool count and names (from server.py EXPECTED_TOOL_NAMES)
  - Handler files (from handlers/)
  - Ledger files (from ledger/)
  - Adapter wiring (no mock references)
  - Mock status (mocks/ should be empty of .py files)

Run: python tests/check_doc_alignment.py
Exit 0 = aligned, Exit 1 = discrepancies found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parent.parent
VISUAL_PLAN = MCP_ROOT / "visual-plan" / "plans" / "bicameral-mcp-system.html"

errors: list[str] = []


def error(msg: str) -> None:
    errors.append(msg)
    print(f"  FAIL: {msg}", file=sys.stderr)


def check_tool_names() -> None:
    """Verify tool names in the visual plan match server.py EXPECTED_TOOL_NAMES."""
    # Read the canonical tool list from server.py
    server_py = MCP_ROOT / "server.py"
    server_text = server_py.read_text()

    match = re.search(
        r"EXPECTED_TOOL_NAMES\s*=\s*\[(.*?)\]", server_text, re.DOTALL
    )
    if not match:
        error("Could not find EXPECTED_TOOL_NAMES in server.py")
        return

    server_tools = set(re.findall(r'"([^"]+)"', match.group(1)))
    html_text = VISUAL_PLAN.read_text()

    missing_from_doc = []
    for tool in sorted(server_tools):
        if tool not in html_text:
            missing_from_doc.append(tool)

    if missing_from_doc:
        error(
            f"Tools in server.py but missing from visual plan: {missing_from_doc}"
        )

    # Check tool count claim in the HTML
    count_match = re.search(r'(\d+)\s*</div>\s*<div class="metric-sub">5 ledger \+ 4 code locator', html_text)
    if count_match:
        claimed = int(count_match.group(1))
        actual = len(server_tools)
        if claimed != actual:
            error(
                f"Visual plan claims {claimed} tools but server.py has {actual}"
            )
    else:
        # Try a simpler check
        if f">{len(server_tools)}<" not in html_text:
            error(
                f"Visual plan may not reflect the correct tool count ({len(server_tools)})"
            )


def check_handler_files() -> None:
    """Verify handler files listed in the visual plan match reality."""
    handlers_dir = MCP_ROOT / "handlers"
    actual_handlers = {
        f.stem
        for f in handlers_dir.glob("*.py")
        if f.stem != "__init__"
    }

    html_text = VISUAL_PLAN.read_text()

    missing_from_doc = []
    for handler in sorted(actual_handlers):
        if handler not in html_text:
            missing_from_doc.append(handler)

    if missing_from_doc:
        error(
            f"Handler files exist but not mentioned in visual plan: {missing_from_doc}"
        )


def check_ledger_files() -> None:
    """Verify ledger/ files listed in the visual plan match reality."""
    ledger_dir = MCP_ROOT / "ledger"
    actual_files = {
        f.name
        for f in ledger_dir.glob("*.py")
        if f.stem != "__init__"
    }

    html_text = VISUAL_PLAN.read_text()

    missing_from_doc = []
    for fname in sorted(actual_files):
        if fname.replace(".py", "") not in html_text:
            missing_from_doc.append(fname)

    if missing_from_doc:
        error(
            f"Ledger files exist but not mentioned in visual plan: {missing_from_doc}"
        )


def check_no_active_mocks() -> None:
    """Verify no .py mock files exist (besides __init__)."""
    mocks_dir = MCP_ROOT / "mocks"
    if not mocks_dir.exists():
        return

    mock_py_files = [
        f.name
        for f in mocks_dir.glob("*.py")
        if f.stem != "__init__"
    ]
    if mock_py_files:
        error(f"Active mock .py files still exist: {mock_py_files}")

    # Check the HTML doesn't claim active mocks
    html_text = VISUAL_PLAN.read_text()
    if "ACTIVE MOCK" in html_text.upper() or "active mock" in html_text.lower():
        error("Visual plan still references 'active mock' — all mocks are deleted")


def check_no_stale_env_vars() -> None:
    """Verify visual plan doesn't reference removed env vars."""
    html_text = VISUAL_PLAN.read_text()

    stale_vars = ["USE_REAL_LEDGER", "USE_REAL_CODE_LOCATOR"]
    for var in stale_vars:
        if var in html_text:
            error(
                f"Visual plan references removed env var {var} — adapters no longer use it"
            )


def check_adapter_wiring() -> None:
    """Verify adapters don't import from mocks/."""
    for adapter_file in (MCP_ROOT / "adapters").glob("*.py"):
        if adapter_file.stem == "__init__":
            continue
        text = adapter_file.read_text()
        if "from mocks" in text or "import mocks" in text:
            error(
                f"{adapter_file.name} still imports from mocks/ — should use real adapters only"
            )


def main() -> int:
    if not VISUAL_PLAN.exists():
        print(f"FAIL: Visual plan not found at {VISUAL_PLAN}", file=sys.stderr)
        return 1

    print(f"Checking alignment: {VISUAL_PLAN.name} vs implementation")
    print()

    check_tool_names()
    check_handler_files()
    check_ledger_files()
    check_no_active_mocks()
    check_no_stale_env_vars()
    check_adapter_wiring()

    if errors:
        print(f"\n{len(errors)} alignment error(s) found.", file=sys.stderr)
        return 1

    print("All checks passed — visual plan is aligned with implementation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
