"""Embedding backends behind one small protocol, so the model is replaceable.

Default: **WordLlama** (``wordllama-l2-supercat``, 256-d). Its pretrained token-embedding weights ship inside the
PyPI wheel, so it runs offline on CPU, is deterministic and embeds a document in well under a millisecond — a good fit
for a self-contained portfolio deployment. Optional: sentence-transformers (needs a model download from the
HuggingFace hub; not available in every environment).

Contract: ``embed`` returns an ``(n, dim)`` float32 array of **L2-normalised** vectors, so cosine similarity is a dot
product and pgvector's cosine distance (``<=>``) equals ``1 - dot``.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np

from app.core.config import get_settings


class EmbeddingError(Exception):
    """Embedding could not be produced (empty input, model unavailable, invalid vector)."""


class Embedder(Protocol):
    name: str
    version: str
    dim: int

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


def _normalise(vectors: np.ndarray, dim: int) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] != dim:
        raise EmbeddingError(f"unexpected embedding shape {arr.shape}, expected (n, {dim})")
    if not np.isfinite(arr).all():
        raise EmbeddingError("embedding contains non-finite values")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    if (norms == 0).any():
        raise EmbeddingError("empty or untokenisable input produced a zero vector")
    return arr / norms


class WordLlamaEmbedder:
    """Pretrained static token-embedding model (averaged, projected). Thread-safe after construction."""

    def __init__(self, dim: int = 256, name: str = "wordllama-l2-supercat-256", version: str = "v1") -> None:
        try:
            import wordllama
            from wordllama import WordLlama
        except Exception as exc:  # pragma: no cover - import problems are environment errors
            raise EmbeddingError("wordllama is not installed") from exc
        self.dim, self.name, self.version = dim, name, version
        # The wheel bundles weights/ and tokenizers/; pointing cache_dir at the package directory makes the loader
        # find them without any network access (disable_download guarantees we never reach for the hub).
        package_dir = Path(wordllama.__file__).parent
        try:
            self._model = WordLlama.load(cache_dir=package_dir, disable_download=True, dim=dim)
        except Exception as exc:
            raise EmbeddingError("could not load the bundled embedding model") from exc

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        cleaned = [t.strip() for t in texts]
        if not cleaned or any(not t for t in cleaned):
            raise EmbeddingError("cannot embed empty text")
        return _normalise(self._model.embed(cleaned), self.dim)


class SentenceTransformerEmbedder:  # pragma: no cover - optional backend, requires a model download
    """Optional backend. NOTE: the vector column is ``vector(256)``; using a model with a different dimension requires
    a migration (see docs/architecture.md, "Changing the embedding model")."""

    def __init__(self, model_name: str, dim: int, name: str, version: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise EmbeddingError("sentence-transformers is not installed (pip install '.[st]')") from exc
        self.dim, self.name, self.version = dim, name, version
        try:
            self._model = SentenceTransformer(model_name)
        except Exception as exc:
            raise EmbeddingError("could not load the sentence-transformers model") from exc
        if self._model.get_sentence_embedding_dimension() != dim:
            raise EmbeddingError(
                f"model dimension {self._model.get_sentence_embedding_dimension()} != configured EMBEDDING_DIM {dim}"
            )

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts or any(not t.strip() for t in texts):
            raise EmbeddingError("cannot embed empty text")
        return _normalise(self._model.encode(list(texts), normalize_embeddings=True), self.dim)


_lock = threading.Lock()


@lru_cache
def _build() -> Embedder:
    s = get_settings()
    if s.embedding_backend == "sentence-transformers":
        return SentenceTransformerEmbedder(
            s.sentence_transformer_model, s.embedding_dim, s.embedding_model_name, s.embedding_version
        )
    return WordLlamaEmbedder(s.embedding_dim, s.embedding_model_name, s.embedding_version)


def get_embedder() -> Embedder:
    """Process-wide singleton (model loads once, ~0.6 s)."""
    with _lock:
        return _build()


def reset_embedder() -> None:
    _build.cache_clear()


async def aembed(texts: Sequence[str]) -> np.ndarray:
    """Embed off the event loop (CPU-bound)."""
    embedder = get_embedder()
    return await asyncio.to_thread(embedder.embed, list(texts))
