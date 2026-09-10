"""Index storage: chunk metadata in SQLite, vectors as one packed array.

At repo scale - a few thousand chunks - an exhaustive cosine scan over a
contiguous float32 matrix takes single-digit milliseconds, so there is no ANN
index to build, tune, or keep in sync.  Vectors are L2-normalised on write,
which makes cosine similarity a plain dot product.

The index is one SQLite file, so it moves with the project and needs no
running service.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .chunker import Chunk

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    path   TEXT PRIMARY KEY,
    digest TEXT NOT NULL,
    mtime  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id         INTEGER PRIMARY KEY,
    path       TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line   INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    name       TEXT NOT NULL,
    text       TEXT NOT NULL,
    vector     BLOB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);

-- keyword arm of the hybrid search; contentless FTS5 mirrors chunks by rowid
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    name, text, content=chunks, content_rowid=id, tokenize="unicode61"
);
"""


@dataclass
class SearchHit:
    score: float
    path: str
    start_line: int
    end_line: int
    kind: str
    name: str
    text: str

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


def file_digest(path: Path) -> str:
    """Content hash, so re-indexing skips files that did not really change."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


class VectorStore:
    """SQLite-backed chunk store with brute-force cosine search."""

    def __init__(self, db_path: Path, dim: int):
        self.db_path = Path(db_path)
        self.dim = dim
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self._set_meta("schema_version", SCHEMA_VERSION)
        self._set_meta("dim", dim)
        self.conn.commit()
        self._cache = None  # (ids ndarray, matrix ndarray)

    # ---- metadata -------------------------------------------------------

    def _set_meta(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def get_meta(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    # ---- writing --------------------------------------------------------

    def needs_reindex(self, rel_path: str, digest: str) -> bool:
        row = self.conn.execute("SELECT digest FROM files WHERE path = ?", (rel_path,)).fetchone()
        return row is None or row["digest"] != digest

    def replace_file(self, rel_path: str, digest: str, mtime: float, chunks: list[Chunk], vectors) -> None:
        """Swap in a file's chunks. Existing rows for that path are dropped first."""
        import numpy as np

        normed = _normalise(np.asarray(vectors, dtype="float32"))
        with self.conn:
            # keep the FTS mirror in step: contentless tables need the old rows
            # deleted explicitly before their chunks disappear
            self._fts_delete_path(rel_path)
            self.conn.execute("DELETE FROM chunks WHERE path = ?", (rel_path,))
            self.conn.executemany(
                "INSERT INTO chunks(path, start_line, end_line, kind, name, text, vector) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                [
                    (c.path, c.start_line, c.end_line, c.kind, c.name, c.text, normed[i].tobytes())
                    for i, c in enumerate(chunks)
                ],
            )
            self._fts_insert_path(rel_path)
            self.conn.execute(
                "INSERT INTO files(path, digest, mtime) VALUES(?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET digest = excluded.digest, mtime = excluded.mtime",
                (rel_path, digest, mtime),
            )
        self._cache = None

    def drop_missing(self, present: set[str]) -> int:
        """Remove files that no longer exist on disk."""
        known = {r["path"] for r in self.conn.execute("SELECT path FROM files")}
        gone = known - present
        if gone:
            with self.conn:
                for path in gone:
                    self._fts_delete_path(path)
                self.conn.executemany("DELETE FROM chunks WHERE path = ?", [(p,) for p in gone])
                self.conn.executemany("DELETE FROM files WHERE path = ?", [(p,) for p in gone])
            self._cache = None
        return len(gone)

    # ---- reading --------------------------------------------------------

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]

    def _matrix(self):
        """Load every vector into one contiguous array, cached until the next write."""
        import numpy as np

        if self._cache is None:
            rows = self.conn.execute("SELECT id, vector FROM chunks ORDER BY id").fetchall()
            if not rows:
                self._cache = (np.zeros(0, dtype="int64"), np.zeros((0, self.dim), dtype="float32"))
            else:
                ids = np.fromiter((r["id"] for r in rows), dtype="int64", count=len(rows))
                mat = np.frombuffer(b"".join(r["vector"] for r in rows), dtype="float32")
                self._cache = (ids, mat.reshape(len(rows), self.dim))
        return self._cache

    def search(self, query_vector, top_k: int = 8) -> list[SearchHit]:
        import numpy as np

        ids, matrix = self._matrix()
        if len(ids) == 0:
            return []

        q = _normalise(np.asarray(query_vector, dtype="float32").reshape(1, -1))[0]
        scores = matrix @ q

        top_k = min(top_k, len(ids))
        best = np.argpartition(-scores, top_k - 1)[:top_k]
        best = best[np.argsort(-scores[best])]

        placeholders = ",".join("?" * len(best))
        rows = {
            r["id"]: r
            for r in self.conn.execute(
                f"SELECT * FROM chunks WHERE id IN ({placeholders})", [int(ids[i]) for i in best]
            )
        }
        hits = []
        for i in best:
            row = rows[int(ids[i])]
            hits.append(SearchHit(
                score=float(scores[i]),
                path=row["path"],
                start_line=row["start_line"],
                end_line=row["end_line"],
                kind=row["kind"],
                name=row["name"],
                text=row["text"],
            ))
        return hits

    def keyword_search(self, query: str, top_k: int = 8) -> list[SearchHit]:
        """BM25 over chunk names and bodies - the keyword arm of hybrid search."""
        terms = _fts_terms(query)
        if not terms:
            return []
        try:
            rows = self.conn.execute(
                "SELECT c.*, bm25(chunks_fts) AS rank FROM chunks_fts "
                "JOIN chunks c ON c.id = chunks_fts.rowid "
                "WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (terms, top_k),
            ).fetchall()
        except sqlite3.OperationalError:
            # a query that FTS5 cannot parse should return nothing, not explode
            return []

        return [
            SearchHit(
                score=-float(r["rank"]),  # bm25() is lower-is-better
                path=r["path"], start_line=r["start_line"], end_line=r["end_line"],
                kind=r["kind"], name=r["name"], text=r["text"],
            )
            for r in rows
        ]

    def _fts_delete_path(self, rel_path: str) -> None:
        rows = self.conn.execute(
            "SELECT id, name, text FROM chunks WHERE path = ?", (rel_path,)
        ).fetchall()
        for r in rows:
            self.conn.execute(
                "INSERT INTO chunks_fts(chunks_fts, rowid, name, text) VALUES('delete', ?, ?, ?)",
                (r["id"], r["name"], r["text"]),
            )

    def _fts_insert_path(self, rel_path: str) -> None:
        self.conn.execute(
            "INSERT INTO chunks_fts(rowid, name, text) "
            "SELECT id, name, text FROM chunks WHERE path = ?",
            (rel_path,),
        )

    def close(self) -> None:
        self.conn.close()


def _fts_terms(query: str) -> str:
    """Quote each word so identifiers and punctuation cannot break MATCH syntax."""
    import re

    words = re.findall(r"[\w一-鿿]+", query)
    return " OR ".join(f'"{w}"' for w in words if len(w) > 1)


def _normalise(matrix):
    """L2-normalise rows so cosine similarity reduces to a dot product."""
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)
