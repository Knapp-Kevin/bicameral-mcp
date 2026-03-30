"""BM25 search protocol — swappable backend for text retrieval."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import RetrievalResult


class BM25Search(ABC):
    """Abstract protocol for BM25 text search backends."""

    @abstractmethod
    def index(self, repo_path: str, output_dir: str) -> None:
        """Build the BM25 index for a repository."""
        ...

    @abstractmethod
    def load(self, index_dir: str) -> None:
        """Load a previously built index."""
        ...

    @abstractmethod
    def search(self, query: str, num_results: int = 20) -> list[RetrievalResult]:
        """Search the index and return ranked results."""
        ...
