"""Extended SQLite store tests — edge cases and missing coverage."""

from __future__ import annotations

from code_locator.indexing.sqlite_store import SymbolDB, SymbolRecord


def _sym(name="X", qn="X", fp="x.py"):
    return SymbolRecord(
        name=name, qualified_name=qn, type="function",
        file_path=fp, start_line=1, end_line=5,
        signature=f"def {name}():", parent_qualified_name="",
    )


def test_init_db_idempotent(tmp_path):
    """Calling init_db twice doesn't error (CREATE TABLE IF NOT EXISTS)."""
    db = SymbolDB(str(tmp_path / "idem.db"))
    db.init_db()
    db.init_db()  # second call
    assert db.symbol_count() == 0
    db.close()


def test_close_on_unopened(tmp_path):
    """Closing a never-opened DB is a no-op."""
    db = SymbolDB(str(tmp_path / "never_opened.db"))
    db.close()  # should not raise


def test_insert_empty_batch(tmp_path):
    """Inserting an empty list is a no-op."""
    db = SymbolDB(str(tmp_path / "empty.db"))
    db.init_db()
    db.insert_symbols_batch([])
    assert db.symbol_count() == 0
    db.close()


def test_lookup_by_name_missing(tmp_path):
    """Looking up a name that doesn't exist returns []."""
    db = SymbolDB(str(tmp_path / "miss.db"))
    db.init_db()
    assert db.lookup_by_name("Nonexistent") == []
    db.close()


def test_lookup_by_id_missing(tmp_path):
    """Looking up a missing ID returns None."""
    db = SymbolDB(str(tmp_path / "miss_id.db"))
    db.init_db()
    assert db.lookup_by_id(99999) is None
    db.close()


def test_symbol_count_empty(tmp_path):
    """Count on empty DB is 0."""
    db = SymbolDB(str(tmp_path / "empty_count.db"))
    db.init_db()
    assert db.symbol_count() == 0
    db.close()


def test_get_file_mtime_missing(tmp_path):
    """Missing file returns None mtime."""
    db = SymbolDB(str(tmp_path / "mtime.db"))
    db.init_db()
    assert db.get_file_mtime("missing.py") is None
    db.close()


def test_get_all_indexed_files_empty(tmp_path):
    """Empty DB returns empty set."""
    db = SymbolDB(str(tmp_path / "files.db"))
    db.init_db()
    assert db.get_all_indexed_files() == set()
    db.close()


def test_delete_file_symbols_nonexistent(tmp_path):
    """Deleting symbols for a non-existent file is a no-op."""
    db = SymbolDB(str(tmp_path / "noop.db"))
    db.init_db()
    db.insert_symbols_batch([_sym("A", fp="a.py")])
    db.delete_file_symbols("nonexistent.py")
    assert db.symbol_count() == 1
    db.close()


def test_delete_file_record(tmp_path):
    """delete_file_record removes both the indexed_files entry and symbols."""
    db = SymbolDB(str(tmp_path / "del_rec.db"))
    db.init_db()
    db.insert_symbols_batch([_sym("A", fp="a.py")])
    db.upsert_file_record("a.py", 1000.0, 1)

    db.delete_file_record("a.py")
    assert db.get_file_mtime("a.py") is None
    assert db.lookup_by_file("a.py") == []
    db.close()


def test_get_neighbors_method(tmp_path):
    """get_neighbors (not get_ego_graph) returns connected symbols."""
    db = SymbolDB(str(tmp_path / "nbrs.db"))
    db.init_db()
    db.insert_symbols_batch([_sym("A", fp="a.py"), _sym("B", "B", fp="b.py")])

    names = db.get_all_symbol_names()
    id_map = {n: sid for sid, n, qn in names}
    db.insert_edges_batch([(id_map["A"], id_map["B"], "imports")])

    neighbors = db.get_neighbors(id_map["A"])
    assert len(neighbors) == 1
    assert neighbors[0]["name"] == "B"
    db.close()


def test_insert_edges_empty_batch(tmp_path):
    """Inserting an empty edge list is a no-op."""
    db = SymbolDB(str(tmp_path / "empty_edges.db"))
    db.init_db()
    db.insert_edges_batch([])
    db.close()


def test_ego_graph_no_edges(tmp_path):
    """Symbol with no edges → empty ego graph."""
    db = SymbolDB(str(tmp_path / "no_edges.db"))
    db.init_db()
    db.insert_symbols_batch([_sym("Lonely")])
    names = db.get_all_symbol_names()
    sid = names[0][0]
    assert db.get_ego_graph(sid) == []
    db.close()
