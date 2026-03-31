from unittest.mock import AsyncMock

import pytest

from atulya_api.engine.search.graph_retrieval import BFSGraphRetriever


@pytest.mark.asyncio
async def test_bfs_graph_retrieval_preserves_neighbor_proof_count():
    retriever = BFSGraphRetriever(entry_point_limit=1, entry_point_threshold=0.1, min_activation=0.1)
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        side_effect=[
            [
                {
                    "id": "seed-1",
                    "text": "Seed observation",
                    "context": None,
                    "event_date": None,
                    "occurred_start": None,
                    "occurred_end": None,
                    "mentioned_at": None,
                    "fact_type": "observation",
                    "document_id": None,
                    "chunk_id": None,
                    "tags": ["team:platform"],
                    "proof_count": 1,
                    "similarity": 0.91,
                }
            ],
            [
                {
                    "id": "neighbor-1",
                    "text": "Expanded observation",
                    "context": None,
                    "occurred_start": None,
                    "occurred_end": None,
                    "mentioned_at": None,
                    "fact_type": "observation",
                    "document_id": None,
                    "chunk_id": None,
                    "tags": ["team:platform"],
                    "proof_count": 4,
                    "weight": 0.7,
                    "link_type": "semantic",
                    "from_unit_id": "seed-1",
                }
            ],
            [],
        ]
    )

    results = await retriever._retrieve_with_conn(
        conn=conn,
        query_embedding_str="[1.0,0.0]",
        bank_id="bank-1",
        fact_type="observation",
        budget=5,
    )

    assert len(results) == 2
    neighbor = next(result for result in results if result.id == "neighbor-1")
    assert neighbor.proof_count == 4
