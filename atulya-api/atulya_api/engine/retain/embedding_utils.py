"""
Embedding generation utilities for memory units.

This module enforces a strict 1:1 contract between input texts and output
embeddings. A short or long batch from the backend is treated as a fatal
contract violation rather than silently truncated, because every downstream
zip() in the retain pipeline relies on positional alignment.

The synchronous ``generate_embedding`` helper that previously lived here was
removed deliberately: it blocked the event loop on the recall hot path and
served as an attractor for new sync callers. Use ``generate_embeddings_batch``
from async code, or ``asyncio.run(generate_embeddings_batch(...))`` from a
sync entry point.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class EmbeddingBackendContractError(RuntimeError):
    """Raised when an embeddings backend returns the wrong number of vectors.

    Callers should treat this as a non-retryable backend bug. Retrying with the
    same input will deterministically produce the same mismatch and waste
    worker capacity.
    """


async def generate_embeddings_batch(embeddings_backend, texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for multiple texts using the provided embeddings backend.

    Runs the embedding generation in a thread pool to avoid blocking the event loop
    for CPU-bound operations.

    Args:
        embeddings_backend: Embeddings instance to use for encoding
        texts: List of texts to embed

    Returns:
        List of embeddings in same order as input texts. Length is guaranteed
        to equal ``len(texts)``.

    Raises:
        EmbeddingBackendContractError: If the backend returned a different
            number of vectors than texts.
    """
    if not texts:
        return []
    try:
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            embeddings_backend.encode,
            texts,
        )
    except Exception as e:
        raise Exception(f"Failed to generate batch embeddings: {str(e)}")

    if len(embeddings) != len(texts):
        raise EmbeddingBackendContractError(
            f"Embeddings backend {type(embeddings_backend).__name__} returned "
            f"{len(embeddings)} vectors for {len(texts)} input texts; the "
            f"retain pipeline requires strict 1:1 alignment"
        )
    return embeddings
