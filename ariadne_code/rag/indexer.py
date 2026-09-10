"""Build and refresh a project's index.

Indexing is incremental: a file is re-chunked and re-embedded only when its
content hash changes, so a second run over an unchanged repo does no work.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .chunker import SKIP_DIRS, chunk_file, is_indexable
from .embedder import Embedder
from .store import VectorStore, file_digest

INDEX_DIRNAME = ".ariadne_index"
INDEX_FILENAME = "index.db"
BATCH = 64


@dataclass
class IndexStats:
    files_scanned: int = 0
    files_indexed: int = 0
    files_removed: int = 0
    chunks_written: int = 0
    total_chunks: int = 0

    def summary(self) -> str:
        if self.files_indexed == 0 and self.files_removed == 0:
            return f"索引已是最新：{self.total_chunks} 个片段，{self.files_scanned} 个文件"
        return (
            f"已索引 {self.files_indexed} 个文件（共扫描 {self.files_scanned} 个），"
            f"写入 {self.chunks_written} 个片段，移除 {self.files_removed} 个失效文件，"
            f"索引现有 {self.total_chunks} 个片段"
        )


def index_path(root: Path) -> Path:
    return root / INDEX_DIRNAME / INDEX_FILENAME


def open_store(root: Path, embedder: Embedder) -> VectorStore:
    return VectorStore(index_path(root), dim=embedder.dim)


def iter_indexable(root: Path):
    """Yield (absolute path, project-relative path) for every file worth indexing."""
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if not is_indexable(path):
            continue
        yield path, "/".join(rel_parts)


def build_index(root: Path, embedder: Embedder, store: VectorStore | None = None,
                on_progress=None) -> IndexStats:
    """Index `root`, skipping files whose content has not changed."""
    owned = store is None
    store = store or open_store(root, embedder)
    stats = IndexStats()
    present: set[str] = set()

    try:
        for path, rel in iter_indexable(root):
            stats.files_scanned += 1
            present.add(rel)

            try:
                digest = file_digest(path)
            except OSError:
                continue
            if not store.needs_reindex(rel, digest):
                continue

            chunks = chunk_file(path, rel)
            if not chunks:
                continue

            vectors = []
            for i in range(0, len(chunks), BATCH):
                batch = chunks[i : i + BATCH]
                vectors.extend(embedder.embed_documents([c.for_embedding() for c in batch]))

            store.replace_file(rel, digest, path.stat().st_mtime, chunks, vectors)
            stats.files_indexed += 1
            stats.chunks_written += len(chunks)
            if on_progress:
                on_progress(rel, stats)

        stats.files_removed = store.drop_missing(present)
        stats.total_chunks = store.count()
    finally:
        if owned:
            store.close()
    return stats


# A test exercising a feature reads a lot like the feature itself, so tests
# crowd out the source they cover. Someone reading a codebase wants the
# implementation first, so tests are ranked below it rather than dropped.
TEST_PENALTY = 0.45


def _is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or name.endswith(("_test.py", ".test.js", ".test.jsx", ".spec.js", ".spec.ts"))
        or "/tests/" in f"/{path}"
    )


def hybrid_search(store: VectorStore, embedder: Embedder, query: str,
                  top_k: int = 8, rrf_k: int = 10):
    """Fuse dense and keyword results with Reciprocal Rank Fusion.

    The two arms score on incompatible scales - cosine similarity against BM25 -
    so RRF ranks by position rather than value: a hit scores 1/(k + rank) in
    each list it appears in, and the sums decide the order. A chunk both arms
    like outranks one that only a single arm put first.

    `rrf_k` is small on purpose. The textbook 60 was tuned for fusing many long
    result lists; over two short ones it flattens the top into a near-tie, and
    agreement between the arms stops meaning anything.
    """
    pool = max(top_k * 3, 20)
    dense = store.search(embedder.embed_query(query), top_k=pool)
    keyword = store.keyword_search(query, top_k=pool)

    fused: dict[str, dict] = {}
    for arm, hits in (("dense", dense), ("keyword", keyword)):
        for rank, hit in enumerate(hits):
            entry = fused.setdefault(hit.location, {"hit": hit, "score": 0.0, "arms": []})
            entry["score"] += 1.0 / (rrf_k + rank + 1)
            entry["arms"].append(arm)

    for entry in fused.values():
        if _is_test(entry["hit"].path):
            entry["score"] *= TEST_PENALTY

    ordered = sorted(fused.values(), key=lambda e: -e["score"])[:top_k]
    return [(e["hit"], e["score"], e["arms"]) for e in ordered]
