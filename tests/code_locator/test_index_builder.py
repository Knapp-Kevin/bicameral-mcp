"""Tests for index_builder: build_index + iter_source_files."""

from __future__ import annotations

import os
import time

from code_locator.indexing.index_builder import IndexStats, build_index, iter_source_files


def test_build_index_stats(tmp_repo, tmp_path):
    db_path = str(tmp_path / "idx.db")
    stats = build_index(tmp_repo, db_path)

    assert isinstance(stats, IndexStats)
    assert stats.files_scanned >= 3  # models, service, utils
    assert stats.files_indexed >= 3
    assert stats.symbols_extracted >= 8
    assert stats.edges_created >= 0
    assert stats.duration_seconds >= 0


def test_iter_source_files(tmp_repo):
    files = list(iter_source_files(tmp_repo))
    rel_paths = [r for r, _ in files]

    assert any("models.py" in r for r in rel_paths)
    assert any("service.py" in r for r in rel_paths)
    assert any("utils.py" in r for r in rel_paths)

    # Should not yield __init__.py (empty, but still .py — it should yield)
    # Actually __init__.py is a valid .py file so it IS yielded
    # Check that .git dirs are not traversed
    for rel, abs_path in files:
        assert ".git" not in rel


def test_incremental_reindex(tmp_repo, tmp_path):
    db_path = str(tmp_path / "incr.db")

    stats1 = build_index(tmp_repo, db_path)
    assert stats1.files_indexed >= 3

    # Second build without changes — all files should be skipped
    stats2 = build_index(tmp_repo, db_path)
    assert stats2.files_skipped >= 3
    assert stats2.files_indexed == 0

    # Touch a file with explicit future mtime to avoid filesystem resolution issues
    models_path = os.path.join(tmp_repo, "sample_app", "models.py")
    future_time = time.time() + 2
    os.utime(models_path, (future_time, future_time))

    stats3 = build_index(tmp_repo, db_path)
    assert stats3.files_indexed >= 1
    assert stats3.files_skipped >= 2
