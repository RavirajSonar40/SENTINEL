"""Vector store — Pinecone (primary) or Qdrant (fallback) for code embeddings."""
import uuid
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger("sentinel.vector_store")

from app.services.embeddings import embed_texts, get_config
from app.core.config import settings

# --- Pinecone ---
_pinecone_client = None
_pinecone_index = None

def _get_pinecone():
    global _pinecone_client, _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index
    if not settings.PINECONE_API_KEY:
        return None
    try:
        from pinecone import Pinecone
        _pinecone_client = Pinecone(api_key=settings.PINECONE_API_KEY)
        _pinecone_index = _pinecone_client.Index(settings.PINECONE_INDEX)
        return _pinecone_index
    except Exception as e:
        logger.warning(f"Pinecone init failed: {e}")
        return None

# --- Qdrant (fallback) ---
_qdrant_client = None

def _get_qdrant():
    global _qdrant_client
    if _qdrant_client is not None:
        return _qdrant_client
    try:
        from qdrant_client import QdrantClient
        _qdrant_client = QdrantClient(url=settings.QDRANT_URL, timeout=5)
        return _qdrant_client
    except Exception:
        return None


@dataclass
class SearchResult:
    id: str
    score: float
    file_path: str
    chunk_type: str
    symbol_name: Optional[str]
    content: str
    metadata: Dict[str, Any]


CODE_INDEX = "sentinel_code"


def ensure_collection():
    """Ensure the vector index/collection exists."""
    index = _get_pinecone()
    if index:
        return True  # Pinecone auto-creates indexes

    client = _get_qdrant()
    if client:
        try:
            from qdrant_client.models import VectorParams, Distance
            collections = [c.name for c in client.get_collections().collections]
            if CODE_INDEX not in collections:
                cfg = get_config()
                client.create_collection(
                    collection_name=CODE_INDEX,
                    vectors_config=VectorParams(size=cfg.dimensions, distance=Distance.COSINE),
                )
            return True
        except Exception:
            pass
    return False


# --- In-Memory Fallback ---
_memory_store: List[Dict[str, Any]] = []

def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = sum(a * a for a in v1) ** 0.5
    norm2 = sum(b * b for b in v2) ** 0.5
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def upsert_chunks(chunks: List[Dict]) -> int:
    """Index code chunks. Returns count indexed."""
    if not chunks:
        return 0

    # Compute embeddings
    texts = [c["content"][:1500] for c in chunks]
    embeddings = embed_texts(texts)

    # Try Pinecone first (with calculated embeddings)
    index = _get_pinecone()
    if index:
        try:
            vectors = []
            for i, chunk in enumerate(chunks):
                vectors.append({
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.get("id", str(i)))),
                    "values": embeddings[i],
                    "metadata": {
                        "file_path": chunk.get("file_path", ""),
                        "chunk_type": chunk.get("chunk_type", ""),
                        "symbol_name": chunk.get("symbol_name", "") or "",
                        "content": chunk["content"][:2000],
                        "language": chunk.get("language", "unknown"),
                        "line_start": chunk.get("line_start", 0),
                        "line_end": chunk.get("line_end", 0),
                        "repository": chunk.get("repository", ""),
                        "commit_sha": chunk.get("commit_sha", ""),
                        "commit_time": chunk.get("commit_time", ""),
                        "namespace": CODE_INDEX,
                    },
                })
            for i in range(0, len(vectors), 100):
                index.upsert(vectors=vectors[i:i+100])
            return len(vectors)
        except Exception as e:
            logger.warning(f"Pinecone upsert failed: {e}")

    # Fallback to Qdrant
    client = _get_qdrant()
    if client:
        try:
            from qdrant_client.models import VectorParams, Distance, PointStruct
            collections = [c.name for c in client.get_collections().collections]
            if CODE_INDEX not in collections:
                cfg = get_config()
                client.create_collection(
                    collection_name=CODE_INDEX,
                    vectors_config=VectorParams(size=cfg.dimensions, distance=Distance.COSINE),
                )
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
                        "content": chunk["content"][:2000],
                        "language": chunk.get("language", "unknown"),
                        "line_start": chunk.get("line_start", 0),
                        "line_end": chunk.get("line_end", 0),
                        "repository": chunk.get("repository", ""),
                        "commit_sha": chunk.get("commit_sha", ""),
                        "commit_time": chunk.get("commit_time", ""),
                    },
                ))
            for i in range(0, len(points), 100):
                client.upsert(collection_name=CODE_INDEX, points=points[i:i+100])
            return len(points)
        except Exception as e:
            logger.warning(f"Qdrant upsert failed: {e}")

    # In-memory fallback (local development / testing)
    global _memory_store
    for i, chunk in enumerate(chunks):
        _memory_store.append({
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.get("id", str(i)))),
            "vector": embeddings[i],
            "chunk": chunk,
        })
    return len(chunks)


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
    """Search code embeddings with filters."""
    query_embedding = embed_texts([query])[0]

    # Try Pinecone first
    index = _get_pinecone()
    if index:
        try:
            filter_dict = {"namespace": CODE_INDEX}
            if repository:
                filter_dict["repository"] = repository
            if language:
                filter_dict["language"] = language
            if chunk_type:
                filter_dict["chunk_type"] = chunk_type
            if symbol_name:
                filter_dict["symbol_name"] = symbol_name

            results = index.query(
                vector=query_embedding,
                top_k=limit,
                include_metadata=True,
                filter=filter_dict,
            )
            search_results = []
            for match in results.get("matches", []):
                if match.get("score", 0) < min_score:
                    continue
                meta = match.get("metadata", {})
                search_results.append(SearchResult(
                    id=match["id"],
                    score=match["score"],
                    file_path=meta.get("file_path", ""),
                    chunk_type=meta.get("chunk_type", ""),
                    symbol_name=meta.get("symbol_name"),
                    content=meta.get("content", ""),
                    metadata={
                        "language": meta.get("language"),
                        "line_start": meta.get("line_start"),
                        "line_end": meta.get("line_end"),
                        "repository": meta.get("repository"),
                        "commit_sha": meta.get("commit_sha"),
                    },
                ))
            return search_results
        except Exception as e:
            logger.warning(f"Pinecone search failed: {e}")

    # Fallback to Qdrant
    client = _get_qdrant()
    if client:
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue, Range
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
                must_conditions.append(FieldCondition(key="commit_time", range=Range(lt=before_time)))

            query_filter = Filter(must=must_conditions) if must_conditions else None
            results = client.search(
                collection_name=CODE_INDEX,
                query_vector=query_embedding,
                query_filter=query_filter,
                limit=limit,
                score_threshold=min_score,
            )
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
                        "repository": payload.get("repository"),
                        "commit_sha": payload.get("commit_sha"),
                    },
                ))
            return search_results
        except Exception as e:
            logger.warning(f"Qdrant search failed: {e}")

    # In-memory search fallback
    if _memory_store:
        scored = []
        for item in _memory_store:
            chunk = item["chunk"]
            if repository and chunk.get("repository") and repository not in chunk.get("repository", ""):
                continue
            if language and chunk.get("language") != language:
                continue
            if chunk_type and chunk.get("chunk_type") != chunk_type:
                continue
            if symbol_name and chunk.get("symbol_name") != symbol_name:
                continue
            score = _cosine_similarity(query_embedding, item["vector"])
            if score >= min_score:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SearchResult(
                id=item["id"],
                score=score,
                file_path=item["chunk"].get("file_path", ""),
                chunk_type=item["chunk"].get("chunk_type", ""),
                symbol_name=item["chunk"].get("symbol_name"),
                content=item["chunk"].get("content", ""),
                metadata={
                    "language": item["chunk"].get("language"),
                    "line_start": item["chunk"].get("line_start"),
                    "line_end": item["chunk"].get("line_end"),
                    "repository": item["chunk"].get("repository"),
                    "commit_sha": item["chunk"].get("commit_sha"),
                },
            )
            for score, item in scored[:limit]
        ]

    return []


def search_by_symbol(symbol_name: str, repository: Optional[str] = None) -> List[SearchResult]:
    """Find exact symbol matches."""
    index = _get_pinecone()
    if index:
        try:
            filter_dict = {"namespace": CODE_INDEX, "symbol_name": symbol_name}
            if repository:
                filter_dict["repository"] = repository
            results = index.query(
                vector=[0.0] * get_config().dimensions,
                top_k=20,
                include_metadata=True,
                filter=filter_dict,
            )
            return [
                SearchResult(
                    id=m["id"], score=m.get("score", 1.0),
                    file_path=m.get("metadata", {}).get("file_path", ""),
                    chunk_type=m.get("metadata", {}).get("chunk_type", ""),
                    symbol_name=symbol_name,
                    content=m.get("metadata", {}).get("content", ""),
                    metadata={"language": m.get("metadata", {}).get("language")},
                )
                for m in results.get("matches", [])
            ]
        except Exception:
            pass

    client = _get_qdrant()
    if client:
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            must = [FieldCondition(key="symbol_name", match=MatchValue(value=symbol_name))]
            if repository:
                must.append(FieldCondition(key="repository", match=MatchValue(value=repository)))
            results, _ = client.scroll(
                collection_name=CODE_INDEX,
                scroll_filter=Filter(must=must),
                limit=20,
            )
            return [
                SearchResult(
                    id=p.id, score=1.0,
                    file_path=(p.payload or {}).get("file_path", ""),
                    chunk_type=(p.payload or {}).get("chunk_type", ""),
                    symbol_name=symbol_name,
                    content=(p.payload or {}).get("content", ""),
                    metadata={"language": (p.payload or {}).get("language")},
                )
                for p in results
            ]
        except Exception:
            pass

    if _memory_store:
        matches = []
        for item in _memory_store:
            chunk = item["chunk"]
            if chunk.get("symbol_name") == symbol_name:
                if not repository or repository in chunk.get("repository", ""):
                    matches.append(SearchResult(
                        id=item["id"],
                        score=1.0,
                        file_path=chunk.get("file_path", ""),
                        chunk_type=chunk.get("chunk_type", ""),
                        symbol_name=symbol_name,
                        content=chunk.get("content", ""),
                        metadata={"language": chunk.get("language")},
                    ))
        return matches[:20]

    return []


def delete_by_repository(repository: str) -> int:
    """Delete all vectors for a repository."""
    index = _get_pinecone()
    if index:
        try:
            index.delete(filter={"namespace": CODE_INDEX, "repository": repository})
            return 1
        except Exception:
            pass

    client = _get_qdrant()
    if client:
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            client.delete(
                collection_name=CODE_INDEX,
                points_selector=Filter(must=[
                    FieldCondition(key="repository", match=MatchValue(value=repository)),
                ]),
            )
            return 1
        except Exception:
            pass

    global _memory_store
    initial_len = len(_memory_store)
    _memory_store = [m for m in _memory_store if repository not in m["chunk"].get("repository", "")]
    return initial_len - len(_memory_store)


def get_collection_stats() -> Dict:
    """Get collection statistics."""
    index = _get_pinecone()
    if index:
        try:
            stats = index.describe_index_stats()
            return {
                "status": "connected",
                "provider": "pinecone",
                "vectors": stats.get("total_vector_count", 0),
                "dimensions": stats.get("dimension", 384),
                "indexed": True,
            }
        except Exception:
            pass

    client = _get_qdrant()
    if client:
        try:
            info = client.get_collection(CODE_INDEX)
            return {
                "status": "connected",
                "provider": "qdrant",
                "vectors": info.points_count or 0,
                "dimensions": info.config.params.vectors.size if info.config else 384,
                "indexed": True,
            }
        except Exception:
            pass

    if _memory_store:
        return {
            "status": "connected",
            "provider": "local_memory",
            "vectors": len(_memory_store),
            "dimensions": 384,
            "indexed": True,
        }

    return {"status": "disconnected", "vectors": 0}
