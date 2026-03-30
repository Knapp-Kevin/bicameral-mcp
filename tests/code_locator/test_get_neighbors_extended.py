"""Extended get_neighbors tests — missing args, direction sort."""

from __future__ import annotations

from code_locator.tools.get_neighbors import GetNeighborsTool


def test_symbol_id_none_in_args(indexed_db, config):
    """symbol_id absent from args dict → empty result."""
    tool = GetNeighborsTool(indexed_db, config)
    result = tool.execute({})
    assert result == []


def test_direction_sort_backward_first(indexed_db, config):
    """Within same edge type, backward (callers) sorts before forward."""
    tool = GetNeighborsTool(indexed_db, config)

    names = indexed_db.get_all_symbol_names()
    for sid, name, qn in names:
        result = tool.execute({"symbol_id": sid})
        if len(result) >= 2:
            # Group by edge type and check direction order
            by_type = {}
            for n in result:
                by_type.setdefault(n.edge_type, []).append(n.direction)
            for edge_type, directions in by_type.items():
                for i in range(len(directions) - 1):
                    if directions[i] == "forward" and directions[i + 1] == "backward":
                        # backward should come first
                        assert False, f"backward should sort before forward for {edge_type}"
            return  # found a symbol with enough neighbors
