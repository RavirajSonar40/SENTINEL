"""LLM service — abstraction layer for multiple LLM providers."""
import os
import json
import asyncio
from typing import List, Dict, Optional, Any, AsyncIterator
from dataclasses import dataclass
from enum import Enum

import httpx


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    NVIDIA = "nvidia"
    KIMI = "kimi"
    VICTOE = "victoe"
    HUGGINGFACE = "huggingface"
    OLLAMA = "ollama"
    MOCK = "mock"


@dataclass
class LLMConfig:
    provider: LLMProvider = LLMProvider.MOCK
    model: str = ""
    api_key: str = ""
    api_url: str = ""
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout: float = 60.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider = os.getenv("LLM_PROVIDER", "mock")
        api_url = os.getenv("LLM_API_URL", "") or os.getenv("LLM_BASE_URL", "")
        if not api_url and provider == "nvidia":
            api_url = "https://integrate.api.nvidia.com/v1/chat/completions"
        return cls(
            provider=LLMProvider(provider),
            model=os.getenv("LLM_MODEL", ""),
            api_key=os.getenv("LLM_API_KEY", ""),
            api_url=api_url,
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        )


@dataclass
class LLMMessage:
    role: str  # system, user, assistant
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: Dict[str, int]
    provider: str
    finish_reason: str = "stop"


# --- Provider Implementations ---

async def _call_openai(config: LLMConfig, messages: List[LLMMessage]) -> LLMResponse:
    """Call OpenAI-compatible API."""
    url = config.api_url or "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key}"}
    payload = {
        "model": config.model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }

    async with httpx.AsyncClient(timeout=config.timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    choice = data["choices"][0]
    return LLMResponse(
        content=choice["message"]["content"],
        model=data.get("model", config.model),
        usage=data.get("usage", {}),
        provider="openai",
        finish_reason=choice.get("finish_reason", "stop"),
    )


async def _call_anthropic(config: LLMConfig, messages: List[LLMMessage]) -> LLMResponse:
    """Call Anthropic API."""
    url = config.api_url or "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
    }

    # Separate system message
    system_msg = ""
    user_messages = []
    for m in messages:
        if m.role == "system":
            system_msg = m.content
        else:
            user_messages.append({"role": m.role, "content": m.content})

    payload = {
        "model": config.model,
        "messages": user_messages,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
    }
    if system_msg:
        payload["system"] = system_msg

    async with httpx.AsyncClient(timeout=config.timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    return LLMResponse(
        content=data["content"][0]["text"],
        model=data.get("model", config.model),
        usage=data.get("usage", {}),
        provider="anthropic",
    )


async def _call_kimi(config: LLMConfig, messages: List[LLMMessage]) -> LLMResponse:
    """Call Kimi/TokenRouter API (OpenAI-compatible)."""
    url = config.api_url or "https://api.tokenrouter.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key}"}
    payload = {
        "model": config.model or "kimi-k3",
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }

    async with httpx.AsyncClient(timeout=config.timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    choice = data["choices"][0]
    return LLMResponse(
        content=choice["message"]["content"],
        model=data.get("model", config.model),
        usage=data.get("usage", {}),
        provider="kimi",
    )


async def _call_ollama(config: LLMConfig, messages: List[LLMMessage]) -> LLMResponse:
    """Call Ollama local API."""
    url = config.api_url or "http://localhost:11434/api/chat"
    payload = {
        "model": config.model or "llama3",
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "stream": False,
        "options": {
            "temperature": config.temperature,
            "num_predict": config.max_tokens,
        },
    }

    async with httpx.AsyncClient(timeout=config.timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return LLMResponse(
        content=data["message"]["content"],
        model=data.get("model", config.model),
        usage={"total_tokens": data.get("eval_count", 0)},
        provider="ollama",
    )


async def _call_mock(config: LLMConfig, messages: List[LLMMessage]) -> LLMResponse:
    """Mock LLM for development/testing."""
    last_msg = messages[-1].content if messages else ""

    # Generate a realistic-looking response based on the prompt
    if "hypothesis" in last_msg.lower():
        content = json.dumps({
            "hypotheses": [
                {
                    "label": "Null pointer in request handler",
                    "description": "A recent code change may have introduced a null pointer dereference in the main request handler, causing the service to crash on specific input patterns.",
                    "confidence": "medium",
                    "category": "code_change",
                    "severity": "high",
                    "evidence_needed": ["Check recent commits touching request handlers", "Review error stack traces"],
                },
                {
                    "label": "Database connection pool exhaustion",
                    "description": "The database connection pool may be exhausted due to long-running queries or connection leaks, causing timeouts and 503 errors.",
                    "confidence": "medium",
                    "category": "infrastructure",
                    "severity": "critical",
                    "evidence_needed": ["Check database connection metrics", "Review connection pool settings"],
                },
                {
                    "label": "Memory leak in background worker",
                    "description": "A memory leak in the background worker process may be causing OOM kills, leading to service restarts and intermittent failures.",
                    "confidence": "low",
                    "category": "code_change",
                    "severity": "high",
                    "evidence_needed": ["Check memory usage over time", "Review worker process logs"],
                },
            ]
        }, indent=2)
    elif "root cause" in last_msg.lower():
        content = json.dumps({
            "root_cause": {
                "label": "Null pointer in request handler",
                "description": "A recent commit (abc123) introduced a null check that was removed from the request validation layer, causing unhandled exceptions on malformed requests.",
                "confidence": "medium",
                "category": "code_change",
                "affected_files": ["src/handlers/request.py", "src/validators/input.py"],
                "causal_chain": [
                    "Malformed request arrives at /api/endpoint",
                    "Input validator skips null check (removed in abc123)",
                    "Request handler accesses null field",
                    "Unhandled exception causes 500 error",
                ],
            }
        }, indent=2)
    elif "investigation" in last_msg.lower() or "plan" in last_msg.lower():
        content = json.dumps({
            "tasks": [
                {"tool": "search_code", "description": "Search for error patterns in the codebase", "priority": 1},
                {"tool": "search_symbol", "description": "Trace the null check function across files", "priority": 2},
                {"tool": "read_file", "description": "Read the request handler and validator files", "priority": 3},
                {"tool": "get_git_history", "description": "Check recent commits that modified the validator", "priority": 4},
                {"tool": "search_logs", "description": "Search logs for the specific error message", "priority": 5},
            ]
        }, indent=2)
    else:
        content = "I'll help you investigate this incident. Based on the error signals and codebase analysis, I recommend starting with a semantic search of the codebase to identify potential root causes."

    return LLMResponse(
        content=content,
        model="mock",
        usage={"prompt_tokens": len(last_msg), "completion_tokens": len(content)},
        provider="mock",
    )


PROVIDERS = {
    LLMProvider.OPENAI: _call_openai,
    LLMProvider.ANTHROPIC: _call_anthropic,
    LLMProvider.NVIDIA: _call_openai,
    LLMProvider.KIMI: _call_openai,
    LLMProvider.VICTOE: _call_openai,
    LLMProvider.OLLAMA: _call_ollama,
    LLMProvider.MOCK: _call_mock,
}


# --- Public API ---

_config: Optional[LLMConfig] = None


def get_config() -> LLMConfig:
    global _config
    if _config is None:
        _config = LLMConfig.from_env()
    return _config


async def chat_completion(
    messages: List[LLMMessage],
    config: Optional[LLMConfig] = None,
) -> LLMResponse:
    """Send a chat completion request."""
    cfg = config or get_config()
    provider_fn = PROVIDERS.get(cfg.provider, _call_mock)
    return await provider_fn(cfg, messages)


async def generate_text(
    system_prompt: str,
    user_prompt: str,
    config: Optional[LLMConfig] = None,
) -> str:
    """Simple text generation."""
    messages = [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt),
    ]
    response = await chat_completion(messages, config)
    return response.content


async def generate_json(
    system_prompt: str,
    user_prompt: str,
    config: Optional[LLMConfig] = None,
) -> Dict:
    """Generate JSON response from LLM."""
    messages = [
        LLMMessage(role="system", content=system_prompt + "\n\nRespond ONLY with valid JSON. No markdown, no explanation."),
        LLMMessage(role="user", content=user_prompt),
    ]
    response = await chat_completion(messages, config)
    # Try to parse JSON from response
    try:
        return json.loads(response.content)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code block
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response.content)
        if match:
            return json.loads(match.group(1))
        # Try to find JSON object or array
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", response.content)
        if match:
            return json.loads(match.group(1))
        raise ValueError(f"Failed to parse LLM response as JSON: {response.content[:200]}")
