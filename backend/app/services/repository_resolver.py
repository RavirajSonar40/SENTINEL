"""Repository resolver — scores candidate repositories for an incident."""
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from dataclasses import dataclass
import logging
import re

from app.models.incident import (
    Incident, Repository, RepositoryScope, Deployment, Service,
)

logger = logging.getLogger("sentinel.repository_resolver")

# Scoring weights (from roadmap)
SCORE_EXPLICIT_SCOPE = 100
SCORE_SERVICE_REPO = 80
SCORE_STACK_TRACE = 70
SCORE_DEPLOYMENT = 65
SCORE_GITHUB_EVIDENCE = 50
SCORE_KEYWORD = 20
SCORE_THRESHOLD = 30


@dataclass
class RepositoryCandidate:
    repository_id: str
    repository_full_name: str
    score: int
    reasons: List[str]


def _stack_trace_paths(error_signature: Optional[str]) -> List[str]:
    """Extract file paths from an error signature or stack trace."""
    if not error_signature:
        return []
    # Match common patterns: File "/path/to/file.py", at line N
    paths = re.findall(r'(?:File\s+"|at\s+)([/\w._-]+\.\w+)', error_signature)
    # Also match Java-style: com.package.ClassName
    java_classes = re.findall(r'([\w]+\.[\w]+\.[\w]+)', error_signature)
    return paths + java_classes


def resolve_repositories(
    incident: Incident,
    db: Session,
    threshold: int = SCORE_THRESHOLD,
) -> List[RepositoryCandidate]:
    """Score all candidate repositories for an incident.

    Returns every repository above the threshold, with reasons.
    Never silently chooses only the first repository.
    """
    candidates: dict[str, RepositoryCandidate] = {}

    def _get_or_create(repo: Repository) -> RepositoryCandidate:
        key = str(repo.id)
        if key not in candidates:
            candidates[key] = RepositoryCandidate(
                repository_id=key,
                repository_full_name=repo.full_name,
                score=0,
                reasons=[],
            )
        return candidates[key]

    # --- Signal 1: Explicit incident scopes (+100) ---
    for scope in incident.scopes:
        repo = db.query(Repository).filter(Repository.id == scope.repository_id).first()
        if repo:
            c = _get_or_create(repo)
            c.score += SCORE_EXPLICIT_SCOPE
            c.reasons.append("explicit_incident_scope")

    # --- Signal 2: Service-to-repository mapping (+80) ---
    if incident.service_id:
        repos = db.query(Repository).filter(
            Repository.service_id == incident.service_id
        ).all()
        for repo in repos:
            c = _get_or_create(repo)
            c.score += SCORE_SERVICE_REPO
            c.reasons.append("service_repository_mapping")

    # --- Signal 3: Stack trace path matches repository (+70) ---
    trace_paths = _stack_trace_paths(incident.error_signature)
    if trace_paths:
        all_repos = db.query(Repository).all()
        for repo in all_repos:
            # Simple heuristic: check if any trace path component matches repo name
            repo_name_parts = set(repo.name.lower().replace("-", "_").replace(".", "_").split("_"))
            for tp in trace_paths:
                tp_parts = set(tp.lower().replace("-", "_").replace(".", "_").replace("/", "_").split("_"))
                overlap = repo_name_parts & tp_parts
                if len(overlap) >= 1:
                    c = _get_or_create(repo)
                    c.score += SCORE_STACK_TRACE
                    c.reasons.append(f"stack_trace_match({tp})")
                    break

    # --- Signal 4: Deployment belongs to repository (+65) ---
    if incident.deployment_id:
        deployment = db.query(Deployment).filter(Deployment.id == incident.deployment_id).first()
        if deployment and deployment.commit_sha:
            # Find repos that have this commit (via service mapping)
            repos = db.query(Repository).filter(
                Repository.service_id == deployment.service_id
            ).all()
            for repo in repos:
                c = _get_or_create(repo)
                c.score += SCORE_DEPLOYMENT
                c.reasons.append(f"deployment_correlation({deployment.version})")

    # --- Signal 5: Keyword & Fuzzy match on title/description (+20 to +80) ---
    import difflib
    if incident.title or incident.description:
        text = f"{incident.title or ''} {incident.description or ''}".lower()
        words = set(re.findall(r'[a-z0-9_-]{3,}', text))
        all_repos = db.query(Repository).all()
        for repo in all_repos:
            repo_name = repo.name.lower()
            repo_full = repo.full_name.lower()
            repo_parts = set(re.findall(r'[a-z0-9_-]{3,}', f"{repo_name} {repo_full}"))
            
            # Exact word match
            overlap = words & repo_parts
            if overlap:
                c = _get_or_create(repo)
                c.score += SCORE_KEYWORD * len(overlap)
                c.reasons.append(f"keyword_match({','.join(overlap)})")
            
            # Fuzzy match for typos (e.g. 'sentinle' vs 'sentinel')
            for w in words:
                for rp in repo_parts:
                    ratio = difflib.SequenceMatcher(None, w, rp).ratio()
                    if ratio >= 0.75 and ratio < 1.0:
                        c = _get_or_create(repo)
                        c.score += int(SCORE_KEYWORD * 2 * ratio)
                        c.reasons.append(f"fuzzy_repo_match({w}->{rp}:{ratio:.2f})")

    # Filter by threshold and sort
    results = [c for c in candidates.values() if c.score >= threshold]
    
    # If no candidate exceeded threshold, fall back to best matched or connected repositories
    if not results:
        if candidates:
            # Pick highest scoring candidate
            best = max(candidates.values(), key=lambda c: c.score)
            results = [best]
        else:
            # Fall back to all connected repositories
            all_repos = db.query(Repository).all()
            for r in all_repos:
                results.append(RepositoryCandidate(
                    repository_id=str(r.id),
                    repository_full_name=r.full_name,
                    score=SCORE_THRESHOLD,
                    reasons=["connected_repository_fallback"],
                ))

    results.sort(key=lambda c: c.score, reverse=True)

    logger.info(
        f"Resolved {len(results)} repositories for incident {incident.id} "
        f"(threshold={threshold}): "
        + ", ".join(f"{c.repository_full_name}={c.score}" for c in results)
    )

    return results
