"""Qdrant vector store — index and search code embeddings."""
import os
import uuid
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance, VectorParams, PointStruct,
        Filter, FieldCondition, MatchValue, Range, MatchAny,
    )
    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False

from app.services.embeddings import embed_texts, get_config


QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "sentinel_code"


@dataclass
class SearchResult:
    id: str
    score: float
    file_path: str
    chunk_type: str
    symbol_name: Optional[str]
    content: str
    metadata: Dict[str, Any]


_client: Optional[Any] = None


def get_client():
    global _client
    if _client is None and HAS_QDRANT:
        try:
            _client = QdrantClient(url=QDRANT_URL, timeout=5)
        except Exception:
            _client = None
    return _client


def ensure_collection():
    """Create the collection if it doesn't exist."""
    client = get_client()
    if not client:
        return False
    try:
        collections = [c.name for c in client.get_collections().collections]
        if COLLECTION_NAME not in collections:
            cfg = get_config()
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=cfg.dimensions,
                    distance=Distance.COSINE,
                ),
            )
        return True
    except Exception:
        return False


def upsert_chunks(chunks: List[Dict]) -> int:
    """Index code chunks into Qdrant. Returns count indexed."""
    client = get_client()
    if not client:
        return 0

    ensure_collection()

    texts = [c["content"][:1500] for c in chunks]
    embeddings = embed_texts(texts)

    points = []
    for i, chunk in enumerate(chunks):
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.get("id", str(i))))
        points.append(PointStruct(
            id=point_id,
            vector=embeddings[i],
            payload={
                "file_path": chunk.get("file_path", ""),
                "chunk_type": chunk.get("chunk_type", ""),
                "symbol_name": chunk.get("symbol_name", ""),
                "parent_symbol": chunk.get("parent_symbol", ""),
                "content": chunk["content"][:2000],
                "language": chunk.get("language", "unknown"),
                "line_start": chunk.get("line_start", 0),
                "line_end": chunk.get("line_end", 0),
                "imports": chunk.get("imports", []),
                "repository": chunk.get("repository", ""),
                "commit_sha": chunk.get("commit_sha", ""),
                "commit_time": chunk.get("commit_time", ""),
                "indexed_at": chunk.get("indexed_at", ""),
            },
        ))

    # Batch upsert (Qdrant has a limit)
    batch_size = 100
    for i in range(0, len(points), batch_size):
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points[i:i+batch_size],
        )

    return len(points)


def search_code(
    query: str,
    repository: Optional[str] = None,
    language: Optional[str] = None,
    chunk_type: Optional[str] = None,
    symbol_name: Optional[str] = None,
    before_time: Optional[str] = None,
    limit: int = 10,
    min_score: float = 0.3,
) -> List[SearchResult]:
    """Search code embeddings with filters, including temporal filtering."""
    client = get_client()
    if not client:
        return []

    query_embedding = embed_texts([query])[0]

    # Build filter
    must_conditions = []
    if repository:
        must_conditions.append(FieldCondition(key="repository", match=MatchValue(value=repository)))
    if language:
        must_conditions.append(FieldCondition(key="language", match=MatchValue(value=language)))
    if chunk_type:
        must_conditions.append(FieldCondition(key="chunk_type", match=MatchValue(value=chunk_type)))
    if symbol_name:
        must_conditions.append(FieldCondition(key="symbol_name", match=MatchValue(value=symbol_name)))
    if before_time:
        must_conditions.append(FieldCondition(
            key="commit_time",
            range=Range(lt=before_time),
        ))

    query_filter = Filter(must=must_conditions) if must_conditions else None

    try:
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            query_filter=query_filter,
            limit=limit,
            score_threshold=min_score,
        )
    except Exception:
        return []

    search_results = []
    for hit in results:
        payload = hit.payload or {}
        search_results.append(SearchResult(
            id=hit.id,
            score=hit.score,
            file_path=payload.get("file_path", ""),
            chunk_type=payload.get("chunk_type", ""),
            symbol_name=payload.get("symbol_name"),
            content=payload.get("content", ""),
            metadata={
                "language": payload.get("language"),
                "line_start": payload.get("line_start"),
                "line_end": payload.get("line_end"),
                "imports": payload.get("imports", []),
                "repository": payload.get("repository"),
                "commit_sha": payload.get("commit_sha"),
            },
        ))

    return search_results


def search_by_symbol(symbol_name: str, repository: Optional[str] = None) -> List[SearchResult]:
    """Find exact symbol matches (function/class name)."""
    client = get_client()
    if not client:
        return []

    ensure_collection()

    must_conditions = [
        FieldCondition(key="symbol_name", match=MatchValue(value=symbol_name)),
    ]
    if repository:
        must_conditions.append(FieldCondition(key="repository", match=MatchValue(value=repository)))

    try:
        results = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(must=must_conditions),
            limit=20,
        )
    except Exception:
        return []

    search_results = []
    for point in results[0]:
        payload = point.payload or {}
        search_results.append(SearchResult(
            id=point.id,
            score=1.0,
            file_path=payload.get("file_path", ""),
            chunk_type=payload.get("chunk_type", ""),
            symbol_name=payload.get("symbol_name"),
            content=payload.get("content", ""),
            metadata={
                "language": payload.get("language"),
                "line_start": payload.get("line_start"),
                "line_end": payload.get("line_end"),
            },
        ))

    return search_results


def delete_by_repository(repository: str) -> int:
    """Delete all vectors for a repository."""
    client = get_client()
    if not client:
        return 0

    try:
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=Filter(must=[
                FieldCondition(key="repository", match=MatchValue(value=repository)),
            ]),
        )
        return 1
    except Exception:
        return 0


def get_collection_stats() -> Dict:
    """Get collection statistics."""
    client = get_client()
    if not client:
        return {"status": "disconnected", "vectors": 0}

    try:
        info = client.get_collection(COLLECTION_NAME)
        return {
            "status": "connected",
            "vectors": info.points_count or 0,
            "dimensions": info.config.params.vectors.size if info.config else 384,
            "indexed": True,
        }
    except Exception:
        return {"status": "empty", "vectors": 0}
