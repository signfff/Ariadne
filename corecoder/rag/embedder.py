"""Local embedding via fastembed (ONNX).

Runs on the CPU with no API key and no per-token cost, so indexing a repo
never touches the chat provider's quota.  fastembed defaults its model cache
to the system temp directory, which gets cleaned; we pin it under the user's
home instead so the download survives a reboot.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
CACHE_DIR = Path.home() / ".corecoder" / "models"

# BGE models are trained with an instruction on the query side only. fastembed's
# query_embed does not add it for this model - it measured identical to embed() -
# so it is prepended here. Without it the query lands in the wrong region of the
# space and every score collapses into a narrow band.
BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


class EmbedderUnavailable(RuntimeError):
    """fastembed is missing, or the weights could not be fetched."""


class Embedder:
    """Wraps one fastembed model. Loaded lazily so importing is cheap."""

    def __init__(self, model_name: str = DEFAULT_MODEL, cache_dir: Path | None = None):
        self.model_name = os.getenv("CORECODER_EMBED_MODEL") or model_name
        self.cache_dir = cache_dir or CACHE_DIR
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = self._load()
        return self._model

    def _load(self):
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise EmbedderUnavailable(
                "fastembed is not installed. Run: pip install -e \".[rag]\""
            ) from e

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            return TextEmbedding(self.model_name, cache_dir=str(self.cache_dir))
        except Exception as e:
            raise EmbedderUnavailable(
                f"Could not load embedding model '{self.model_name}': {e}\n"
                "The weights download from HuggingFace. Behind the GFW, set:\n"
                "  HF_ENDPOINT=https://hf-mirror.com\n"
                "  HF_HUB_DISABLE_XET=1"
            ) from e

    @property
    def dim(self) -> int:
        from fastembed import TextEmbedding

        for spec in TextEmbedding.list_supported_models():
            if spec["model"] == self.model_name:
                return int(spec["dim"])
        raise EmbedderUnavailable(f"unknown embedding model: {self.model_name}")

    def embed_documents(self, texts: list[str]):
        """Embed corpus text. Returns an (n, dim) float32 array."""
        import numpy as np

        if not texts:
            return np.zeros((0, self.dim), dtype="float32")
        return np.asarray(list(self.model.embed(texts)), dtype="float32")

    def embed_query(self, text: str):
        """Embed a search query, applying the model's own query instruction."""
        import numpy as np

        name = self.model_name.lower()
        if "bge" in name and "zh" in name:
            text = BGE_QUERY_PREFIX + text
        return np.asarray(next(iter(self.model.embed([text]))), dtype="float32")
