"""Tests for chunking, storage, and hybrid retrieval.

The embedder is stubbed with deterministic hashed vectors, so these run
without downloading a model or hitting any network.
"""

import numpy as np
import pytest

from ariadne_code.rag.chunker import chunk_file, is_indexable
from ariadne_code.rag.indexer import _is_test, build_index, hybrid_search, open_store

DIM = 32


class StubEmbedder:
    """Deterministic bag-of-words vectors - similar text lands nearby."""

    model_name = "stub"
    dim = DIM

    def _vec(self, text: str):
        v = np.zeros(DIM, dtype="float32")
        for word in text.lower().split():
            v[hash(word) % DIM] += 1.0
        return v

    def embed_documents(self, texts):
        return np.asarray([self._vec(t) for t in texts], dtype="float32")

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "app.py").write_text(
        '"""Session storage helpers."""\n'
        "\n"
        "import json\n"
        "\n"
        "def save_session(data):\n"
        '    """Write the conversation to disk."""\n'
        "    return json.dumps(data)\n"
        "\n"
        "\n"
        "def unrelated_math(a, b):\n"
        '    """Add two numbers."""\n'
        "    return a + b\n",
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text('{"noise": true}\n', encoding="utf-8")
    return tmp_path


# ---- chunking -----------------------------------------------------------

def test_chunks_split_on_function_boundaries(project):
    chunks = chunk_file(project / "app.py", "app.py")
    by_name = {c.name: c for c in chunks}

    assert "save_session" in by_name
    assert "unrelated_math" in by_name
    assert by_name["save_session"].kind == "function"
    # each function is a complete unit, not a window cutting through one
    assert "def save_session" in by_name["save_session"].text
    assert "unrelated_math" not in by_name["save_session"].text


def test_module_chunk_does_not_swallow_functions(project):
    """Imports and functions must not end up in one chunk spanning the file."""
    chunks = chunk_file(project / "app.py", "app.py")
    module = [c for c in chunks if c.kind == "module"]

    assert module, "module-level code should still be indexed"
    for chunk in module:
        assert "def save_session" not in chunk.text


def test_embedding_card_keeps_prose_and_drops_body(project):
    chunk = next(c for c in chunk_file(project / "app.py", "app.py") if c.name == "save_session")
    card = chunk.for_embedding()

    assert "Write the conversation to disk" in card  # docstring survives
    assert "save session" in card                    # identifier is split into words
    assert "return json.dumps" not in card           # body does not


def test_generated_files_are_not_indexable(project):
    assert is_indexable(project / "app.py")
    assert not is_indexable(project / "package-lock.json")


def test_test_files_are_recognised():
    assert _is_test("tests/test_core.py")
    assert _is_test("web/src/App.test.jsx")
    assert not _is_test("ariadne_code/agent.py")


# ---- store and retrieval ------------------------------------------------

def test_index_is_incremental(project):
    embedder = StubEmbedder()
    store = open_store(project, embedder)
    try:
        first = build_index(project, embedder, store)
        assert first.files_indexed == 1

        again = build_index(project, embedder, store)
        assert again.files_indexed == 0        # nothing changed, nothing re-embedded
        assert again.total_chunks == first.total_chunks

        (project / "app.py").write_text("def changed():\n    return 1\n", encoding="utf-8")
        third = build_index(project, embedder, store)
        assert third.files_indexed == 1
    finally:
        store.close()


def test_deleted_files_leave_the_index(project):
    embedder = StubEmbedder()
    store = open_store(project, embedder)
    try:
        build_index(project, embedder, store)
        (project / "app.py").unlink()
        stats = build_index(project, embedder, store)

        assert stats.files_removed == 1
        assert stats.total_chunks == 0
    finally:
        store.close()


def test_keyword_arm_finds_exact_identifier(project):
    embedder = StubEmbedder()
    store = open_store(project, embedder)
    try:
        build_index(project, embedder, store)
        hits = store.keyword_search("save_session", top_k=5)
        assert any(h.name == "save_session" for h in hits)
    finally:
        store.close()


def test_hybrid_search_reports_which_arms_matched(project):
    embedder = StubEmbedder()
    store = open_store(project, embedder)
    try:
        build_index(project, embedder, store)
        results = hybrid_search(store, embedder, "save_session", top_k=5)

        assert results
        assert all(set(arms) <= {"dense", "keyword"} for _, _, arms in results)
        assert any("keyword" in arms for _, _, arms in results)
    finally:
        store.close()


def test_search_on_empty_index_returns_nothing(tmp_path):
    embedder = StubEmbedder()
    store = open_store(tmp_path, embedder)
    try:
        assert store.search(embedder.embed_query("anything")) == []
        assert hybrid_search(store, embedder, "anything") == []
    finally:
        store.close()
