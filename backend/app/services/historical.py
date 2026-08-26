"""Historical incident search — Pinecone (primary) or Qdrant (fallback)."""
from typing import List, Dict, Optional
import logging

logger = logging.getLogger("sentinel.historical")

from app.services.embeddings import embed_texts, get_config
from app.core.config import settings

HISTORY_INDEX = "sentinel_incident_history"

# --- Pinecone ---
_pinecone_index = None

def _get_pinecone():
    global _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index
    if not settings.PINECONE_API_KEY:
        return None
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        _pinecone_index = pc.Index(settings.PINECONE_INDEX)
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


def index_incident(incident: Dict) -> bool:
    """Index a resolved incident for future similarity search."""
    text = f"{incident.get('title', '')} {incident.get('description', '')} {incident.get('root_cause', '')}"
    embedding = embed_texts([text])[0]

    # Try Pinecone
    index = _get_pinecone()
    if index:
        try:
            index.upsert(vectors=[{
                "id": incident["id"],
                "values": embedding,
                "metadata": {
                    "title": incident.get("title", ""),
                    "description": incident.get("description", ""),
                    "service": incident.get("service", ""),
                    "severity": incident.get("severity", ""),
                    "root_cause": incident.get("root_cause", ""),
                    "resolution": incident.get("resolution", ""),
                    "resolved_at": incident.get("resolved_at", ""),
                    "error_signature": incident.get("error_signature", ""),
                    "namespace": HISTORY_INDEX,
                },
            }])
            return True
        except Exception as e:
            logger.warning(f"Pinecone index_incident failed: {e}")

    # Fallback to Qdrant
    client = _get_qdrant()
    if client:
        try:
            from qdrant_client.models import VectorParams, Distance, PointStruct
            collections = [c.name for c in client.get_collections().collections]
            if HISTORY_INDEX not in collections:
                cfg = get_config()
                client.create_collection(
                    collection_name=HISTORY_INDEX,
                    vectors_config=VectorParams(size=cfg.dimensions, distance=Distance.COSINE),
                )
            client.upsert(
                collection_name=HISTORY_INDEX,
                points=[PointStruct(
                    id=incident["id"],
                    vector=embedding,
                    payload={
                        "title": incident.get("title", ""),
                        "description": incident.get("description", ""),
                        "service": incident.get("service", ""),
                        "severity": incident.get("severity", ""),
                        "root_cause": incident.get("root_cause", ""),
                        "resolution": incident.get("resolution", ""),
                        "resolved_at": incident.get("resolved_at", ""),
                        "error_signature": incident.get("error_signature", ""),
                    },
                )],
            )
            return True
        except Exception as e:
            logger.warning(f"Qdrant index_incident failed: {e}")

    return False


def search_similar_incidents(
    query: str,
    service: Optional[str] = None,
    limit: int = 5,
) -> List[Dict]:
    """Find similar past incidents."""
    embedding = embed_texts([query])[0]

    # Try Pinecone
    index = _get_pinecone()
    if index:
        try:
            filter_dict = {"namespace": HISTORY_INDEX}
            if service:
                filter_dict["service"] = service
            results = index.query(
                vector=embedding,
                top_k=limit,
                include_metadata=True,
                filter=filter_dict,
            )
            return [
                {
                    "id": m["id"],
                    "score": m.get("score", 0),
                    "title": m.get("metadata", {}).get("title", ""),
                    "description": m.get("metadata", {}).get("description", ""),
                    "service": m.get("metadata", {}).get("service", ""),
                    "severity": m.get("metadata", {}).get("severity", ""),
                    "root_cause": m.get("metadata", {}).get("root_cause", ""),
                    "resolution": m.get("metadata", {}).get("resolution", ""),
                    "resolved_at": m.get("metadata", {}).get("resolved_at", ""),
                }
                for m in results.get("matches", [])
            ]
        except Exception as e:
            logger.warning(f"Pinecone search failed: {e}")

    # Fallback to Qdrant
    client = _get_qdrant()
    if client:
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            must_conditions = []
            if service:
                must_conditions.append(FieldCondition(key="service", match=MatchValue(value=service)))
            query_filter = Filter(must=must_conditions) if must_conditions else None
            results = client.search(
                collection_name=HISTORY_INDEX,
                query_vector=embedding,
                query_filter=query_filter,
                limit=limit,
                score_threshold=0.3,
            )
            return [
                {
                    "id": hit.id,
                    "score": hit.score,
                    "title": hit.payload.get("title", ""),
                    "description": hit.payload.get("description", ""),
                    "service": hit.payload.get("service", ""),
                    "severity": hit.payload.get("severity", ""),
                    "root_cause": hit.payload.get("root_cause", ""),
                    "resolution": hit.payload.get("resolution", ""),
                    "resolved_at": hit.payload.get("resolved_at", ""),
                }
                for hit in results
            ]
        except Exception as e:
            logger.warning(f"Qdrant search failed: {e}")

    return []
