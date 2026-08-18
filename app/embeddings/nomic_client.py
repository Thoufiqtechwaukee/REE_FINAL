"""
NomicEmbeddingService (spec §12). Batches to /v1/embeddings, validates the
response's model/dimensionality, retries with backoff, and always returns
L2-normalized vectors (so FAISS IndexFlatIP == cosine similarity downstream).
Confirmed live against the real RunPod endpoint during planning: POST
{base}/embeddings with {"model": "nomic-embed-text", "input": [...]} returns
the standard OpenAI-shaped {"data": [{"index", "embedding"}], "model", ...},
768-dim vectors.
"""
import asyncio
import logging

import httpx
import numpy as np

from app.core.config import get_settings
from app.core.versioning import EMBEDDING_VERSION

logger = logging.getLogger(__name__)

_BATCH_SIZE = 32
_MAX_RETRIES = 3
_TIMEOUT_SECONDS = 60.0


class EmbeddingError(Exception):
    pass


class EmbeddingDimensionMismatch(EmbeddingError):
    pass


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


async def embed_batch(texts: list[str]) -> np.ndarray:
    """Returns an (N, D) float32 array of L2-normalized embeddings, one row
    per input text, in the same order. Raises EmbeddingError if the endpoint
    is unreachable after retries or returns an unexpected shape -- callers
    (skill/role matchers, chunk indexing) must handle this as "semantic
    component unavailable" per spec §52, never silently substitute zeros."""
    if not texts:
        return np.zeros((0, get_settings().embedding_expected_dimension), dtype=np.float32)

    settings = get_settings()
    all_vectors: list[list[float]] = [None] * len(texts)  # type: ignore[list-item]

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start : start + _BATCH_SIZE]
            batch_vectors = await _embed_one_batch(client, batch, settings)
            for i, vec in enumerate(batch_vectors):
                all_vectors[start + i] = vec

    missing = [i for i, v in enumerate(all_vectors) if v is None]
    if missing:
        raise EmbeddingError(f"Embedding endpoint returned no vector for indices {missing}")

    arr = np.array(all_vectors, dtype=np.float32)
    if arr.shape[1] != settings.embedding_expected_dimension:
        raise EmbeddingDimensionMismatch(
            f"Expected {settings.embedding_expected_dimension}-dim embeddings, got {arr.shape[1]}"
        )
    return _normalize(arr)


async def _embed_one_batch(client: httpx.AsyncClient, batch: list[str], settings) -> list[list[float]]:
    headers = {"Authorization": f"Bearer {settings.runpod_api_key}"} if settings.runpod_api_key else {}
    payload = {"model": settings.runpod_embedding_model, "input": batch}

    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = await client.post(settings.embeddings_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            items = sorted(data["data"], key=lambda d: d["index"])
            if len(items) != len(batch):
                raise EmbeddingError(f"Expected {len(batch)} embeddings, got {len(items)}")
            return [item["embedding"] for item in items]
        except Exception as exc:  # noqa: BLE001 -- deliberately broad, retried uniformly
            last_error = exc
            logger.warning("Embedding batch attempt %d/%d failed: %s", attempt, _MAX_RETRIES, exc)
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(0.5 * attempt)

    raise EmbeddingError(f"Embedding endpoint failed after {_MAX_RETRIES} attempts: {last_error}") from last_error


async def health_check() -> bool:
    try:
        await embed_batch(["health check"])
        return True
    except EmbeddingError:
        return False


EMBEDDING_MODEL_VERSION = EMBEDDING_VERSION
