"""Shared fixtures for Code Locator tests."""

from __future__ import annotations

import os
import textwrap

import pytest

from code_locator.config import CodeLocatorConfig
from code_locator.indexing.index_builder import build_index
from code_locator.indexing.sqlite_store import SymbolDB
from code_locator.retrieval.bm25s_client import Bm25sClient


# ── Sample repo files ───────────────────────────────────────────────

_MODELS_PY = textwrap.dedent("""\
    class User:
        def __init__(self, name: str):
            self.name = name

        def get_name(self) -> str:
            return self.name


    class Order:
        def __init__(self, user: "User", amount: float):
            self.user = user
            self.amount = amount

        def total(self) -> float:
            return self.amount
""")

_SERVICE_PY = textwrap.dedent("""\
    from .models import User, Order


    def validate_user(user):
        return user.get_name() is not None


    def process_order(user, order):
        if not validate_user(user):
            raise ValueError("invalid user")
        return order.total()
""")

_UTILS_PY = textwrap.dedent("""\
    def format_currency(amount: float) -> str:
        return f"${amount:.2f}"


    def send_notification(user) -> None:
        print(f"Notification sent to {user}")
""")

_SAMPLE_JS = textwrap.dedent("""\
    class CartService {
        constructor(db) {
            this.db = db;
        }

        addItem(item) {
            return this.db.insert(item);
        }
    }

    function calculateTotal(items) {
        return items.reduce((sum, i) => sum + i.price, 0);
    }

    const formatPrice = (price) => `$${price.toFixed(2)}`;
""")


@pytest.fixture(scope="session")
def tmp_repo(tmp_path_factory):
    """Create a temporary repo with Python and JS sample files."""
    root = tmp_path_factory.mktemp("sample_repo")
    pkg = root / "sample_app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "models.py").write_text(_MODELS_PY)
    (pkg / "service.py").write_text(_SERVICE_PY)
    (pkg / "utils.py").write_text(_UTILS_PY)
    (pkg / "cart.js").write_text(_SAMPLE_JS)
    return str(root)


@pytest.fixture(scope="session")
def indexed_db(tmp_repo, tmp_path_factory):
    """Build a full index on tmp_repo and return SymbolDB."""
    db_dir = tmp_path_factory.mktemp("db")
    db_path = str(db_dir / "test.db")
    build_index(tmp_repo, db_path)
    db = SymbolDB(db_path)
    db.init_db()
    yield db
    db.close()


@pytest.fixture(scope="session")
def bm25_indexed(tmp_repo, tmp_path_factory):
    """Build a BM25 index on tmp_repo and return loaded client."""
    bm25_dir = tmp_path_factory.mktemp("bm25")
    client = Bm25sClient()
    client.index(tmp_repo, str(bm25_dir))
    client.load(str(bm25_dir))
    return client


@pytest.fixture
def config(tmp_path):
    """Return a CodeLocatorConfig with test-appropriate defaults."""
    return CodeLocatorConfig(
        sqlite_db=str(tmp_path / "test.db"),
        fuzzy_threshold=70,
        min_candidate_length=3,
        fuzzy_max_matches_per_candidate=3,
        max_retrieval_results=10,
        max_neighbors_per_result=5,
    )
