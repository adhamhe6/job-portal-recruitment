"""The WordLlama embedder contract: L2-normalised float32, deterministic, batch-consistent, fails loudly on bad input."""

from __future__ import annotations

import numpy as np
import pytest

from app.core.config import get_settings
from app.matching.embedder import (
    EmbeddingError,
    WordLlamaEmbedder,
    _normalise,
    aembed,
    get_embedder,
    reset_embedder,
)

BACKEND_JOB = (
    "Backend Engineer. Python, FastAPI, PostgreSQL, Docker, Redis. Design and build REST APIs and services, "
    "tune SQL queries and operate containers in production."
)
BACKEND_PERSON = (
    "Backend developer with five years building Python APIs using FastAPI and PostgreSQL, deployed with Docker "
    "and Redis caching."
)
NURSE_PERSON = (
    "Registered nurse in an intensive care unit providing patient care, medication administration, "
    "life support and clinical documentation."
)
TEXTS = [BACKEND_JOB, BACKEND_PERSON, NURSE_PERSON, "short", "Ünïcödé text — with punctuation!?", "x" * 5000]


@pytest.fixture(scope="module")
def embedder() -> WordLlamaEmbedder:
    emb = get_embedder()
    assert isinstance(emb, WordLlamaEmbedder)
    return emb


def test_metadata_matches_settings(embedder: WordLlamaEmbedder) -> None:
    s = get_settings()
    assert (embedder.name, embedder.version, embedder.dim) == (
        s.embedding_model_name,
        s.embedding_version,
        s.embedding_dim,
    )
    assert embedder.dim == 256


def test_singleton(embedder: WordLlamaEmbedder) -> None:
    assert get_embedder() is embedder


def test_vectors_are_float32_l2_normalised(embedder: WordLlamaEmbedder) -> None:
    out = embedder.embed(TEXTS)
    assert out.shape == (len(TEXTS), 256) and out.dtype == np.float32
    assert np.isfinite(out).all()
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-5)


def test_deterministic(embedder: WordLlamaEmbedder) -> None:
    a, b = embedder.embed(TEXTS), embedder.embed(TEXTS)
    assert np.array_equal(a, b)


def test_batch_equals_singles(embedder: WordLlamaEmbedder) -> None:
    batch = embedder.embed(TEXTS)
    singles = np.vstack([embedder.embed([t]) for t in TEXTS])
    assert np.allclose(batch, singles, atol=1e-5)


def test_order_in_batch_does_not_matter(embedder: WordLlamaEmbedder) -> None:
    forward, backward = embedder.embed(TEXTS), embedder.embed(TEXTS[::-1])[::-1]
    assert np.allclose(forward, backward, atol=1e-5)


def test_surrounding_whitespace_is_ignored(embedder: WordLlamaEmbedder) -> None:
    assert np.array_equal(embedder.embed(["  hello world \n"]), embedder.embed(["hello world"]))


@pytest.mark.parametrize("bad", [[], [""], ["   "], ["ok text", ""], ["\n\t"]])
def test_empty_input_raises(embedder: WordLlamaEmbedder, bad: list[str]) -> None:
    with pytest.raises(EmbeddingError):
        embedder.embed(bad)


@pytest.mark.parametrize("odd", ["!!!", "日本語のテキスト", "😀", "a", "1234567890"])
def test_unusual_text_yields_a_valid_vector_or_a_clean_error(embedder: WordLlamaEmbedder, odd: str) -> None:
    try:
        vec = embedder.embed([odd])
    except EmbeddingError:
        return
    assert np.isfinite(vec).all() and np.linalg.norm(vec) == pytest.approx(1.0, abs=1e-5)


def test_backend_person_is_closer_to_backend_job_than_a_nurse(embedder: WordLlamaEmbedder) -> None:
    job, backend, nurse = embedder.embed([BACKEND_JOB, BACKEND_PERSON, NURSE_PERSON])
    assert float(job @ backend) > float(job @ nurse) + 0.15
    assert float(job @ backend) > 0.5


def test_similarity_is_symmetric_and_self_similarity_is_one(embedder: WordLlamaEmbedder) -> None:
    a, b = embedder.embed([BACKEND_JOB, NURSE_PERSON])
    assert float(a @ b) == pytest.approx(float(b @ a), abs=1e-6)
    assert float(a @ a) == pytest.approx(1.0, abs=1e-5)


async def test_async_wrapper_matches_sync(embedder: WordLlamaEmbedder) -> None:
    assert np.array_equal(await aembed(TEXTS[:3]), embedder.embed(TEXTS[:3]))
    with pytest.raises(EmbeddingError):
        await aembed([""])


# --- _normalise guards -----------------------------------------------------------------------------------------------


def test_normalise_rejects_wrong_shape_nan_inf_and_zero_vectors() -> None:
    with pytest.raises(EmbeddingError):
        _normalise(np.ones((2, 5), dtype=np.float32), 8)
    with pytest.raises(EmbeddingError):
        _normalise(np.ones(8, dtype=np.float32), 8)  # not 2-D
    with pytest.raises(EmbeddingError):
        _normalise(np.array([[1.0, np.nan]], dtype=np.float32), 2)
    with pytest.raises(EmbeddingError):
        _normalise(np.array([[1.0, np.inf]], dtype=np.float32), 2)
    with pytest.raises(EmbeddingError):
        _normalise(np.array([[0.0, 0.0], [1.0, 0.0]], dtype=np.float32), 2)  # one zero row poisons the batch


def test_normalise_scales_to_unit_length_and_casts_to_float32() -> None:
    out = _normalise(np.array([[3.0, 4.0]], dtype=np.float64), 2)
    assert out.dtype == np.float32 and np.allclose(out, [[0.6, 0.8]])


# --- construction failures ------------------------------------------------------------------------------------------


def test_model_load_failure_is_an_embedding_error_and_never_touches_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import wordllama

    seen: dict[str, object] = {}

    def boom(*args: object, **kwargs: object) -> None:
        seen.update(kwargs)
        raise RuntimeError("weights missing")

    monkeypatch.setattr(wordllama.WordLlama, "load", boom)
    with pytest.raises(EmbeddingError, match="could not load"):
        WordLlamaEmbedder()
    assert seen.get("disable_download") is True  # offline by construction


def test_reset_embedder_rebuilds_the_singleton(embedder: WordLlamaEmbedder) -> None:
    reset_embedder()
    try:
        fresh = get_embedder()
        assert fresh is not embedder
        assert np.array_equal(fresh.embed([BACKEND_JOB]), embedder.embed([BACKEND_JOB]))
    finally:
        reset_embedder()
        get_embedder()
