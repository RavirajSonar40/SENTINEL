"""Embedding service — generate vectors for code/text using local or API embeddings."""
import os
from typing import List, Optional
from dataclasses import dataclass

# Lazy imports for optional dependencies
_embedding_client = None


@dataclass
class EmbeddingConfig:
    provider: str = "local"  # local, openai, huggingface, kimi
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    dimensions: int = 384
    api_key: Optional[str] = None
    api_url: Optional[str] = None


# Default config — uses sentence-transformers locally if available, else mock
_config = EmbeddingConfig(
    provider=os.getenv("EMBEDDING_PROVIDER", "local"),
    model=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
    dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "384")),
    api_key=os.getenv("EMBEDDING_API_KEY"),
    api_url=os.getenv("EMBEDDING_API_URL"),
)


def _get_local_model():
    """Load sentence-transformers model lazily."""
    global _embedding_client
    if _embedding_client is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_client = SentenceTransformer(_config.model)
        except ImportError:
            _embedding_client = None
    return _embedding_client


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for a list of texts."""
    if _config.provider == "local":
        model = _get_local_model()
        if model:
            embeddings = model.encode(texts, normalize_embeddings=True)
            return embeddings.tolist()
        # Fallback: deterministic pseudo-embeddings based on text hash
        import hashlib
        import struct
        result = []
        for text in texts:
            h = hashlib.sha512(text.encode()).digest()
            vec = []
            for i in range(0, len(h), 4):
                if len(vec) >= _config.dimensions:
                    break
                val = struct.unpack("f", h[i:i+4])[0]
                # Normalize to [-1, 1]
                val = max(-1.0, min(1.0, val / 100.0))
                vec.append(val)
            # Pad if needed
            while len(vec) < _config.dimensions:
                vec.append(0.0)
            result.append(vec[:_config.dimensions])
        return result

    elif _config.provider == "openai":
        import httpx
        resp = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {_config.api_key}"},
            json={"model": _config.model, "input": texts},
        )
        resp.raise_for_status()
        return [item["embedding"] for item in resp.json()["data"]]

    elif _config.provider == "huggingface":
        import httpx
        url = _config.api_url or "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {_config.api_key}"},
            json={"inputs": texts},
        )
        resp.raise_for_status()
        return resp.json()

    # Default: return random vectors (for development)
    import random
    return [[random.random() for _ in range(_config.dimensions)] for _ in texts]


def embed_single(text: str) -> List[float]:
    """Generate embedding for a single text."""
    return embed_texts([text])[0]


def get_config() -> EmbeddingConfig:
    return _config
