"""get_neighbors tool — 1-hop structural graph traversal."""

from __future__ import annotations

from ..config import CodeLocatorConfig
from ..indexing.sqlite_store import SymbolDB
from ..models import NeighborInfo

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_neighbors",
        "description": (
            "Explore structural neighbors of a symbol via 1-hop graph traversal. "
            "Returns callers, callees, imports, and inheritance relationships. "
            "Use this to understand context around a promising symbol."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol_id": {
                    "type": "integer",
                    "description": "Symbol ID from validate_symbols results",
                },
            },
            "required": ["symbol_id"],
        },
    },
}

# Priority order for neighbor types (higher priority = kept first when capping)
_EDGE_PRIORITY = {
    "invokes": 0,  # callers/callees most useful
    "imports": 1,
    "inherits": 2,
    "contains": 3,
}


class GetNeighborsTool:
    """1-hop graph traversal around a symbol."""

    def __init__(self, db: SymbolDB, config: CodeLocatorConfig) -> None:
        self.db = db
        self.max_neighbors = config.max_neighbors_per_result

    def execute(self, args: dict) -> list[NeighborInfo]:
        symbol_id = args.get("symbol_id")
        if symbol_id is None:
            return []

        raw = self.db.get_ego_graph(symbol_id)

        # Convert to NeighborInfo and sort by priority
        neighbors = [
            NeighborInfo(
                symbol_name=n.get("qualified_name", n.get("name", "")),
                file_path=n["file_path"],
                line_number=n.get("start_line", 0),
                edge_type=n.get("edge_type", "unknown"),
                direction=n.get("direction", "forward"),
            )
            for n in raw
        ]

        # Sort by edge type priority, then by direction (backward = callers first)
        neighbors.sort(
            key=lambda n: (
                _EDGE_PRIORITY.get(n.edge_type, 99),
                0 if n.direction == "backward" else 1,
            )
        )

        return neighbors[: self.max_neighbors]
