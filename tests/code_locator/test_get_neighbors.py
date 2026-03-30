"""Tests for the get_neighbors tool."""

from __future__ import annotations

from code_locator.tools.get_neighbors import GetNeighborsTool, _EDGE_PRIORITY


def test_neighbors_exist(indexed_db, config):
    tool = GetNeighborsTool(indexed_db, config)

    # The test fixture has classes with methods → contains edges must exist
    found_any = False
    names = indexed_db.get_all_symbol_names()
    for sid, name, qn in names:
        result = tool.execute({"symbol_id": sid})
        if result:
            assert all(hasattr(n, "edge_type") for n in result)
            found_any = True
            break

    assert found_any, "No symbol had any neighbors — graph may be empty"


def test_priority_sort(indexed_db, config):
    tool = GetNeighborsTool(indexed_db, config)

    found_multi = False
    names = indexed_db.get_all_symbol_names()
    for sid, name, qn in names:
        result = tool.execute({"symbol_id": sid})
        if len(result) >= 2:
            priorities = [_EDGE_PRIORITY.get(n.edge_type, 99) for n in result]
            assert priorities == sorted(priorities)
            found_multi = True
            break

    assert found_multi, "No symbol had >= 2 neighbors to test sort order"


def test_max_cap(indexed_db, config):
    config.max_neighbors_per_result = 2
    tool = GetNeighborsTool(indexed_db, config)

    names = indexed_db.get_all_symbol_names()
    for sid, name, qn in names:
        result = tool.execute({"symbol_id": sid})
        assert len(result) <= 2


def test_missing_symbol(indexed_db, config):
    tool = GetNeighborsTool(indexed_db, config)
    result = tool.execute({"symbol_id": 99999})
    assert result == []
