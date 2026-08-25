"""Investigation engine — plans tasks, executes tools, collects evidence."""
import os
import json
import hashlib
import asyncio
from typing import List, Dict, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
    results = hybrid_search(
        query=query,
        repository=repository,
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
    """Read a file from the workspace."""
    file_path = args.get("file_path", "")
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {
            "file_path": file_path,
            "content": content[:10000],
            "lines": content.count("\n") + 1,
            "truncated": len(content) > 10000,
        }
    except FileNotFoundError:
        return {"error": f"File not found: {file_path}"}
    except Exception as e:
        return {"error": str(e)}


async def tool_get_diff(args: Dict) -> Dict:
    """Get diff between commits for a file."""
    # Placeholder — would call GitHub API in real implementation
    file_path = args.get("file_path", "")
    return {
        "file_path": file_path,
        "diff": "Diff retrieval requires GitHub integration",
        "note": "Use /api/github/repos/{owner}/{repo}/commits/{sha} for real diffs",
    }


async def tool_search_logs(args: Dict) -> Dict:
    """Search logs for error patterns."""
    query = args.get("query", "")
    # Placeholder — would connect to log aggregation service
    return {
        "query": query,
        "results": [],
        "note": "Log search not yet connected",
    }


async def tool_get_dependencies(args: Dict) -> Dict:
    """Get dependency graph for a file or symbol."""
    file_path = args.get("file_path", "")
    # Placeholder — would analyze import graph
    return {
        "file_path": file_path,
        "dependencies": [],
        "dependents": [],
        "note": "Dependency analysis not yet implemented",
    }


async def tool_get_git_history(args: Dict) -> Dict:
    """Get recent git history for a file or service."""
    file_path = args.get("file_path", "")
    # Placeholder — would call GitHub API
    return {
        "file_path": file_path,
        "commits": [],
        "note": "Git history requires GitHub integration",
    }


# --- Tool Registry ---

TOOLS: Dict[str, Tool] = {
    "search_code": Tool(
        name="search_code",
        description="Search codebase by semantic similarity to find relevant functions, classes, or logic",
        execute=tool_search_code,
        parameters_schema={
            "query": {"type": "string", "description": "Search query"},
            "repository": {"type": "string", "description": "Repository filter"},
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
        },
    ),
}


# --- Task Planning (LLM-powered) ---

async def generate_tasks_llm(state: InvestigationState) -> List[InvestigationTask]:
    """Use LLM to generate investigation plan based on incident."""
    system_prompt = """You are an incident investigation planner. Given an incident, generate a list of investigation tasks.

Available tools:
- search_code: Search codebase by semantic similarity (params: query, repository, limit)
- search_symbol: Find where a symbol is defined/used (params: symbol_name, repository)
- read_file: Read file contents (params: file_path)
- get_diff: Get changes between commits (params: file_path, from_commit, to_commit)
- search_logs: Search application logs (params: query)
- get_dependencies: Get dependency graph (params: file_path)
- get_git_history: Get recent commits (params: file_path)

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
    tasks.append(InvestigationTask(
        id="task_0", task_type="search", description="Search codebase for error patterns",
        tool_name="search_code",
        parameters={"query": f"{state.incident_title} {state.incident_description}", "repository": state.repository, "limit": 15},
    ))
    if state.error_signals:
        tasks.append(InvestigationTask(
            id="task_1", task_type="search", description="Search for specific error messages",
            tool_name="search_code",
            parameters={"query": " ".join(state.error_signals[:3]), "repository": state.repository, "limit": 10},
        ))
    return tasks

    # Read files that were found
    tasks.append(InvestigationTask(
        id=f"task_{task_id}",
        task_type="read",
        description="Read key files for context",
        tool_name="read_file",
        parameters={"file_path": ""},  # Will be filled after search
    ))
    task_id += 1

    # Get git history for relevant files
    tasks.append(InvestigationTask(
        id=f"task_{task_id}",
        task_type="history",
        description="Check recent changes to relevant files",
        tool_name="get_git_history",
        parameters={"file_path": ""},  # Will be filled after search
    ))
    task_id += 1

    # Search logs
    tasks.append(InvestigationTask(
        id=f"task_{task_id}",
        task_type="logs",
        description="Search logs for related errors",
        tool_name="search_logs",
        parameters={"query": state.incident_title},
    ))
    task_id += 1

    return tasks


# --- Execution ---

async def execute_task(task: InvestigationTask) -> Dict:
    """Execute a single investigation task with retries."""
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

    return {"error": task.error}


async def run_investigation(state: InvestigationState) -> InvestigationState:
    """Run a full investigation from planning through execution."""
    state.status = "planning"

    # 1. Plan tasks (LLM-powered)
    tasks = await generate_tasks_llm(state)

    # 2. Execute tasks in parallel batches
    state.status = "investigating"
    search_tasks = [t for t in tasks if t.task_type in ("search", "symbol", "code", "logs")]
    other_tasks = [t for t in tasks if t.task_type not in ("search", "symbol", "code", "logs")]

    # Execute search tasks first (parallel)
    search_results = await asyncio.gather(
        *[execute_task(t) for t in search_tasks],
        return_exceptions=True,
    )

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

    # Execute remaining tasks (parallel)
    remaining_results = await asyncio.gather(
        *[execute_task(t) for t in other_tasks],
        return_exceptions=True,
    )

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
