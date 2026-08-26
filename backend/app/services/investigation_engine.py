"""Investigation engine — plans tasks, executes tools, collects evidence."""
import os
import json
import hashlib
import asyncio
from typing import List, Dict, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from app.services.code_parser import chunk_repository, CodeChunk
from app.services.retrieval import hybrid_search, build_context_for_investigation
from app.services.vector_store import upsert_chunks, search_code
from app.services.llm import generate_json, generate_text, get_config as get_llm_config


# --- Investigation State ---

@dataclass
class InvestigationState:
    incident_id: str
    incident_title: str
    incident_description: str
    error_signals: List[str] = field(default_factory=list)
    repository: Optional[str] = None
    service: Optional[str] = None
    status: str = "planning"
    tasks_completed: int = 0
    tasks_failed: int = 0
    evidence_collected: List[Dict] = field(default_factory=list)
    hypotheses_generated: List[Dict] = field(default_factory=list)
    root_cause: Optional[Dict] = None
    proposed_fixes: List[Dict] = field(default_factory=list)
    confidence: str = "low"
    abort_reason: Optional[str] = None
    error_log: List[str] = field(default_factory=list)
    github_token: Optional[str] = None


@dataclass
class InvestigationTask:
    id: str
    task_type: str
    description: str
    tool_name: str
    parameters: Dict = field(default_factory=dict)
    status: str = "pending"
    result: Optional[Dict] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2


@dataclass
class Tool:
    name: str
    description: str
    execute: Callable[..., Awaitable[Dict]]
    parameters_schema: Dict = field(default_factory=dict)


# --- Tool Definitions ---

async def tool_search_code(args: Dict) -> Dict:
    """Search codebase by semantic similarity."""
    query = args.get("query", "")
    repository = args.get("repository")
    before_time = args.get("before_time")
    results = hybrid_search(
        query=query,
        repository=repository,
        before_time=before_time,
        limit=args.get("limit", 10),
    )
    return {
        "results": [
            {
                "file": r.result.file_path,
                "symbol": r.result.symbol_name,
                "type": r.result.chunk_type,
                "score": r.result.score,
                "source": r.source,
                "content_preview": r.result.content[:500],
                "lines": f"{r.result.metadata.get('line_start', '?')}-{r.result.metadata.get('line_end', '?')}",
            }
            for r in results
        ],
        "total": len(results),
    }


async def tool_search_symbol(args: Dict) -> Dict:
    """Find where a symbol (function/class) is defined and used."""
    from app.services.vector_store import search_by_symbol
    symbol = args.get("symbol_name", "")
    repository = args.get("repository")
    results = search_by_symbol(symbol, repository)
    return {
        "symbol": symbol,
        "locations": [
            {
                "file": r.file_path,
                "type": r.chunk_type,
                "lines": f"{r.metadata.get('line_start', '?')}-{r.metadata.get('line_end', '?')}",
                "content": r.content[:1000],
            }
            for r in results
        ],
        "count": len(results),
    }


async def tool_read_file(args: Dict) -> Dict:
    """Read a file from GitHub or local workspace."""
    file_path = args.get("file_path", "")
    repository = args.get("repository", "")
    sha = args.get("sha", "master")
    github_token = args.get("_github_token")

    # Try GitHub first
    if repository and "/" in repository:
        try:
            from app.services.github import GitHubClient
            client = GitHubClient(token=github_token)
            owner, repo = repository.split("/", 1)
            content_raw = await client.get_file(owner, repo, file_path, ref=sha)
            if content_raw and "content" in content_raw:
                import base64
                content = base64.b64decode(content_raw["content"]).decode("utf-8", errors="replace")
            if content:
                return {
                    "file_path": file_path,
                    "content": content[:10000],
                    "lines": content.count("\n") + 1,
                    "truncated": len(content) > 10000,
                    "source": "github",
                }
        except Exception as e:
            pass

    # Fallback to local filesystem
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {
            "file_path": file_path,
            "content": content[:10000],
            "lines": content.count("\n") + 1,
            "truncated": len(content) > 10000,
            "source": "local",
        }
    except FileNotFoundError:
        return {"error": f"File not found: {file_path}"}
    except Exception as e:
        return {"error": str(e)}


async def tool_get_diff(args: Dict) -> Dict:
    """Get diff between commits for a file from GitHub."""
    repo = args.get("repository", "")
    sha = args.get("sha", "") or args.get("from_commit", "")
    file_path = args.get("file_path", "")
    github_token = args.get("_github_token")
    if not repo or not sha:
        return {"error": "repository and sha required"}

    try:
        from app.services.github import GitHubClient
        client = GitHubClient(token=github_token)
        parts = repo.split("/")
        if len(parts) != 2:
            return {"error": f"Invalid repo format: {repo}, expected owner/name"}
        owner, name = parts
        diff = await client.get_commit_diff(owner, name, sha)
        # Filter to specific file if requested
        if file_path:
            lines = diff.split("\n")
            filtered = []
            in_file = False
            for line in lines:
                if line.startswith("diff --git"):
                    in_file = file_path in line
                if in_file:
                    filtered.append(line)
            diff = "\n".join(filtered) if filtered else f"No changes for {file_path} in this commit"
        return {"repo": repo, "sha": sha, "file_path": file_path, "diff": diff[:5000]}
    except Exception as e:
        return {"error": str(e)[:200]}


async def tool_search_logs(args: Dict) -> Dict:
    """Search logs for error patterns (stub — requires log aggregation service)."""
    query = args.get("query", "")
    return {
        "query": query,
        "results": [],
        "note": "Log search requires integration with log aggregation (e.g., ELK, CloudWatch)",
    }


async def tool_get_dependencies(args: Dict) -> Dict:
    """Get dependency graph for a file or symbol (stub — requires AST analysis)."""
    file_path = args.get("file_path", "")
    return {
        "file_path": file_path,
        "dependencies": [],
        "dependents": [],
        "note": "Dependency analysis requires AST-based import graph",
    }


async def tool_get_git_history(args: Dict) -> Dict:
    """Get recent git history for a file from GitHub."""
    repo = args.get("repository", "")
    file_path = args.get("file_path", "")
    github_token = args.get("_github_token")
    if not repo:
        return {"error": "repository required"}

    try:
        from app.services.github import GitHubClient
        client = GitHubClient(token=github_token)
        parts = repo.split("/")
        if len(parts) != 2:
            return {"error": f"Invalid repo format: {repo}, expected owner/name"}
        owner, name = parts
        commits = await client.list_commits(owner, name)
        return {
            "repo": repo,
            "file_path": file_path,
            "commits": [
                {
                    "sha": c.get("sha", ""),
                    "message": c.get("commit", {}).get("message", "")[:200],
                    "author": c.get("commit", {}).get("author", {}).get("name", ""),
                    "date": c.get("commit", {}).get("author", {}).get("date", ""),
                }
                for c in (commits or [])[:10]
            ],
        }
    except Exception as e:
        return {"error": str(e)[:200]}


async def tool_search_historical(args: Dict) -> Dict:
    """Search for similar past incidents in Qdrant."""
    query = args.get("query", "")
    service = args.get("service", "")
    if not query:
        return {"error": "query required"}

    try:
        from app.services.historical import search_similar_incidents
        results = await search_similar_incidents(query, service_filter=service, limit=5)
        return {
            "query": query,
            "service": service,
            "incidents": [
                {
                    "id": str(r.get("incident_id", "")),
                    "title": r.get("title", ""),
                    "root_cause": r.get("root_cause_summary", ""),
                    "score": r.get("score", 0),
                }
                for r in (results or [])
            ],
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# --- Tool Registry ---

TOOLS: Dict[str, Tool] = {
    "search_code": Tool(
        name="search_code",
        description="Search codebase by semantic similarity to find relevant functions, classes, or logic",
        execute=tool_search_code,
        parameters_schema={
            "query": {"type": "string", "description": "Search query"},
            "repository": {"type": "string", "description": "Repository filter"},
            "before_time": {"type": "string", "description": "ISO timestamp to filter commits before this time (deployment window)"},
            "limit": {"type": "integer", "description": "Max results"},
        },
    ),
    "search_symbol": Tool(
        name="search_symbol",
        description="Find where a specific function, class, or variable is defined and used",
        execute=tool_search_symbol,
        parameters_schema={
            "symbol_name": {"type": "string", "description": "Symbol name to search"},
            "repository": {"type": "string", "description": "Repository filter"},
        },
    ),
    "read_file": Tool(
        name="read_file",
        description="Read the contents of a specific file",
        execute=tool_read_file,
        parameters_schema={
            "file_path": {"type": "string", "description": "File path to read"},
        },
    ),
    "get_diff": Tool(
        name="get_diff",
        description="Get changes made to a file between commits",
        execute=tool_get_diff,
        parameters_schema={
            "file_path": {"type": "string", "description": "File path"},
            "from_commit": {"type": "string", "description": "From commit SHA"},
            "to_commit": {"type": "string", "description": "To commit SHA"},
        },
    ),
    "search_logs": Tool(
        name="search_logs",
        description="Search application logs for error messages or patterns",
        execute=tool_search_logs,
        parameters_schema={
            "query": {"type": "string", "description": "Log search query"},
        },
    ),
    "get_dependencies": Tool(
        name="get_dependencies",
        description="Get the dependency graph for a file or module",
        execute=tool_get_dependencies,
        parameters_schema={
            "file_path": {"type": "string", "description": "File path to analyze"},
        },
    ),
    "get_git_history": Tool(
        name="get_git_history",
        description="Get recent git commits that modified a file",
        execute=tool_get_git_history,
        parameters_schema={
            "file_path": {"type": "string", "description": "File path"},
            "repository": {"type": "string", "description": "Repository (owner/name)"},
        },
    ),
    "search_historical": Tool(
        name="search_historical",
        description="Search for similar past incidents to find patterns and previous solutions",
        execute=tool_search_historical,
        parameters_schema={
            "query": {"type": "string", "description": "Search query"},
            "service": {"type": "string", "description": "Service name filter"},
        },
    ),
}


# --- Task Planning (LLM-powered) ---

async def generate_tasks_llm(state: InvestigationState) -> List[InvestigationTask]:
    """Use LLM to generate investigation plan based on incident."""
    system_prompt = """You are an incident investigation planner. Given an incident, generate a list of investigation tasks.

Available tools:
- search_code: Search codebase by semantic similarity (params: query, repository, before_time, limit)
- search_symbol: Find where a symbol is defined/used (params: symbol_name, repository)
- read_file: Read file contents (params: file_path)
- get_diff: Get changes between commits (params: file_path, sha, repository)
- search_logs: Search application logs (params: query)
- get_dependencies: Get dependency graph (params: file_path)
- get_git_history: Get recent commits (params: file_path, repository)
- search_historical: Search similar past incidents (params: query, service)

Use before_time (ISO timestamp) to filter code search to commits before the deployment/incident time.
This narrows results to code that existed when the incident occurred.

Respond with JSON array of tasks, each with:
- tool: tool name
- description: what this task investigates
- params: parameters for the tool
- priority: 1 (highest) to 5 (lowest)

Generate 4-8 focused tasks. Always start with search_code for the main error, then dig deeper."""

    user_prompt = f"""Incident: {state.incident_title}
Description: {state.incident_description}
Error signals: {', '.join(state.error_signals[:5]) if state.error_signals else 'None'}
Service: {state.service or 'Unknown'}
Repository: {state.repository or 'Unknown'}"""

    try:
        result = await generate_json(system_prompt, user_prompt)
        tasks = []
        task_list = result.get("tasks", result) if isinstance(result, dict) else result
        if isinstance(task_list, list):
            for i, task_data in enumerate(task_list):
                tool_name = task_data.get("tool", "search_code")
                tasks.append(InvestigationTask(
                    id=f"task_{i}",
                    task_type=tool_name.replace("search_", "").replace("get_", ""),
                    description=task_data.get("description", ""),
                    tool_name=tool_name,
                    parameters=task_data.get("params", {}),
                ))
            return tasks
    except Exception as e:
        print(f"LLM planning failed, falling back to defaults: {e}")

    # Fallback to default tasks
    return _generate_default_tasks(state)


def _generate_default_tasks(state: InvestigationState) -> List[InvestigationTask]:
    """Fallback task generation when LLM fails."""
    tasks = []
    task_id = 0

    tasks.append(InvestigationTask(
        id=f"task_{task_id}", task_type="search", description="Search codebase for error patterns",
        tool_name="search_code",
        parameters={"query": f"{state.incident_title} {state.incident_description}", "repository": state.repository, "limit": 15},
    ))
    task_id += 1

    if state.error_signals:
        tasks.append(InvestigationTask(
            id=f"task_{task_id}", task_type="search", description="Search for specific error messages",
            tool_name="search_code",
            parameters={"query": " ".join(state.error_signals[:3]), "repository": state.repository, "limit": 10},
        ))
        task_id += 1

    keywords = [w for w in state.incident_title.lower().split() if len(w) > 3][:5]
    if keywords:
        tasks.append(InvestigationTask(
            id=f"task_{task_id}", task_type="search", description="Search for related components",
            tool_name="search_code",
            parameters={"query": " ".join(keywords), "repository": state.repository, "limit": 10},
        ))
        task_id += 1

    tasks.append(InvestigationTask(
        id=f"task_{task_id}", task_type="history", description="Check recent commits",
        tool_name="get_git_history",
        parameters={"repository": state.repository},
    ))
    task_id += 1

    return tasks

    return tasks


# --- Execution ---

async def execute_task(task: InvestigationTask) -> Dict:
    """Execute a single investigation task with exponential backoff retries."""
    import asyncio as _asyncio

    tool = TOOLS.get(task.tool_name)
    if not tool:
        task.status = "failed"
        task.error = f"Unknown tool: {task.tool_name}"
        return {"error": task.error}

    for attempt in range(task.max_retries + 1):
        try:
            result = await tool.execute(task.parameters)
            task.status = "completed"
            task.result = result
            return result
        except Exception as e:
            task.retry_count = attempt + 1
            task.error = str(e)
            if attempt >= task.max_retries:
                task.status = "failed"
                return {"error": str(e)}
            # Exponential backoff: 1s, 2s, 4s, ...
            delay = min(2 ** attempt, 10)
            await _asyncio.sleep(delay)

    return {"error": task.error}


async def run_investigation(state: InvestigationState, db=None, investigation_id=None, github_token: str = None) -> InvestigationState:
    """Run a full investigation from planning through execution.

    When db and investigation_id are provided, each task is persisted to the
    investigation_tasks table as it transitions through states.
    """
    from app.models.incident import InvestigationTask as InvestigationTaskModel, TaskStatus

    state.status = "planning"

    # 1. Plan tasks (LLM-powered)
    tasks = await generate_tasks_llm(state)

    # Inject user's GitHub token into tool parameters for GitHub-dependent tools
    if github_token:
        state.github_token = github_token
        for task in tasks:
            if task.tool_name in ("read_file", "get_git_history", "get_diff", "search_code"):
                task.parameters["_github_token"] = github_token

    # Persist planned tasks to DB
    db_task_map = {}  # in-memory task id -> DB row
    if db and investigation_id:
        for idx, task in enumerate(tasks):
            db_task = InvestigationTaskModel(
                id=uuid4(),
                investigation_id=investigation_id,
                task_type=task.task_type,
                description=task.description,
                status=TaskStatus.PENDING.value,
                order=idx,
                tool_name=task.tool_name,
                tool_input=task.parameters,
                max_attempts=task.max_retries + 1,
            )
            db.add(db_task)
            db_task_map[task.id] = db_task
        db.flush()

    # 2. Execute tasks in parallel batches
    state.status = "investigating"
    search_tasks = [t for t in tasks if t.task_type in ("search", "symbol", "code", "logs")]
    other_tasks = [t for t in tasks if t.task_type not in ("search", "symbol", "code", "logs")]

    # Mark search tasks as running
    if db and investigation_id:
        for task in search_tasks:
            if task.id in db_task_map:
                db_task_map[task.id].status = TaskStatus.RUNNING.value
                db_task_map[task.id].started_at = datetime.now(timezone.utc)
        db.flush()

    # Execute search tasks first (parallel)
    search_results = await asyncio.gather(
        *[execute_task(t) for t in search_tasks],
        return_exceptions=True,
    )

    # Persist search task results
    if db and investigation_id:
        for task, result in zip(search_tasks, search_results):
            if task.id in db_task_map:
                db_task = db_task_map[task.id]
                db_task.attempt = task.retry_count
                if isinstance(result, Exception):
                    db_task.status = TaskStatus.FAILED.value
                    db_task.error_message = str(result)
                else:
                    db_task.status = TaskStatus.COMPLETED.value
                    db_task.tool_output = result if isinstance(result, dict) else {"result": str(result)}
                db_task.completed_at = datetime.now(timezone.utc)
        db.flush()

    # Collect evidence from search results
    for i, (task, result) in enumerate(zip(search_tasks, search_results)):
        if isinstance(result, Exception):
            state.tasks_failed += 1
            state.error_log.append(f"Task {task.id} failed: {result}")
        else:
            state.tasks_completed += 1
            if isinstance(result, dict) and "results" in result:
                for item in result["results"]:
                    state.evidence_collected.append({
                        "source": "code_search",
                        "tool": task.tool_name,
                        "file": item.get("file"),
                        "symbol": item.get("symbol"),
                        "type": item.get("type"),
                        "score": item.get("score"),
                        "content_preview": item.get("content_preview", "")[:500],
                    })

    # Update tasks that depend on search results
    for task in other_tasks:
        if task.tool_name == "read_file" and not task.parameters.get("file_path"):
            if state.evidence_collected:
                task.parameters["file_path"] = state.evidence_collected[0].get("file", "")
        if task.tool_name == "get_git_history" and not task.parameters.get("file_path"):
            if state.evidence_collected:
                task.parameters["file_path"] = state.evidence_collected[0].get("file", "")

    # Mark remaining tasks as running
    if db and investigation_id:
        for task in other_tasks:
            if task.id in db_task_map:
                db_task_map[task.id].status = TaskStatus.RUNNING.value
                db_task_map[task.id].started_at = datetime.now(timezone.utc)
                db_task_map[task.id].tool_input = task.parameters
        db.flush()

    # Execute remaining tasks (parallel)
    remaining_results = await asyncio.gather(
        *[execute_task(t) for t in other_tasks],
        return_exceptions=True,
    )

    # Persist remaining task results
    if db and investigation_id:
        for task, result in zip(other_tasks, remaining_results):
            if task.id in db_task_map:
                db_task = db_task_map[task.id]
                db_task.attempt = task.retry_count
                if isinstance(result, Exception):
                    db_task.status = TaskStatus.FAILED.value
                    db_task.error_message = str(result)
                else:
                    db_task.status = TaskStatus.COMPLETED.value
                    db_task.tool_output = result if isinstance(result, dict) else {"result": str(result)}
                db_task.completed_at = datetime.now(timezone.utc)
        db.flush()

    for task, result in zip(other_tasks, remaining_results):
        if isinstance(result, Exception):
            state.tasks_failed += 1
        else:
            state.tasks_completed += 1

    # 3. Assess confidence
    total = state.tasks_completed + state.tasks_failed
    if total > 0:
        success_rate = state.tasks_completed / total
        if success_rate >= 0.8 and len(state.evidence_collected) >= 5:
            state.confidence = "high"
        elif success_rate >= 0.5 and len(state.evidence_collected) >= 2:
            state.confidence = "medium"
        else:
            state.confidence = "low"

    state.status = "evidence_collected"
    return state
