"""Tests for CodeLocatorConfig loading and env overrides."""

from __future__ import annotations

import os
from unittest.mock import patch

from code_locator.config import CodeLocatorConfig, load_config


def test_default_config():
    cfg = CodeLocatorConfig()
    assert cfg.rrf_k == 60
    assert cfg.fuzzy_threshold == 80
    assert cfg.bm25_backend == "bm25s"
    assert cfg.channel_weights == {"bm25": 1.0, "graph": 1.2, "vector": 0.6}


def test_env_override():
    with patch.dict(os.environ, {"CODE_LOCATOR_FUZZY_THRESHOLD": "90"}):
        cfg = load_config()
    assert cfg.fuzzy_threshold == 90


def test_resolve_paths():
    cfg = CodeLocatorConfig(
        sqlite_db="~/test.db",
    )
    cfg.resolve_paths()

    home = os.path.expanduser("~")
    assert cfg.sqlite_db == os.path.join(home, "test.db")
