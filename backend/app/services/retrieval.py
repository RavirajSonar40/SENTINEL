"""Hybrid retrieval — combines vector, keyword, and exact symbol search."""
import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from app.services.vector_store import search_code, search_by_symbol, SearchResult


@dataclass
class RetrievalResult:
    """A retrieval result with source attribution."""
    source: str  # vector, keyword, symbol, exact
    result: SearchResult
    reason: str


def hybrid_search(
    query: str,
    repository: Optional[str] = None,
    language: Optional[str] = None,
    symbol_name: Optional[str] = None,
    before_time: Optional[str] = None,
    limit: int = 10,
    min_score: float = 0.3,
) -> List[RetrievalResult]:
    """Combined search: vector similarity + exact symbol + keyword matching with temporal filtering."""
    all_results: List[RetrievalResult] = []
    seen_files = set()

    # 1. Exact symbol search (highest priority)
    if symbol_name:
        symbol_results = search_by_symbol(symbol_name, repository)
        for r in symbol_results:
            key = f"{r.file_path}:{r.symbol_name}"
            if key not in seen_files:
                seen_files.add(key)
                all_results.append(RetrievalResult(
                    source="symbol",
                    result=r,
                    reason=f"Exact symbol match: {symbol_name}",
                ))

    # 2. Vector search (with temporal filter)
    vector_results = search_code(
        query=query,
        repository=repository,
        language=language,
        before_time=before_time,
        limit=limit * 2,
        min_score=min_score,
    )
    for r in vector_results:
        key = f"{r.file_path}:{r.symbol_name}"
        if key not in seen_files:
            seen_files.add(key)
            all_results.append(RetrievalResult(
                source="vector",
                result=r,
                reason=f"Semantic similarity (score: {r.score:.3f})",
            ))

    # 3. Keyword search (extract key terms from query)
    keywords = _extract_keywords(query)
    if keywords:
        keyword_query = " ".join(keywords[:5])
        keyword_results = search_code(
            query=keyword_query,
            repository=repository,
            language=language,
            limit=limit,
            min_score=min_score * 0.8,
        )
        for r in keyword_results:
            key = f"{r.file_path}:{r.symbol_name}"
            if key not in seen_files:
                seen_files.add(key)
                all_results.append(RetrievalResult(
                    source="keyword",
                    result=r,
                    reason=f"Keyword match: {', '.join(keywords[:3])}",
                ))

    # 4. Sort by relevance: symbol > vector > keyword
    priority = {"symbol": 0, "vector": 1, "keyword": 2}
    all_results.sort(key=lambda x: (priority.get(x.source, 3), -x.result.score))

    return all_results[:limit]


def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from query text."""
    # Remove common stop words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above", "below",
        "between", "out", "off", "over", "under", "again", "further", "then",
        "once", "here", "there", "when", "where", "why", "how", "all", "both",
        "each", "few", "more", "most", "other", "some", "such", "no", "nor",
        "not", "only", "own", "same", "so", "than", "too", "very", "just",
        "don", "now", "and", "but", "or", "if", "this", "that", "these",
        "those", "it", "its", "what", "which", "who", "whom",
    }

    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)
    keywords = [w for w in words if w.lower() not in stop_words and len(w) > 2]
    return keywords


def build_context_for_investigation(
    incident_title: str,
    incident_description: str,
    error_signals: List[str],
    repository: Optional[str] = None,
    service: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a rich context for investigation from retrieval results."""
    # Combine all signals into a query
    query_parts = [incident_title, incident_description] + error_signals
    query = " ".join(query_parts)

    # Search for relevant code
    results = hybrid_search(
        query=query,
        repository=repository,
        limit=15,
        min_score=0.25,
    )

    # Group by file
    by_file: Dict[str, List] = {}
    for r in results:
        fp = r.result.file_path
        if fp not in by_file:
            by_file[fp] = []
        by_file[fp].append(r)

    # Build context
    context = {
        "query": query,
        "total_results": len(results),
        "files_explored": len(by_file),
        "results": [],
        "symbol_table": {},  # symbol name -> file locations
    }

    for fp, file_results in by_file.items():
        for r in file_results:
            entry = {
                "file": fp,
                "score": r.result.score,
                "source": r.source,
                "reason": r.reason,
                "symbol": r.result.symbol_name,
                "type": r.result.chunk_type,
                "lines": f"{r.result.metadata.get('line_start', '?')}-{r.result.metadata.get('line_end', '?')}",
                "content_preview": r.result.content[:500],
            }
            context["results"].append(entry)

            if r.result.symbol_name:
                if r.result.symbol_name not in context["symbol_table"]:
                    context["symbol_table"][r.result.symbol_name] = []
                context["symbol_table"][r.result.symbol_name].append({
                    "file": fp,
                    "lines": entry["lines"],
                    "type": r.result.chunk_type,
                })

    return context
