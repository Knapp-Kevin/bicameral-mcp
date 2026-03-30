"""Extended config tests — YAML loading, float env override, missing path."""

from __future__ import annotations

import os
from unittest.mock import patch

import yaml

from code_locator.config import CodeLocatorConfig, load_config


def test_load_config_from_yaml(tmp_path):
    """Load config from a YAML file with code_locator key."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({
        "code_locator": {
            "fuzzy_threshold": 85,
            "rrf_k": 30,
        }
    }))

    cfg = load_config(str(config_file))
    assert cfg.fuzzy_threshold == 85
    assert cfg.rrf_k == 30


def test_load_config_yaml_root_level(tmp_path):
    """YAML without code_locator key -> uses root as config."""
    config_file = tmp_path / "flat.yaml"
    config_file.write_text(yaml.dump({
        "fuzzy_threshold": 75,
        "bm25_backend": "zoekt",
    }))

    cfg = load_config(str(config_file))
    assert cfg.fuzzy_threshold == 75
    assert cfg.bm25_backend == "zoekt"


def test_load_config_nonexistent_path():
    """Nonexistent config path -> uses defaults gracefully."""
    cfg = load_config("/nonexistent/config.yaml")
    assert cfg.rrf_k == 60  # default
    assert cfg.fuzzy_threshold == 80  # default


def test_load_config_none_path():
    """config_path=None -> uses defaults."""
    cfg = load_config(None)
    assert cfg.rrf_k == 60


def test_env_override_string():
    """String env override."""
    with patch.dict(os.environ, {"CODE_LOCATOR_BM25_BACKEND": "zoekt"}):
        cfg = load_config()
    assert cfg.bm25_backend == "zoekt"


def test_remaining_defaults():
    """Assert all default values not covered by test_default_config."""
    cfg = CodeLocatorConfig()
    assert cfg.graph_hop_depth == 1
    assert cfg.fuzzy_scorer == "WRatio"
    assert cfg.min_candidate_length == 2


def test_vector_defaults():
    """Vector search config defaults."""
    cfg = CodeLocatorConfig()
    assert cfg.vector_enabled is False
    assert cfg.vector_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert "vector" in cfg.channel_weights
    assert cfg.channel_weights["vector"] == 0.6


def test_vector_env_override_bool():
    """Boolean env override for vector_enabled."""
    with patch.dict(os.environ, {"CODE_LOCATOR_VECTOR_ENABLED": "true"}):
        cfg = load_config()
    assert cfg.vector_enabled is True

    with patch.dict(os.environ, {"CODE_LOCATOR_VECTOR_ENABLED": "false"}):
        cfg = load_config()
    assert cfg.vector_enabled is False

    with patch.dict(os.environ, {"CODE_LOCATOR_VECTOR_ENABLED": "1"}):
        cfg = load_config()
    assert cfg.vector_enabled is True


def test_cocoindex_backend_defaults():
    """CocoIndex backend config defaults."""
    cfg = CodeLocatorConfig()
    assert cfg.indexing_backend == "legacy"
    assert cfg.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert cfg.chunk_size == 512
    assert cfg.chunk_overlap == 50


def test_cocoindex_backend_env_override():
    """Env override for indexing_backend."""
    with patch.dict(os.environ, {"CODE_LOCATOR_INDEXING_BACKEND": "cocoindex"}):
        cfg = load_config()
    assert cfg.indexing_backend == "cocoindex"


def test_cocoindex_single_db():
    """CocoIndex backend uses sqlite_db (single DB, no separate cocoindex_db_path)."""
    cfg = CodeLocatorConfig()
    assert not hasattr(cfg, "cocoindex_db_path")
