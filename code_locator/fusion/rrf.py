"""Weighted Reciprocal Rank Fusion for multi-channel retrieval."""

from __future__ import annotations

from collections import defaultdict

from ..models import RetrievalResult


def rrf_fuse(
    ranked_lists: list[list[RetrievalResult]],
    channel_weights: dict[str, float] | None = None,
    k: int = 60,
    max_results: int = 20,
) -> list[RetrievalResult]:
    """Fuse multiple ranked lists using weighted Reciprocal Rank Fusion.

    Args:
        ranked_lists: One list per retrieval channel.
        channel_weights: Weight per channel method. Default: bm25=1.0, graph=1.2.
        k: RRF smoothing parameter (higher = more uniform).
        max_results: Maximum results to return.

    Returns:
        Unified ranked list, deduplicated by (file_path, line_number).
    """
    if channel_weights is None:
        channel_weights = {"bm25": 1.0, "graph": 1.2}

    # Track scores and contributing channels per result key
    scores: dict[tuple[str, int], float] = defaultdict(float)
    best_result: dict[tuple[str, int], RetrievalResult] = {}
    channels_per_key: dict[tuple[str, int], list[str]] = defaultdict(list)

    for ranked_list in ranked_lists:
        for rank, result in enumerate(ranked_list):
            key = (result.file_path, result.line_number)
            weight = channel_weights.get(result.method, 1.0)
            scores[key] += weight / (k + rank + 1)
            channels_per_key[key].append(result.method)

            # Keep the result with the most detail
            if key not in best_result or result.snippet:
                best_result[key] = result

    # Sort by fused score, build output
    sorted_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    output: list[RetrievalResult] = []
    for key in sorted_keys[:max_results]:
        result = best_result[key]
        output.append(
            RetrievalResult(
                file_path=result.file_path,
                line_number=result.line_number,
                snippet=result.snippet,
                score=scores[key],
                method="+".join(sorted(set(channels_per_key[key]))),
                repo=result.repo,
                symbol_name=result.symbol_name,
            )
        )

    return output
