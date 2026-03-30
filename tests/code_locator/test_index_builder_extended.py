"""Extended index_builder tests — file deletion, skip dirs."""

from __future__ import annotations

import os

from code_locator.indexing.index_builder import build_index, iter_source_files


def test_file_deletion_detected(tmp_path):
    """Removing a file between builds → files_deleted incremented."""
    root = tmp_path / "del_repo"
    root.mkdir()
    (root / "keep.py").write_text("def keep(): pass")
    (root / "remove.py").write_text("def remove(): pass")

    db_path = str(tmp_path / "del.db")
    stats1 = build_index(str(root), db_path)
    assert stats1.files_indexed >= 2

    # Remove one file
    (root / "remove.py").unlink()

    stats2 = build_index(str(root), db_path)
    assert stats2.files_deleted >= 1


def test_skip_dirs_filtering(tmp_path):
    """Directories in SKIP_DIRS are not traversed."""
    root = tmp_path / "skip_repo"
    root.mkdir()
    (root / "good.py").write_text("def good(): pass")

    # Create a node_modules dir with a .py file — should be skipped
    nm = root / "node_modules"
    nm.mkdir()
    (nm / "bad.py").write_text("def bad(): pass")

    # Create a .venv dir — should be skipped
    venv = root / ".venv"
    venv.mkdir()
    (venv / "also_bad.py").write_text("def also_bad(): pass")

    files = list(iter_source_files(str(root)))
    rel_paths = [r for r, _ in files]

    assert any("good.py" in r for r in rel_paths)
    assert not any("bad.py" in r for r in rel_paths)
    assert not any("also_bad.py" in r for r in rel_paths)


def test_symlink_skipped(tmp_path):
    """Symlinked files are skipped by iter_source_files."""
    root = tmp_path / "link_repo"
    root.mkdir()
    real = root / "real.py"
    real.write_text("def real(): pass")
    link = root / "link.py"
    link.symlink_to(real)

    files = list(iter_source_files(str(root)))
    rel_paths = [r for r, _ in files]

    assert any("real.py" in r for r in rel_paths)
    assert not any("link.py" in r for r in rel_paths)


def test_build_index_edges_nonzero(tmp_repo, tmp_path):
    """build_index on tmp_repo produces edges."""
    db_path = str(tmp_path / "edges.db")
    stats = build_index(tmp_repo, db_path)
    assert stats.edges_created > 0
