from __future__ import annotations

from .scoping import _context_source_weight

# 从 graph_runtime.py 迁移，原函数名：_compress_memory_context_results


def _compress_memory_context_results(
    results,
    *,
    preferred_scopes: tuple[str, ...],
    limit: int,
    per_scope_limit: int,
):
    preferred_weight = {
        scope: len(preferred_scopes) - index
        for index, scope in enumerate(preferred_scopes)
    }
    by_scope_count: dict[str, int] = {}
    seen: set[tuple[str, str, str]] = set()
    ranked = sorted(
        results,
        key=lambda result: (
            -preferred_weight.get(result.source_scope, 0),
            -_context_source_weight(result.source_scope),
            -result.score,
            result.relative_path,
            result.heading or "",
        ),
    )
    compressed = []
    for result in ranked:
        key = (
            result.relative_path,
            result.heading or "",
            " ".join(result.snippet.split()).casefold(),
        )
        if key in seen:
            continue
        scope_count = by_scope_count.get(result.source_scope, 0)
        if scope_count >= per_scope_limit:
            continue
        seen.add(key)
        by_scope_count[result.source_scope] = scope_count + 1
        compressed.append(result)
        if len(compressed) >= limit:
            break
    return compressed
