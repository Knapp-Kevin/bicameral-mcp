"""Tests for graph_builder — edge generation (contains, imports, invokes)."""

from __future__ import annotations

import os
import textwrap

from code_locator.indexing.graph_builder import (
    _build_contains_edges,
    _extract_call_names,
    _extract_python_imports,
    build_graph,
)
from code_locator.indexing.index_builder import build_index
from code_locator.indexing.sqlite_store import SymbolDB
from code_locator.indexing.symbol_extractor import _get_parser


def _name_map(db):
    return {qn: sid for sid, n, qn in db.get_all_symbol_names()}


def test_contains_edges(indexed_db):
    """Parent->child edges exist for class methods."""
    edges = _build_contains_edges(indexed_db)
    edge_types = {e[2] for e in edges}
    assert "contains" in edge_types

    names = _name_map(indexed_db)
    # User contains __init__ and get_name
    user_id = names.get("User")
    init_id = names.get("User.__init__")
    get_name_id = names.get("User.get_name")

    if user_id and init_id:
        assert (user_id, init_id, "contains") in edges
    if user_id and get_name_id:
        assert (user_id, get_name_id, "contains") in edges


def test_import_edges(indexed_db, tmp_repo):
    """service.py imports User and Order from models.py → import edges."""
    names = _name_map(indexed_db)

    # After build_index, there should be import edges from service funcs to models symbols
    edges_from_service = []
    for sid, n, qn in indexed_db.get_all_symbol_names():
        row = indexed_db.lookup_by_id(sid)
        if row and "service.py" in row["file_path"] and row["parent_qualified_name"] == "":
            ego = indexed_db.get_ego_graph(sid)
            for e in ego:
                if e["edge_type"] == "imports":
                    edges_from_service.append((qn, e["name"], e["direction"]))

    # service.py top-level funcs should import User and/or Order
    imported_names = {name for _, name, _ in edges_from_service}
    assert "User" in imported_names or "Order" in imported_names


def test_invokes_edges(indexed_db):
    """process_order calls validate_user → invokes edge."""
    names = _name_map(indexed_db)
    process_id = names.get("process_order")

    if process_id:
        ego = indexed_db.get_ego_graph(process_id)
        invoked = [e for e in ego if e["edge_type"] == "invokes" and e["direction"] == "forward"]
        invoked_names = {e["name"] for e in invoked}
        assert "validate_user" in invoked_names


def test_build_graph_returns_count(tmp_repo, tmp_path):
    """build_graph returns total edge count > 0."""
    db_path = str(tmp_path / "graph_test.db")
    build_index(tmp_repo, db_path)
    db = SymbolDB(db_path)
    db.init_db()

    count = build_graph(db, tmp_repo)
    assert count > 0  # should have contains + imports + invokes
    db.close()


def test_build_graph_clears_old_edges(tmp_path, tmp_repo):
    """build_graph clears existing edges before rebuilding."""
    db_path = str(tmp_path / "clear_test.db")
    build_index(tmp_repo, db_path)
    db = SymbolDB(db_path)
    db.init_db()

    count1 = build_graph(db, tmp_repo)
    count2 = build_graph(db, tmp_repo)
    # Same count both times (full rebuild, not additive)
    assert count1 == count2
    db.close()


def test_extract_python_imports():
    """Extract import names from Python source."""
    code = textwrap.dedent("""\
        from os.path import join
        import sys
        from .models import User
        from .utils import format_currency
    """)
    parser = _get_parser("python")
    tree = parser.parse(code.encode())
    names = _extract_python_imports(tree, code.encode())
    assert "join" in names
    assert "sys" in names
    assert "User" in names
    assert "format_currency" in names


def test_extract_python_imports_comma_separated():
    """Known limitation: comma-separated imports only extract the first name.

    `from .models import User, Order` extracts only 'User' because the
    extractor checks prev_sibling for 'import' keyword, which doesn't
    match for subsequent names after a comma.
    """
    code = "from .models import User, Order"
    parser = _get_parser("python")
    tree = parser.parse(code.encode())
    names = _extract_python_imports(tree, code.encode())
    assert "User" in names
    # Known limitation: Order is NOT extracted due to prev_sibling check
    # This documents the behavior for future fixing
    assert len(names) >= 1


def test_extract_call_names():
    """Extract call site names from Python source."""
    code = textwrap.dedent("""\
        def foo():
            bar()
            obj.method()
            nested.deep.call()
    """)
    parser = _get_parser("python")
    tree = parser.parse(code.encode())
    calls = _extract_call_names(tree, code.encode(), "python")

    call_names = [name for _, name in calls]
    assert "bar" in call_names
    assert "method" in call_names
    assert "call" in call_names


def test_self_call_skipped(tmp_path):
    """Recursive self-calls should not create self-referencing invokes edges."""
    root = tmp_path / "selfcall"
    root.mkdir()
    (root / "rec.py").write_text(textwrap.dedent("""\
        def factorial(n):
            if n <= 1:
                return 1
            return n * factorial(n - 1)
    """))

    db_path = str(tmp_path / "selfcall.db")
    build_index(str(root), db_path)
    db = SymbolDB(db_path)
    db.init_db()

    names = {qn: sid for sid, n, qn in db.get_all_symbol_names()}
    fac_id = names.get("factorial")
    if fac_id:
        ego = db.get_ego_graph(fac_id)
        # Should have no forward invokes edge to itself
        self_invokes = [e for e in ego if e["id"] == fac_id and e["edge_type"] == "invokes"]
        assert self_invokes == []
    db.close()
