"""Historical incident & post-mortem memory service — Canonical Pinecone with tenant isolation.

Guarantees:
- Pinecone is canonical in production.
- Production failures log errors and do NOT silently switch to Qdrant.
- Qdrant is an optional local development fallback ONLY when Pinecone is unconfigured.
- In-memory vector store is strictly for test environments.
- Every vector upsert and query strictly enforces organization_id metadata filtering.
- Indexing failures are non-blocking for live incident response.
"""
from typing import List, Dict, Optional, Any
import logging
from uuid import UUID

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
        logger.error(f"Pinecone client initialization failed: {e}")
        return None

# --- Qdrant (Development Fallback Only) ---
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

# --- In-Memory Test Store ---
_memory_store: List[Dict[str, Any]] = []


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = sum(a * a for a in v1) ** 0.5
    norm2 = sum(b * b for b in v2) ** 0.5
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def is_production_mode() -> bool:
    """Check if the service is running in production mode or with configured Pinecone."""
    env = getattr(settings, "ENVIRONMENT", "").lower()
    if env in ("testing", "test"):
        return False
    return bool(env == "production" or (settings.PINECONE_API_KEY and env != "development"))


def is_development_mode() -> bool:
    """Check if the service is explicitly in local development mode without Pinecone."""
    env = getattr(settings, "ENVIRONMENT", "").lower()
    return env == "development" and not settings.PINECONE_API_KEY


def index_post_mortem(post_mortem_dict: Dict[str, Any]) -> bool:
    """
    Index a published post-mortem into canonical vector incident memory.
    Non-blocking: returns boolean status and catches exceptions gracefully.
    """
    try:
        org_id = str(post_mortem_dict.get("organization_id", ""))
        pm_id = str(post_mortem_dict.get("id", ""))
        inc_id = str(post_mortem_dict.get("incident_id", ""))

        if not org_id or not pm_id:
            logger.warning("Cannot index post-mortem without organization_id and id")
            return False

        # Construct comprehensive semantic document
        title = post_mortem_dict.get("title", "")
        summary = post_mortem_dict.get("summary", "")
        root_cause = post_mortem_dict.get("root_cause_summary", "")
        impact = post_mortem_dict.get("impact_summary", "")
        resolution = post_mortem_dict.get("resolution_summary", "")
        lessons = " ".join([str(l.get("lesson", l) if isinstance(l, dict) else l) for l in (post_mortem_dict.get("lessons_learned_json") or [])])

        doc_text = f"Title: {title}\nSummary: {summary}\nRoot Cause: {root_cause}\nImpact: {impact}\nResolution: {resolution}\nLessons: {lessons}".strip()
        embedding = embed_texts([doc_text])[0]

        metadata = {
            "organization_id": org_id,
            "incident_id": inc_id,
            "post_mortem_id": pm_id,
            "title": title,
            "service": post_mortem_dict.get("service", ""),
            "severity": post_mortem_dict.get("severity_actual", "SEV-2"),
            "root_cause": root_cause,
            "resolution": resolution,
            "resolved_at": post_mortem_dict.get("published_at", "") or post_mortem_dict.get("signed_off_at", ""),
            "version": int(post_mortem_dict.get("version", 1)),
            "namespace": HISTORY_INDEX,
        }

        # 1. Canonical Pinecone
        if is_production_mode():
            index = _get_pinecone()
            if index:
                try:
                    index.upsert(vectors=[{
                        "id": f"pm-{pm_id}",
                        "values": embedding,
                        "metadata": metadata,
                    }])
                    logger.info(f"Successfully indexed post-mortem {pm_id} to Pinecone for tenant {org_id}")
                    return True
                except Exception as e:
                    logger.error(f"Pinecone upsert failed in production mode: {e}")
                    # Strict: In production, do NOT fall back to Qdrant
                    return False
            else:
                logger.error("Pinecone client unavailable in production mode; rejecting fallback to alternate backend")
                return False

        # 2. Development Fallback (Qdrant)
        elif is_development_mode():
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
                            id=pm_id,
                            vector=embedding,
                            payload=metadata,
                        )],
                    )
                    logger.info(f"Successfully indexed post-mortem {pm_id} to Qdrant (dev mode)")
                    return True
                except Exception as e:
                    logger.warning(f"Qdrant dev upsert failed: {e}")
                    return False
            return False

        # 3. Test In-Memory Store
        else:
            _memory_store.append({
                "id": f"pm-{pm_id}",
                "vector": embedding,
                "metadata": metadata,
            })
            return True

    except Exception as exc:
        logger.error(f"Unexpected error in index_post_mortem: {exc}")
        return False


def index_incident(incident: Dict) -> bool:
    """Index a resolved incident for future similarity search."""
    return index_post_mortem(incident)


def search_similar_incidents(
    query: str,
    organization_id: str,
    service: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Find similar historical incidents and post-mortems for an organization.
    Strictly enforces tenant isolation with organization_id filter.
    """
    if not organization_id:
        logger.warning("search_similar_incidents called without organization_id; returning empty list")
        return []

    try:
        embedding = embed_texts([query])[0]

        # 1. Canonical Pinecone
        if is_production_mode():
            index = _get_pinecone()
            if index:
                try:
                    filter_dict: Dict[str, Any] = {"organization_id": str(organization_id)}
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
                            "score": float(m.get("score", 0)),
                            "title": m.get("metadata", {}).get("title", ""),
                            "service": m.get("metadata", {}).get("service", ""),
                            "severity": m.get("metadata", {}).get("severity", ""),
                            "root_cause": m.get("metadata", {}).get("root_cause", ""),
                            "resolution": m.get("metadata", {}).get("resolution", ""),
                            "resolved_at": m.get("metadata", {}).get("resolved_at", ""),
                        }
                        for m in results.get("matches", [])
                        if m.get("metadata", {}).get("organization_id") == str(organization_id)
                    ]
                except Exception as e:
                    logger.error(f"Pinecone query failed in production mode: {e}")
                    # Strict: In production, do NOT fall back to Qdrant
                    return []
            else:
                logger.error("Pinecone unavailable in production mode; query aborted")
                return []

        # 2. Development Fallback (Qdrant)
        elif is_development_mode():
            client = _get_qdrant()
            if client:
                try:
                    from qdrant_client.models import Filter, FieldCondition, MatchValue
                    must_conditions = [
                        FieldCondition(key="organization_id", match=MatchValue(value=str(organization_id)))
                    ]
                    if service:
                        must_conditions.append(FieldCondition(key="service", match=MatchValue(value=service)))
                    
                    query_filter = Filter(must=must_conditions)
                    results = client.search(
                        collection_name=HISTORY_INDEX,
                        query_vector=embedding,
                        query_filter=query_filter,
                        limit=limit,
                        score_threshold=0.3,
                    )
                    return [
                        {
                            "id": str(hit.id),
                            "score": float(hit.score),
                            "title": hit.payload.get("title", ""),
                            "service": hit.payload.get("service", ""),
                            "severity": hit.payload.get("severity", ""),
                            "root_cause": hit.payload.get("root_cause", ""),
                            "resolution": hit.payload.get("resolution", ""),
                            "resolved_at": hit.payload.get("resolved_at", ""),
                        }
                        for hit in results
                    ]
                except Exception as e:
                    logger.warning(f"Qdrant dev search failed: {e}")
                    return []
            return []

        # 3. Test In-Memory Store
        else:
            matches = []
            for item in _memory_store:
                meta = item.get("metadata", {})
                if str(meta.get("organization_id")) != str(organization_id):
                    continue
                if service and meta.get("service") and meta.get("service") != service:
                    continue
                score = _cosine_similarity(embedding, item["vector"])
                matches.append((score, item))

            matches.sort(key=lambda x: x[0], reverse=True)
            return [
                {
                    "id": str(item["id"]),
                    "score": float(score),
                    "title": item.get("metadata", {}).get("title", ""),
                    "service": item.get("metadata", {}).get("service", ""),
                    "severity": item.get("metadata", {}).get("severity", ""),
                    "root_cause": item.get("metadata", {}).get("root_cause", ""),
                    "resolution": item.get("metadata", {}).get("resolution", ""),
                    "resolved_at": item.get("metadata", {}).get("resolved_at", ""),
                }
                for score, item in matches[:limit]
            ]

    except Exception as exc:
        logger.error(f"Unexpected error in search_similar_incidents: {exc}")
        return []
