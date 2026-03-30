from unittest.mock import AsyncMock, MagicMock

import pytest

from atulya_api.engine.cross_encoder import CohereCrossEncoder


@pytest.mark.asyncio
async def test_cohere_cross_encoder_custom_endpoint_posts_to_exact_url():
    encoder = CohereCrossEncoder(
        api_key="test-key",
        model="Cohere-rerank-v4.0-fast",
        base_url="https://example.services.ai.azure.com/models/rerank",
    )

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "results": [
            {"index": 0, "relevance_score": 0.91},
            {"index": 1, "relevance_score": 0.33},
        ]
    }

    encoder._httpx_client = MagicMock()
    encoder._httpx_client.post = AsyncMock(return_value=response)

    scores = await encoder.predict(
        [
            ("What is the capital of France?", "Paris is the capital of France."),
            ("What is the capital of France?", "Python is a programming language."),
        ]
    )

    assert scores == [0.91, 0.33]
    encoder._httpx_client.post.assert_awaited_once_with(
        "https://example.services.ai.azure.com/models/rerank",
        headers={
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        },
        json={
            "model": "Cohere-rerank-v4.0-fast",
            "query": "What is the capital of France?",
            "documents": [
                "Paris is the capital of France.",
                "Python is a programming language.",
            ],
        },
    )
