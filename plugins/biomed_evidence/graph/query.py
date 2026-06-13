from __future__ import annotations

from collections import deque

from plugins.biomed_evidence.graph.schema import BiomedEvidenceGraph


def shortest_path(
    graph: BiomedEvidenceGraph,
    source: str,
    target: str,
    *,
    directed: bool = False,
    max_depth: int = 6,
) -> list[str]:
    """Return node IDs for the shortest path, or an empty list."""

    if source == target:
        return [source]
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)
        if not directed:
            adjacency.setdefault(edge.target, []).append(edge.source)
    queue: deque[tuple[str, list[str]]] = deque([(source, [source])])
    seen = {source}
    while queue:
        node_id, path = queue.popleft()
        if len(path) > max_depth + 1:
            continue
        for next_id in adjacency.get(node_id, []):
            if next_id in seen:
                continue
            next_path = [*path, next_id]
            if next_id == target:
                return next_path
            seen.add(next_id)
            queue.append((next_id, next_path))
    return []
