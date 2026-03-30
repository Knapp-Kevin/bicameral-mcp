"""Tests for SymbolDB CRUD operations."""

from __future__ import annotations

from code_locator.indexing.sqlite_store import SymbolDB, SymbolRecord


def _make_symbol(name="Foo", qn="Foo", stype="class", fp="a.py", start=1, end=5):
    return SymbolRecord(
        name=name, qualified_name=qn, type=stype,
        file_path=fp, start_line=start, end_line=end,
        signature=f"class {name}:", parent_qualified_name="",
    )


def test_insert_and_lookup(tmp_path):
    db = SymbolDB(str(tmp_path / "test.db"))
    db.init_db()

    db.insert_symbols_batch([_make_symbol("Foo"), _make_symbol("Bar", "Bar", "function")])
    assert db.symbol_count() == 2

    rows = db.lookup_by_name("Foo")
    assert len(rows) == 1
    assert rows[0]["qualified_name"] == "Foo"

    rows = db.lookup_by_file("a.py")
    assert len(rows) == 2

    # lookup_by_id
    row = db.lookup_by_id(rows[0]["id"])
    assert row is not None

    db.close()


def test_upsert_file_record(tmp_path):
    db = SymbolDB(str(tmp_path / "test.db"))
    db.init_db()

    db.upsert_file_record("x.py", 1000.0, 3)
    assert db.get_file_mtime("x.py") == 1000.0

    db.upsert_file_record("x.py", 2000.0, 5)
    assert db.get_file_mtime("x.py") == 2000.0

    assert "x.py" in db.get_all_indexed_files()
    db.close()


def test_delete_file_symbols(tmp_path):
    db = SymbolDB(str(tmp_path / "test.db"))
    db.init_db()

    db.insert_symbols_batch([_make_symbol("A", fp="a.py"), _make_symbol("B", fp="b.py")])
    db.delete_file_symbols("a.py")

    assert db.lookup_by_file("a.py") == []
    assert len(db.lookup_by_file("b.py")) == 1
    db.close()


def test_edges_and_ego_graph(tmp_path):
    db = SymbolDB(str(tmp_path / "test.db"))
    db.init_db()

    db.insert_symbols_batch([
        _make_symbol("A", "A", "class", "a.py", 1, 5),
        _make_symbol("B", "B", "function", "b.py", 1, 3),
        _make_symbol("C", "C", "function", "c.py", 1, 3),
    ])

    names = db.get_all_symbol_names()
    id_map = {n: sid for sid, n, qn in names}

    db.insert_edges_batch([
        (id_map["A"], id_map["B"], "imports"),
        (id_map["A"], id_map["C"], "invokes"),
    ])

    ego = db.get_ego_graph(id_map["A"])
    assert len(ego) == 2

    neighbor_names = {e["name"] for e in ego}
    assert "B" in neighbor_names
    assert "C" in neighbor_names

    # Check direction: A is source → forward
    for e in ego:
        assert e["direction"] == "forward"

    # From B's perspective, A→B is backward
    ego_b = db.get_ego_graph(id_map["B"])
    assert len(ego_b) == 1
    assert ego_b[0]["direction"] == "backward"

    db.close()


def test_delete_all_edges(tmp_path):
    db = SymbolDB(str(tmp_path / "test.db"))
    db.init_db()

    db.insert_symbols_batch([_make_symbol("X"), _make_symbol("Y", "Y")])
    names = db.get_all_symbol_names()
    id_map = {n: sid for sid, n, qn in names}
    db.insert_edges_batch([(id_map["X"], id_map["Y"], "imports")])

    db.delete_all_edges()
    ego = db.get_ego_graph(id_map["X"])
    assert ego == []
    db.close()


def test_get_all_symbol_names(tmp_path):
    db = SymbolDB(str(tmp_path / "test.db"))
    db.init_db()
    db.insert_symbols_batch([_make_symbol("Alpha", "Alpha"), _make_symbol("Beta", "mod.Beta")])

    result = db.get_all_symbol_names()
    assert len(result) == 2
    assert all(len(t) == 3 for t in result)
    names = {t[1] for t in result}
    assert names == {"Alpha", "Beta"}
    db.close()
