"""Tests for the SqliteVecClient (Option A direct sqlite-vec search)."""

from __future__ import annotations

from code_locator.retrieval.sqlite_vec_client import SqliteVecClient, _is_test_file


def test_is_test_file():
    """Test file demotion detection."""
    assert _is_test_file("test/Router.js")
    assert _is_test_file("tests/test_app.py")
    assert _is_test_file("spec/helpers.rb")
    assert _is_test_file("__tests__/App.test.tsx")
    assert _is_test_file("src/__tests__/utils.test.js")
    assert not _is_test_file("src/app.py")
    assert not _is_test_file("lib/router.js")


def test_search_returns_empty_when_not_ready():
    """Search returns empty list when client not initialized."""
    client = SqliteVecClient("/nonexistent/db.sqlite", "all-MiniLM-L6-v2")
    assert client.search("test query") == []
    assert client.is_ready is False


def test_load_nonexistent_db():
    """Loading a nonexistent DB marks client as not ready."""
    client = SqliteVecClient("/nonexistent/db.sqlite", "all-MiniLM-L6-v2")
    client.load("/nonexistent/db.sqlite")
    assert client.is_ready is False


def test_load_existing_db(tmp_path):
    """Loading an existing DB file marks client as ready."""
    db_file = tmp_path / "test.db"
    db_file.touch()

    client = SqliteVecClient(str(db_file), "all-MiniLM-L6-v2")
    client.load(str(db_file))
    assert client.is_ready is True


def test_search_graceful_failure(tmp_path):
    """Search on a DB without the vec0 table should return empty list."""
    import sqlite3

    db_file = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE dummy (id INTEGER)")
    conn.close()

    client = SqliteVecClient(str(db_file), "all-MiniLM-L6-v2")
    client.load(str(db_file))
    assert client.is_ready is True

    # Search should fail gracefully (no vec0 table)
    results = client.search("test query")
    assert results == []
