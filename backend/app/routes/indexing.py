"""Repository indexing — parse files, generate embeddings, index into Pinecone/Qdrant."""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime, timezone
import os
import glob as glob_module

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.incident import User, Repository as RepoModel
from app.services.code_parser import chunk_batch, detect_language
from app.services.embeddings import embed_texts
from app.services.vector_store import upsert_chunks, get_collection_stats, ensure_collection

router = APIRouter()


class IndexRequest(BaseModel):
    repo_id: Optional[str] = None
    repository: Optional[str] = None  # e.g. "owner/repo"
    file_paths: Optional[List[str]] = None
    local_path: Optional[str] = None


class IndexResponse(BaseModel):
    status: str
    files_indexed: int = 0
    chunks_indexed: int = 0
    message: str = ""


class RepoStats(BaseModel):
    vectors: int
    status: str
    dimensions: int = 384


def _read_file_safe(path: str) -> Optional[str]:
    """Read a file safely, handling encoding errors."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def _scan_directory(local_path: str, extensions: List[str] = None) -> Dict[str, str]:
    """Scan a directory and read all matching source files."""
    if extensions is None:
        extensions = [
            "*.py", "*.js", "*.ts", "*.jsx", "*.tsx",
            "*.go", "*.java", "*.rs", "*.rb", "*.php",
            "*.yaml", "*.yml", "*.json", "*.toml", "*.md",
        ]

    files = {}
    for ext in extensions:
        for file_path in glob_module.glob(os.path.join(local_path, "**", ext), recursive=True):
            # Skip common non-source directories
            skip_dirs = ["node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build"]
            if any(sd in file_path for sd in skip_dirs):
                continue
            content = _read_file_safe(file_path)
            if content and len(content) > 10:
                # Make path relative
                rel_path = os.path.relpath(file_path, local_path)
                files[rel_path] = content

    return files


async def _scan_github_repo(repository: str, branch: str = "main", github_token: str = None) -> Dict[str, str]:
    """Scan a GitHub repository and read all matching source files."""
    import logging
    logger = logging.getLogger("sentinel.indexing")
    from app.services.github import GitHubClient

    files = {}
    skip_dirs = ["node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build", "vendor"]

    if "/" not in repository:
        logger.warning(f"Invalid repository format: {repository}")
        return files

    if not github_token:
        logger.warning("No GitHub token — cannot index GitHub repository")
        return files

    client = GitHubClient(token=github_token)
    owner, repo = repository.split("/", 1)

    # Get repo tree recursively
    try:
        tree_resp = await client._client().get(f"/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
        if tree_resp.status_code != 200:
            return files
        tree = tree_resp.json()
        for item in tree.get("tree", []):
            if item["type"] != "blob":
                continue
            path = item["path"]
            # Check skip dirs
            if any(sd in path.split("/") for sd in skip_dirs):
                continue
            # Check extension
            ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if ext not in (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".json", ".yaml", ".yml", ".toml", ".md"):
                continue
            # Skip very large files (likely not code)
            if item.get("size", 0) > 500000:
                continue
            # Read file content
            try:
                file_resp = await client._client().get(f"/repos/{owner}/{repo}/contents/{path}?ref={branch}")
                if file_resp.status_code == 200:
                    file_data = file_resp.json()
                    if file_data.get("encoding") == "base64":
                        import base64
                        content = base64.b64decode(file_data["content"]).decode("utf-8", errors="replace")
                        if len(content) > 10:
                            files[path] = content
            except Exception:
                continue
    except Exception as e:
        pass

    return files


async def _index_files(
    files: Dict[str, str],
    repository: str = "",
    commit_sha: str = "",
    indexed_at: str = "",
) -> int:
    """Parse, embed, and index files into Qdrant."""
    # Parse into chunks
    chunks = chunk_batch(files)

    # Convert to dicts for upsert
    chunk_dicts = []
    for chunk in chunks:
        chunk_dicts.append({
            "id": chunk.id,
            "file_path": chunk.file_path,
            "content": chunk.content,
            "chunk_type": chunk.chunk_type,
            "symbol_name": chunk.symbol_name,
            "parent_symbol": chunk.parent_symbol,
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
            "language": chunk.language,
            "imports": chunk.imports,
            "repository": repository,
            "commit_sha": commit_sha,
            "indexed_at": indexed_at,
        })

    # Upsert to Qdrant
    return upsert_chunks(chunk_dicts)


@router.post("/index")
async def index_repository(
    request: IndexRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Index a repository (local path or GitHub) into Qdrant for search."""
    ensure_collection()

    files = {}

    if request.local_path:
        # Index from local filesystem
        files = _scan_directory(request.local_path)
    elif request.repository and "/" in request.repository:
        # Index from GitHub repository — get user's token by repo owner
        from app.models.incident import GitHubInstallation
        repo_owner = request.repository.split("/")[0]
        installation = db.query(GitHubInstallation).filter(
            GitHubInstallation.account_login == repo_owner,
        ).first()
        user_token = installation.tokens_encrypted if installation else None
        files = await _scan_github_repo(request.repository, github_token=user_token)
    elif request.file_paths:
        # Index specific files
        for fp in request.file_paths:
            content = _read_file_safe(fp)
            if content:
                files[fp] = content

    if not files:
        return IndexResponse(
            status="warning",
            files_indexed=0,
            chunks_indexed=0,
            message="No files found to index. Provide local_path, repository (owner/repo), or file_paths. For GitHub repos, ensure GITHUB_TOKEN is set in environment variables.",
        )

    # Index files
    chunks_count = await _index_files(
        files,
        repository=request.repository or "",
        indexed_at=datetime.now(timezone.utc).isoformat(),
    )

    return IndexResponse(
        status="completed",
        files_indexed=len(files),
        chunks_indexed=chunks_count,
        message=f"Indexed {len(files)} files ({chunks_count} chunks) into vector store",
    )


@router.get("/index/stats")
async def get_index_stats(
    current_user: User = Depends(get_current_user),
):
    """Get vector store statistics."""
    stats = get_collection_stats()
    return stats


@router.get("/index/search")
async def search_index(
    q: str,
    repository: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
):
    """Search the indexed codebase by semantic similarity."""
    from app.services.retrieval import hybrid_search
    results = hybrid_search(
        query=q,
        repository=repository,
        language=language,
        limit=limit,
    )
    return {
        "query": q,
        "results": [
            {
                "file": r.result.file_path,
                "symbol": r.result.symbol_name,
                "type": r.result.chunk_type,
                "score": r.result.score,
                "source": r.source,
                "reason": r.reason,
                "lines": f"{r.result.metadata.get('line_start', '?')}-{r.result.metadata.get('line_end', '?')}",
                "content_preview": r.result.content[:500],
            }
            for r in results
        ],
        "total": len(results),
    }
