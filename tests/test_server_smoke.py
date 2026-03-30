"""Packaging/startup smoke tests for the installable MCP surface."""

from __future__ import annotations

import asyncio

from server import EXPECTED_TOOL_NAMES, run_smoke_test


def test_run_smoke_test_reports_expected_tools():
    result = asyncio.run(run_smoke_test())

    assert result["server_name"] == "bicameral-mcp"
    assert result["server_version"] == "0.1.0"
    assert result["tool_names"] == EXPECTED_TOOL_NAMES
