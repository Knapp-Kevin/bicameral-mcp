"""search_code tool — BM25 text search + graph traversal + vector search with RRF fusion."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..config import CodeLocatorConfig
from ..fusion.rrf import rrf_fuse
from ..indexing.sqlite_store import SymbolDB
from ..models import RetrievalResult
from ..retrieval.bm25_protocol import BM25Search


@runtime_checkable
class VectorSearch(Protocol):
    """Protocol for vector search clients (VectorSearchClient or SqliteVecClient)."""

    def search(self, query: str, num_results: int = 20) -> list[RetrievalResult]: ...

    @property
    def is_ready(self) -> bool: ...

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_code",
        "description": (
            "Search the codebase using BM25 text search and structural graph traversal. "
            "Returns ranked code locations. Always provide a query string. "
            "Optionally provide symbol_ids (from validate_symbols) to activate "
            "graph-based retrieval for better results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text search query (e.g. 'checkout rate limit middleware')",
                },
                "symbol_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Symbol IDs from validate_symbols to use as graph traversal seeds (optional)",
                },
            },
            "required": ["query"],
        },
    },
}


class SearchCodeTool:
    """Searches codebase via BM25 + graph, fused with RRF."""

    def __init__(
        self,
        bm25_client: BM25Search,
        db: SymbolDB,
        config: CodeLocatorConfig,
        vector_client: VectorSearch | None = None,
    ) -> None:
        self.bm25 = bm25_client
        self.db = db
        self.config = config
        self.vector = vector_client

    def execute(self, args: dict) -> list[RetrievalResult]:
        query = args.get("query", "")
        symbol_ids: list[int] | None = args.get("symbol_ids")

        if not query:
            return []

        # Channel 1: BM25 always runs
        bm25_results = self.bm25.search(query, num_results=self.config.max_retrieval_results)

        # Channel 2: Graph — only if symbol_ids provided
        graph_results: list[RetrievalResult] = []
        if symbol_ids:
            graph_results = self._graph_retrieve(symbol_ids)

        # Channel 3: Vector — only if vector client available
        vector_results: list[RetrievalResult] = []
        if self.vector:
            vector_results = self.vector.search(query, num_results=self.config.max_retrieval_results)
            vector_results = self._enrich_vector_results(vector_results)

        # Fuse all non-empty channels
        channels = [ch for ch in [bm25_results, graph_results, vector_results] if ch]
        if len(channels) > 1:
            return rrf_fuse(
                channels,
                channel_weights=self.config.channel_weights,
                k=self.config.rrf_k,
                max_results=self.config.max_retrieval_results,
            )
        elif channels:
            return channels[0][: self.config.max_retrieval_results]
        return []

    def _enrich_vector_results(self, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Enrich vector results with symbol names from the symbol index.

        Vector chunks have file_path + line_number but no symbol_name.
        Look up which symbol contains each chunk's line range.
        """
        enriched: list[RetrievalResult] = []
        for r in results:
            symbol_name = ""
            if r.file_path and r.line_number > 0:
                symbols = self.db.lookup_by_file(r.file_path)
                # Find the tightest symbol that contains this line
                best_match = None
                best_span = float("inf")
                for sym in symbols:
                    start = sym["start_line"]
                    end = sym["end_line"]
                    if start <= r.line_number <= end:
                        span = end - start
                        if span < best_span:
                            best_span = span
                            best_match = sym
                if best_match:
                    symbol_name = best_match["qualified_name"]
            enriched.append(
                RetrievalResult(
                    file_path=r.file_path,
                    line_number=r.line_number,
                    snippet=r.snippet,
                    score=r.score,
                    method=r.method,
                    symbol_name=symbol_name,
                )
            )
        return enriched

    def _graph_retrieve(self, symbol_ids: list[int]) -> list[RetrievalResult]:
        """Retrieve structural neighbors for each symbol seed."""
        results: list[RetrievalResult] = []
        seen: set[tuple[str, int]] = set()

        for sid in symbol_ids:
            # Include the seed symbol itself (ranked higher)
            row = self.db.lookup_by_id(sid)
            if row:
                key = (row["file_path"], row["start_line"])
                if key not in seen:
                    seen.add(key)
                    results.append(
                        RetrievalResult(
                            file_path=row["file_path"],
                            line_number=row["start_line"],
                            snippet="",
                            score=1.5,
                            method="graph",
                            symbol_name=row["qualified_name"],
                        )
                    )

            # 1-hop neighbors
            for n in self.db.get_ego_graph(sid):
                key = (n["file_path"], n.get("start_line", 0))
                if key in seen:
                    continue
                seen.add(key)
                results.append(
                    RetrievalResult(
                        file_path=n["file_path"],
                        line_number=n.get("start_line", 0),
                        snippet="",
                        score=1.0,
                        method="graph",
                        symbol_name=n.get("qualified_name", n.get("name", "")),
                    )
                )

        return results
