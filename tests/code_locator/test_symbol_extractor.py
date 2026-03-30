"""Tests for tree-sitter symbol extraction."""

from __future__ import annotations

import os

from code_locator.indexing.symbol_extractor import extract_symbols


def test_extract_python_symbols(tmp_repo):
    models_path = os.path.join(tmp_repo, "sample_app", "models.py")
    symbols = extract_symbols(models_path, tmp_repo)

    names = [s.name for s in symbols]
    assert "User" in names
    assert "Order" in names
    assert "__init__" in names
    assert "get_name" in names
    assert "total" in names

    classes = [s for s in symbols if s.type == "class"]
    functions = [s for s in symbols if s.type == "function"]
    assert len(classes) == 2
    assert len(functions) >= 4  # __init__ x2 + get_name + total

    user_cls = next(s for s in symbols if s.name == "User" and s.type == "class")
    assert user_cls.qualified_name == "User"
    assert user_cls.parent_qualified_name == ""
    assert user_cls.start_line >= 1
    assert user_cls.end_line >= user_cls.start_line

    get_name = next(s for s in symbols if s.name == "get_name")
    assert get_name.qualified_name == "User.get_name"
    assert get_name.parent_qualified_name == "User"


def test_extract_empty_file(tmp_path):
    empty = tmp_path / "empty.py"
    empty.write_text("")
    symbols = extract_symbols(str(empty), str(tmp_path))
    assert symbols == []


def test_unsupported_extension(tmp_path):
    txt = tmp_path / "readme.txt"
    txt.write_text("hello world")
    symbols = extract_symbols(str(txt), str(tmp_path))
    assert symbols == []
