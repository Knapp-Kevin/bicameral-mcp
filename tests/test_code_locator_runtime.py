"""Tests for pilot/mcp-owned Code Locator runtime helpers."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

from code_locator_runtime import ensure_index_matches_repo, ensure_runtime_env, record_index_state


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_record_index_state_persists_git_metadata(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@bicameral.ai")
    _git(repo, "config", "user.name", "Code Locator Test")
    (repo / "service.py").write_text("def ping():\n    return 'pong'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")

    db_path = str(tmp_path / "code-graph.db")
    record_index_state(db_path, str(repo))

    conn = sqlite3.connect(db_path)
    rows = dict(conn.execute("SELECT key, value FROM index_meta").fetchall())
    conn.close()

    assert rows["repo_path"] == str(repo.resolve())
    assert rows["head_commit"]
    assert rows["branch"] in {"main", "master"}


def test_ensure_runtime_env_defaults_to_repo_level_bicameral(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.delenv("CODE_LOCATOR_SQLITE_DB", raising=False)
    monkeypatch.setenv("REPO_PATH", str(repo))

    ensure_runtime_env()

    assert os.environ["CODE_LOCATOR_SQLITE_DB"] == str(repo / ".bicameral" / "code-graph.db")


def test_ensure_index_matches_repo_rebuilds_on_head_change(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@bicameral.ai")
    _git(repo, "config", "user.name", "Code Locator Test")
    target = repo / "service.py"
    target.write_text("def first():\n    return 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "v1")

    db_path = str(tmp_path / "code-graph.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE symbols (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO symbols (name) VALUES ('first')")
    conn.commit()
    conn.close()
    record_index_state(db_path, str(repo))

    class Config:
        sqlite_db = db_path
        indexing_backend = "legacy"
        embedding_model = ""
        chunk_size = 512
        chunk_overlap = 50
    config = Config()

    target.write_text("def second():\n    return 2\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "v2")

    with patch("code_locator_runtime.rebuild_index") as rebuild:
        refreshed = ensure_index_matches_repo(str(repo), config)

    assert refreshed is True
    rebuild.assert_called_once_with(str(repo), config, force=True)
