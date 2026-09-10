"""Semantic code search: chunk a repo, embed it locally, retrieve by meaning."""

from .chunker import Chunk, chunk_file, chunk_project
from .embedder import Embedder, EmbedderUnavailable
from .indexer import IndexStats, build_index, hybrid_search, index_path, open_store
from .store import SearchHit, VectorStore

__all__ = [
    "Chunk", "chunk_file", "chunk_project",
    "Embedder", "EmbedderUnavailable",
    "IndexStats", "build_index", "hybrid_search", "index_path", "open_store",
    "SearchHit", "VectorStore",
]
