"""Extended symbol extractor tests — JS extraction, async, edge cases."""

from __future__ import annotations

import os
import textwrap

from code_locator.indexing.symbol_extractor import extract_symbols


def test_extract_javascript_symbols(tmp_repo):
    """Extract class, method, function, arrow fn from JS file."""
    js_path = os.path.join(tmp_repo, "sample_app", "cart.js")
    symbols = extract_symbols(js_path, tmp_repo)

    names = [s.name for s in symbols]
    assert "CartService" in names
    assert "calculateTotal" in names
    assert "formatPrice" in names

    classes = [s for s in symbols if s.type == "class"]
    functions = [s for s in symbols if s.type == "function"]
    assert len(classes) >= 1  # CartService
    assert len(functions) >= 2  # calculateTotal, formatPrice, + methods

    cart = next(s for s in symbols if s.name == "CartService")
    assert cart.type == "class"
    assert cart.qualified_name == "CartService"


def test_extract_async_function(tmp_path):
    """Async function definitions are extracted."""
    code = textwrap.dedent("""\
        async def fetch_data(url):
            pass
    """)
    f = tmp_path / "async_mod.py"
    f.write_text(code)
    symbols = extract_symbols(str(f), str(tmp_path))

    names = [s.name for s in symbols]
    assert "fetch_data" in names


def test_extract_nested_classes(tmp_path):
    """Nested class inside a class."""
    code = textwrap.dedent("""\
        class Outer:
            class Inner:
                def method(self):
                    pass
    """)
    f = tmp_path / "nested.py"
    f.write_text(code)
    symbols = extract_symbols(str(f), str(tmp_path))

    qns = [s.qualified_name for s in symbols]
    assert "Outer" in qns
    assert "Outer.Inner" in qns
    assert "Outer.Inner.method" in qns

    inner = next(s for s in symbols if s.name == "Inner")
    assert inner.parent_qualified_name == "Outer"


def test_extract_file_with_syntax_error(tmp_path):
    """File with syntax error should return partial or empty results without crashing."""
    code = "def broken(:\n    pass\n"
    f = tmp_path / "broken.py"
    f.write_text(code)
    # Should not raise — tree-sitter handles partial parses
    symbols = extract_symbols(str(f), str(tmp_path))
    # May or may not extract symbols, but should not crash
    assert isinstance(symbols, list)


def test_extract_multiple_top_level_functions(tmp_path):
    """Multiple top-level functions each have empty parent_qualified_name."""
    code = textwrap.dedent("""\
        def alpha():
            pass

        def beta():
            pass

        def gamma():
            pass
    """)
    f = tmp_path / "multi.py"
    f.write_text(code)
    symbols = extract_symbols(str(f), str(tmp_path))

    for s in symbols:
        assert s.parent_qualified_name == ""
    assert len(symbols) == 3


def test_extract_preserves_line_numbers(tmp_path):
    """Line numbers are accurate and 1-indexed."""
    code = textwrap.dedent("""\
        # comment line 1

        class Foo:
            def bar(self):
                pass
    """)
    f = tmp_path / "lines.py"
    f.write_text(code)
    symbols = extract_symbols(str(f), str(tmp_path))

    foo = next(s for s in symbols if s.name == "Foo")
    assert foo.start_line == 3  # 1-indexed
    bar = next(s for s in symbols if s.name == "bar")
    assert bar.start_line == 4
