"""Tests for the CocoIndex pipeline module (Option A+).

Tests pure-Python helpers directly. Tests that require the CocoIndex runtime
(flow definition, Postgres) are skipped when cocoindex is not importable.
"""

from __future__ import annotations

import pytest

from code_locator.indexing.cocoindex_pipeline import (
    CodeChunk,
    PipelineStats,
    SymbolRow,
    _ext_to_language,
    _stable_id,
    _INCLUDE_PATTERNS,
)


def test_ext_to_language():
    """File extension to language mapping."""
    assert _ext_to_language("app.py") == "python"
    assert _ext_to_language("index.ts") == "typescript"
    assert _ext_to_language("Main.java") == "java"
    assert _ext_to_language("main.go") == "go"
    assert _ext_to_language("lib.rs") == "rust"
    assert _ext_to_language("README.md") == ""
    assert _ext_to_language("Makefile") == ""


def test_include_patterns_cover_all_extensions():
    """Include patterns should cover all supported extensions."""
    from code_locator.indexing.symbol_extractor import EXTENSION_LANGUAGE

    for ext in EXTENSION_LANGUAGE:
        pattern = f"**/*{ext}"
        assert pattern in _INCLUDE_PATTERNS, f"Missing pattern for {ext}"


def test_code_chunk_schema():
    """CodeChunk dataclass has expected fields."""
    chunk = CodeChunk(
        id=1,
        file_path="src/app.py",
        language="python",
        content="def foo(): pass",
        start_line=1,
        end_line=1,
        embedding=[0.0] * 384,
    )
    assert chunk.file_path == "src/app.py"
    assert chunk.language == "python"
    assert chunk.start_line == 1


def test_symbol_row_schema():
    """SymbolRow dataclass has expected fields matching SymbolRecord."""
    row = SymbolRow(
        id=1,
        name="foo",
        qualified_name="module.foo",
        type="function",
        file_path="src/app.py",
        start_line=10,
        end_line=15,
        signature="def foo(x: int) -> str:",
        parent_qualified_name="",
    )
    assert row.name == "foo"
    assert row.qualified_name == "module.foo"
    assert row.type == "function"


def test_pipeline_stats():
    """PipelineStats dataclass defaults."""
    stats = PipelineStats()
    assert stats.duration_seconds == 0.0
    assert stats.chunks_created == 0
    assert stats.symbols_extracted == 0


def test_stable_id_deterministic():
    """Same input always produces the same ID."""
    id1 = _stable_id("chunk:src/app.py:10:20")
    id2 = _stable_id("chunk:src/app.py:10:20")
    assert id1 == id2
    assert isinstance(id1, int)
    assert id1 > 0


def test_stable_id_different_inputs():
    """Different inputs produce different IDs."""
    id1 = _stable_id("chunk:src/app.py:10:20")
    id2 = _stable_id("chunk:src/app.py:10:21")
    assert id1 != id2


def test_stable_id_fits_sqlite_integer():
    """Stable IDs must fit in a 63-bit positive integer."""
    for key in ["a", "z" * 1000, "chunk:very/long/path.py:99999:99999"]:
        sid = _stable_id(key)
        assert 0 < sid < 2**63


def test_sync_symbols_in_db(tmp_path):
    """sync_symbols_in_db copies from cocoindex_symbols -> legacy symbols table."""
    import sqlite3
    from code_locator.indexing.cocoindex_pipeline import sync_symbols_in_db

    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)

    # Create the cocoindex_symbols table with test data
    conn.execute("""
        CREATE TABLE cocoindex_symbols (
            id INTEGER PRIMARY KEY, name TEXT, qualified_name TEXT, type TEXT,
            file_path TEXT, start_line INTEGER, end_line INTEGER,
            signature TEXT, parent_qualified_name TEXT
        )
    """)
    conn.execute("""
        INSERT INTO cocoindex_symbols VALUES
        (1, 'foo', 'mod.foo', 'function', 'src/mod.py', 10, 15, 'def foo():', ''),
        (2, 'Bar', 'Bar', 'class', 'src/mod.py', 1, 20, 'class Bar:', '')
    """)
    conn.commit()
    conn.close()

    count = sync_symbols_in_db(db_path)
    assert count == 2

    # Verify legacy symbols table was populated
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT name, qualified_name FROM symbols ORDER BY name").fetchall()
    assert rows == [("Bar", "Bar"), ("foo", "mod.foo")]

    # Verify indexed_files was populated
    files = conn.execute("SELECT file_path, symbol_count FROM indexed_files").fetchall()
    assert files == [("src/mod.py", 2)]
    conn.close()


def test_extract_symbols_from_content_integration():
    """extract_symbols_from_content works correctly (the refactored API)."""
    from code_locator.indexing.symbol_extractor import extract_symbols_from_content

    python_code = '''
class MyClass:
    def my_method(self):
        pass

def standalone_func():
    pass
'''
    symbols = extract_symbols_from_content(python_code, "python", "test.py")
    names = [s.name for s in symbols]
    assert "MyClass" in names
    assert "my_method" in names
    assert "standalone_func" in names

    cls = next(s for s in symbols if s.name == "MyClass")
    assert cls.type == "class"
    assert cls.parent_qualified_name == ""

    method = next(s for s in symbols if s.name == "my_method")
    assert method.type == "function"
    assert method.parent_qualified_name == "MyClass"


def _has_cocoindex_flow_api() -> bool:
    """Check if cocoindex has the v0.3 flow API (op, flow_def, sources, etc.).

    The pipeline code in cocoindex_pipeline.py targets cocoindex v0.3.x which
    exposes @cocoindex.op.function(), @cocoindex.flow_def(), cocoindex.sources,
    cocoindex.functions, and cocoindex.storages. The v1.0 alpha (>=1.0.0a38)
    shipped a completely different API surface (App, Environment, Runner, mount)
    that breaks all of these. requirements.txt is now pinned to <1.0.0 to avoid
    this, but the guard remains so tests degrade gracefully if the wrong version
    is installed.
    """
    try:
        import cocoindex
        return hasattr(cocoindex, "op") and hasattr(cocoindex, "flow_def")
    except ImportError:
        return False


@pytest.mark.skipif(
    not _has_cocoindex_flow_api(),
    reason="cocoindex v0.3 flow API not available — pipeline requires cocoindex<1.0.0 (op, flow_def, sources)",
)
def test_define_flow_creates_flow():
    """_define_flow returns a valid flow definition (requires cocoindex v0.3 flow API)."""
    from code_locator.indexing.cocoindex_pipeline import _define_flow

    flow_def, transform = _define_flow(
        repo_path="/tmp/test_repo",
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        chunk_size=512,
        chunk_overlap=50,
    )
    assert flow_def is not None
    assert transform is not None
