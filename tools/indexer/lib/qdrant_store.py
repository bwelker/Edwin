"""Qdrant collection management, upsert, and deletion."""

import sys
import time
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, SparseVectorParams, SparseIndexParams,
    PointStruct, SparseVector, Filter, FieldCondition, MatchValue,
)

from .config import QDRANT_URL, COLLECTION_NAME, EMBEDDING_DIM


class QdrantStore:
    """Manages the edwin-memory Qdrant collection."""

    def __init__(self, url: str = QDRANT_URL, collection: str = COLLECTION_NAME):
        self.collection = collection
        try:
            self.client = QdrantClient(url=url, timeout=30)
            # Quick health check
            self.client.get_collections()
        except Exception as e:
            print(f"ERROR: Cannot connect to Qdrant at {url}: {e}", file=sys.stderr)
            raise SystemExit(1)

    def ensure_collection(self, dense_dim: int = EMBEDDING_DIM):
        """Create collection if it doesn't exist. Verify config if it does."""
        collections = [c.name for c in self.client.get_collections().collections]

        if self.collection in collections:
            info = self.client.get_collection(self.collection)
            existing_dim = None
            if info.config.params.vectors:
                if isinstance(info.config.params.vectors, dict):
                    dense_cfg = info.config.params.vectors.get("text-dense")
                    if dense_cfg:
                        existing_dim = dense_cfg.size
            if existing_dim and existing_dim != dense_dim:
                print(f"WARNING: Collection '{self.collection}' has dimension "
                      f"{existing_dim}, expected {dense_dim}.", file=sys.stderr)
                print("  Use --force to reindex with new dimensions.", file=sys.stderr)
            return

        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                "text-dense": VectorParams(
                    size=dense_dim,
                    distance=Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "text-sparse": SparseVectorParams(
                    index=SparseIndexParams(on_disk=False),
                ),
            },
        )
        print(f"Created collection '{self.collection}' "
              f"(dense={dense_dim}, sparse=text-sparse)", file=sys.stderr)

    def delete_file_points(self, file_path: str):
        """Remove all points for a given file_path."""
        self.client.delete(
            collection_name=self.collection,
            points_selector=Filter(
                must=[FieldCondition(key="file_path", match=MatchValue(value=file_path))]
            ),
        )

    def upsert_chunks(self, points: list[PointStruct], batch_size: int = 100):
        """Batch upsert points with retry."""
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            for attempt in range(3):
                try:
                    self.client.upsert(
                        collection_name=self.collection,
                        points=batch,
                    )
                    break
                except Exception as e:
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        print(f"  Qdrant retry {attempt + 1}/3: {e}", file=sys.stderr)
                    else:
                        raise

    def collection_info(self) -> dict:
        """Get collection stats."""
        try:
            info = self.client.get_collection(self.collection)
            return {
                "collection": self.collection,
                "points_count": info.points_count,
                "status": str(info.status),
            }
        except Exception:
            return {"collection": self.collection, "status": "not found"}

    @staticmethod
    def make_point(point_id: str, dense_vec: list[float],
                   sparse_indices: list[int], sparse_values: list[float],
                   payload: dict) -> PointStruct:
        """Build a PointStruct for upsert."""
        return PointStruct(
            id=point_id,
            vector={
                "text-dense": dense_vec,
                "text-sparse": SparseVector(
                    indices=sparse_indices,
                    values=sparse_values,
                ),
            },
            payload=payload,
        )

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())
