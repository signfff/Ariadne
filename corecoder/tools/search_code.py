"""Semantic code search over the project index.

grep answers "where does this string appear". This answers "where is the code
that does X", which is the question someone reading an unfamiliar codebase
actually has. The two are complementary, so the index fuses both: dense
retrieval finds the concept, BM25 pins the exact identifier.

The index lives under the project root, and tools run with the project as the
working directory, so it is found the same way the other file tools find files.
"""

from __future__ import annotations

from pathlib import Path

from .base import Tool

# the ONNX model takes a second to load; keep one per process
_EMBEDDER = None


def _embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        from ..rag import Embedder

        _EMBEDDER = Embedder()
    return _EMBEDDER


class SearchCodeTool(Tool):
    name = "search_code"
    description = (
        "Search the codebase by meaning, not by exact text. "
        "Use this to find where a behaviour lives when you do not know the "
        "identifier - 'where is retry handled', 'how are sessions saved'. "
        "Returns ranked snippets with file paths and line numbers. "
        "Use grep instead when you know the exact string to look for."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What you are looking for, in plain language",
            },
            "top_k": {
                "type": "integer",
                "description": "How many snippets to return (default 6, max 20)",
            },
        },
        "required": ["query"],
    }

    def execute(self, query: str, top_k: int = 6) -> str:
        from ..rag import EmbedderUnavailable, hybrid_search, index_path, open_store

        top_k = max(1, min(int(top_k), 20))
        root = Path.cwd()

        if not index_path(root).exists():
            return (
                "No index for this project yet. Build one with:\n"
                "  corecoder index\n"
                "Until then, use grep and glob."
            )

        try:
            embedder = _embedder()
            store = open_store(root, embedder)
        except EmbedderUnavailable as e:
            return f"Semantic search unavailable: {e}"

        try:
            results = hybrid_search(store, embedder, query, top_k=top_k)
        finally:
            store.close()

        if not results:
            return f"No matches for: {query}"

        blocks = [f"{len(results)} results for: {query}\n"]
        for i, (hit, score, arms) in enumerate(results, 1):
            body = hit.text if len(hit.text) <= 1200 else hit.text[:1200] + "\n... (truncated)"
            blocks.append(
                f"[{i}] {hit.location}  ({hit.kind} {hit.name}, score {score:.3f}, {'+'.join(sorted(set(arms)))})\n"
                f"{body}"
            )
        return "\n\n".join(blocks)
