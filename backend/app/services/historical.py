"""Historical incident search — find similar past incidents via Qdrant."""
from typing import List, Dict, Optional
from datetime import datetime, timezone

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance, VectorParams, PointStruct,
        Filter, FieldCondition, MatchValue,
    )
    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False

from app.services.embeddings import embed_texts, get_config
from app.core.config import settings

HISTORY_COLLECTION = "sentinel_incident_history"
QDRANT_URL = settings.QDRANT_URL

_client = None


def get_client():
    global _client
    if _client is None and HAS_QDRANT:
        try:
            _client = QdrantClient(url=QDRANT_URL, timeout=5)
        except Exception:
            _client = None
    return _client


def ensure_collection():
    client = get_client()
    if not client:
        return False
    try:
        collections = [c.name for c in client.get_collections().collections]
        if HISTORY_COLLECTION not in collections:
            cfg = get_config()
            client.create_collection(
                collection_name=HISTORY_COLLECTION,
                vectors_config=VectorParams(size=cfg.dimensions, distance=Distance.COSINE),
            )
        return True
    except Exception:
        return False


def index_incident(incident: Dict) -> bool:
    """Index a resolved incident for future similarity search."""
    client = get_client()
    if not client:
        return False
    ensure_collection()

    text = f"{incident.get('title', '')} {incident.get('description', '')} {incident.get('root_cause', '')}"
    embedding = embed_texts([text])[0]

    try:
        client.upsert(
            collection_name=HISTORY_COLLECTION,
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
    except Exception:
        return False


def search_similar_incidents(
    query: str,
    service: Optional[str] = None,
    limit: int = 5,
) -> List[Dict]:
    """Find similar past incidents."""
    client = get_client()
    if not client:
        return []

    ensure_collection()
    embedding = embed_texts([query])[0]

    must_conditions = []
    if service:
        must_conditions.append(FieldCondition(key="service", match=MatchValue(value=service)))

    query_filter = Filter(must=must_conditions) if must_conditions else None

    try:
        results = client.search(
            collection_name=HISTORY_COLLECTION,
            query_vector=embedding,
            query_filter=query_filter,
            limit=limit,
            score_threshold=0.3,
        )
    except Exception:
        return []

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
