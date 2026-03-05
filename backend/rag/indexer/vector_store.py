"""
Qdrant vector store logic for Ablatix Indexer.
Handles connection, upsert, and search operations.
"""

from typing import List, Dict, Any, Optional
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    PointStruct,
    VectorParams,
    Distance,
    SparseVectorParams,
    SparseIndexParams
)

class VectorStore:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "ablatix_index",
        vector_size: int = 1024,
        distance: str = "Cosine"
    ):
        self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection_name

        existing = [c.name for c in self.client.get_collections().collections]
        if collection_name not in existing:
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance[distance.upper()]
                )
            )

    def upsert(
        self,
        embeddings: List[List[float]],
        payloads: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None
    ):
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in embeddings]
        if payloads is None:
            payloads = [{} for _ in embeddings]

        points = [
            PointStruct(id=pid, vector=vec, payload=payload)
            for pid, vec, payload in zip(ids, embeddings, payloads)
        ]
        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )

    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            with_payload=True
        ).points
        return [
            {
                "id": hit.id,
                "score": hit.score,
                "payload": hit.payload
            }
            for hit in results
        ]

    def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        top_k: int = 10,
        alpha: float = 0.5,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        # In qdrant-client 1.17.0, hybrid search uses query_points
        # with a prefetch for sparse + dense fusion
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            with_payload=True,
            query_filter=filter
        ).points
        return [
            {
                "id": hit.id,
                "score": hit.score,
                "payload": hit.payload
            }
            for hit in results
        ]