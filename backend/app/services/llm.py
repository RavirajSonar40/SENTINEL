"""LLM service — abstraction layer for multiple LLM providers.

Implements Phase 1 of the Sentinel Build Execution Plan:
- Nemotron-compatible AI provider support (OpenAI-compatible protocol)
- Structured error hierarchy
- Response metadata (request_id, tokens, latency, finish_reason)
- Backward-compatible public API (generate_text, generate_json, generate_json_response)
- Defensive JSON extraction with Pydantic/schema validation and 1x repair retry
- In-memory bounded TTL cache for cost and latency control
- Mock provider isolation with strict validation
"""
import os
import json
import time
import hashlib
import logging
import asyncio
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

import httpx

logger = logging.getLogger("sentinel.llm")


# --- Error Hierarchy ---

class LLMError(Exception):
    """Base exception for all LLM service errors."""
    pass


class LLMConfigurationError(LLMError):
    """Raised when provider configuration is missing required parameters or invalid."""
    pass


class LLMProviderError(LLMError):
    """Raised when an upstream provider returns an error."""
    def __init__(self, message: str, status_code: Optional[int] = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class LLMTimeoutError(LLMProviderError):
    """Raised when upstream API request times out."""
    pass


class LLMAuthenticationError(LLMProviderError):
    """Raised on 401/403 unauthorized or invalid API credentials."""
    pass


class LLMRateLimitError(LLMProviderError):
    """Raised on 429 rate limit exceeded."""
    pass


class LLMStructuredOutputError(LLMError):
    """Raised when response fails JSON parsing or schema validation after repair attempt."""
    pass


# --- Provider Enums and Configuration ---

class LLMProvider(str, Enum):
    NEMOTRON = "nemotron"
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
    base_url: str = ""
    api_url: str = ""  # Legacy alias
    temperature: float = 0.3
    max_tokens: int = 4000
    timeout: float = 60.0
    max_retries: int = 2
    json_repair_retries: int = 1
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Load LLMConfig from environment variables with backward-compatible aliases."""
        raw_provider = os.getenv("LLM_PROVIDER", "mock").lower()
        try:
            provider = LLMProvider(raw_provider)
        except ValueError:
            raise LLMConfigurationError(f"Unknown LLM_PROVIDER '{raw_provider}'. Supported: {[p.value for p in LLMProvider]}")

        base_url = (
            os.getenv("LLM_BASE_URL", "")
            or os.getenv("LLM_API_URL", "")
            or os.getenv("LLM_API_BASE", "")
        )
        if not base_url and provider == LLMProvider.NVIDIA:
            base_url = "https://integrate.api.nvidia.com/v1"

        timeout_str = os.getenv("LLM_TIMEOUT_SECONDS") or os.getenv("LLM_TIMEOUT", "60")
        max_tokens_str = os.getenv("LLM_MAX_OUTPUT_TOKENS") or os.getenv("LLM_MAX_TOKENS", "4000")

        return cls(
            provider=provider,
            model=os.getenv("LLM_MODEL", ""),
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=base_url,
            api_url=base_url,
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
            max_tokens=int(max_tokens_str),
            timeout=float(timeout_str),
            max_retries=int(os.getenv("LLM_MAX_REQUEST_RETRIES", "2")),
            json_repair_retries=int(os.getenv("LLM_JSON_REPAIR_RETRIES", "1")),
            cache_enabled=os.getenv("LLM_CACHE_ENABLED", "true").lower() in ("1", "true", "yes"),
            cache_ttl_seconds=int(os.getenv("LLM_CACHE_TTL_SECONDS", "300")),
        )

    def validate(self) -> None:
        """Validate that all required configuration settings exist for the selected provider."""
        if self.provider == LLMProvider.NEMOTRON:
            if not self.base_url:
                raise LLMConfigurationError("LLM_BASE_URL is required when LLM_PROVIDER=nemotron")
            if not self.api_key:
                raise LLMConfigurationError("LLM_API_KEY is required when LLM_PROVIDER=nemotron")
            if not self.model:
                raise LLMConfigurationError("LLM_MODEL is required when LLM_PROVIDER=nemotron")

        elif self.provider == LLMProvider.OPENAI:
            if not self.api_key:
                raise LLMConfigurationError("LLM_API_KEY is required when LLM_PROVIDER=openai")

        elif self.provider == LLMProvider.ANTHROPIC:
            if not self.api_key:
                raise LLMConfigurationError("LLM_API_KEY is required when LLM_PROVIDER=anthropic")

        elif self.provider == LLMProvider.MOCK:
            # Mock provider is explicitly permitted for local development and testing
            pass


@dataclass
class LLMMessage:
    role: str  # system, user, assistant
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    usage: Dict[str, int] = field(default_factory=dict)
    request_id: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    finish_reason: Optional[str] = "stop"
    error_state: Optional[str] = None
    cached: bool = False
    parsed: Optional[Any] = None


# --- URL Helper ---

def _resolve_chat_endpoint(base_url: str) -> str:
    """Format canonical chat completions endpoint from base URL."""
    if not base_url:
        return "https://api.openai.com/v1/chat/completions"
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


# --- In-Memory Response Cache ---

_llm_cache: Dict[str, Tuple[LLMResponse, float]] = {}
_MAX_CACHE_SIZE = 1000


def _build_cache_key(provider: str, model: str, messages: List[LLMMessage], schema_name: str = "") -> str:
    """Generate SHA-256 hash key for caching."""
    raw = f"{provider}:{model}:{schema_name}:" + "|".join(f"{m.role}:{m.content}" for m in messages)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_cached_response(key: str, ttl_seconds: int) -> Optional[LLMResponse]:
    """Retrieve response from cache if not expired."""
    entry = _llm_cache.get(key)
    if not entry:
        return None
    resp, timestamp = entry
    if (time.time() - timestamp) > ttl_seconds:
        _llm_cache.pop(key, None)
        return None
    # Return a copy marked as cached
    return LLMResponse(
        content=resp.content,
        model=resp.model,
        provider=resp.provider,
        usage=dict(resp.usage),
        request_id=resp.request_id,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        latency_ms=0.0,
        finish_reason=resp.finish_reason,
        cached=True,
        parsed=resp.parsed,
    )


def _store_cached_response(key: str, resp: LLMResponse) -> None:
    """Store successful response in cache with LRU eviction."""
    global _llm_cache
    if len(_llm_cache) >= _MAX_CACHE_SIZE:
        # Evict oldest 20%
        sorted_keys = sorted(_llm_cache.keys(), key=lambda k: _llm_cache[k][1])
        for k in sorted_keys[: _MAX_CACHE_SIZE // 5]:
            _llm_cache.pop(k, None)
    _llm_cache[key] = (resp, time.time())


def clear_llm_cache() -> None:
    """Clear all entries in the LLM response cache."""
    global _llm_cache
    _llm_cache.clear()


# --- Provider Implementations ---

async def _call_openai_compatible(
    config: LLMConfig,
    messages: List[LLMMessage],
    http_client: Optional[httpx.AsyncClient] = None,
) -> LLMResponse:
    """Call an OpenAI-compatible API (Nemotron, OpenAI, Kimi, etc.) with retries."""
    url = _resolve_chat_endpoint(config.base_url or config.api_url)
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    payload = {
        "model": config.model or "default",
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }

    start_time = time.perf_counter()
    last_exception = None

    for attempt in range(config.max_retries + 1):
        try:
            if http_client is not None:
                resp = await http_client.post(url, json=payload, headers=headers, timeout=config.timeout)
            else:
                async with httpx.AsyncClient(timeout=config.timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)

            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # Classify HTTP Status Codes
            if resp.status_code in (401, 403):
                raise LLMAuthenticationError(
                    f"Authentication failed for {config.provider} (status {resp.status_code})",
                    status_code=resp.status_code,
                    retryable=False,
                )
            if resp.status_code == 400:
                raise LLMProviderError(
                    f"Invalid request to {config.provider}: {resp.text[:200]}",
                    status_code=400,
                    retryable=False,
                )
            if resp.status_code == 429:
                if attempt < config.max_retries:
                    await asyncio.sleep(min(2 ** attempt, 8))
                    continue
                raise LLMRateLimitError(
                    f"Rate limit exceeded for {config.provider}",
                    status_code=429,
                    retryable=True,
                )
            if resp.status_code >= 500:
                if attempt < config.max_retries:
                    await asyncio.sleep(min(2 ** attempt, 8))
                    continue
                raise LLMProviderError(
                    f"Provider {config.provider} server error ({resp.status_code})",
                    status_code=resp.status_code,
                    retryable=True,
                )

            resp.raise_for_status()
            data = resp.json()

            choice = data["choices"][0]
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens")
            output_tokens = usage.get("completion_tokens")

            return LLMResponse(
                content=choice["message"]["content"],
                model=data.get("model", config.model),
                provider=config.provider.value,
                usage=usage,
                request_id=data.get("id"),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                finish_reason=choice.get("finish_reason", "stop"),
            )

        except httpx.TimeoutException as exc:
            last_exception = LLMTimeoutError(
                f"Timeout calling {config.provider} after {config.timeout}s",
                retryable=True,
            )
            if attempt < config.max_retries:
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            raise last_exception
        except (LLMAuthenticationError, LLMProviderError):
            raise
        except Exception as exc:
            last_exception = LLMProviderError(f"Error calling {config.provider}: {str(exc)[:200]}")
            if attempt < config.max_retries:
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            raise last_exception

    if last_exception:
        raise last_exception
    raise LLMProviderError(f"Failed calling {config.provider} after {config.max_retries} retries")


async def _call_anthropic(
    config: LLMConfig,
    messages: List[LLMMessage],
    http_client: Optional[httpx.AsyncClient] = None,
) -> LLMResponse:
    """Call Anthropic API."""
    url = config.base_url or "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    system_msg = ""
    user_messages = []
    for m in messages:
        if m.role == "system":
            system_msg = m.content
        else:
            user_messages.append({"role": m.role, "content": m.content})

    payload = {
        "model": config.model or "claude-3-5-sonnet-20241022",
        "messages": user_messages,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
    }
    if system_msg:
        payload["system"] = system_msg

    start_time = time.perf_counter()
    if http_client is not None:
        resp = await http_client.post(url, json=payload, headers=headers, timeout=config.timeout)
    else:
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)

    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
    resp.raise_for_status()
    data = resp.json()

    usage = data.get("usage", {})
    return LLMResponse(
        content=data["content"][0]["text"],
        model=data.get("model", config.model),
        provider="anthropic",
        usage=usage,
        request_id=data.get("id"),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        latency_ms=latency_ms,
    )


async def _call_mock(
    config: LLMConfig,
    messages: List[LLMMessage],
    http_client: Optional[httpx.AsyncClient] = None,
) -> LLMResponse:
    """Mock LLM for explicit development and unit testing."""
    last_msg = messages[-1].content if messages else ""

    if "hypothesis" in last_msg.lower():
        content = json.dumps({
            "hypotheses": [
                {
                    "label": "Null pointer in request handler",
                    "description": "A recent code change introduced a null pointer dereference in the main request handler.",
                    "confidence": "medium",
                    "category": "code_change",
                    "severity": "high",
                    "evidence_needed": ["Check recent commits touching request handlers"],
                },
                {
                    "label": "Database connection pool exhaustion",
                    "description": "The database connection pool may be exhausted due to long-running queries.",
                    "confidence": "medium",
                    "category": "infrastructure",
                    "severity": "critical",
                    "evidence_needed": ["Check database connection metrics"],
                },
            ]
        }, indent=2)
    elif "root cause" in last_msg.lower():
        content = json.dumps({
            "root_cause": {
                "label": "Null pointer in request handler",
                "description": "A recent commit removed a null check from the validation layer.",
                "confidence": "medium",
                "category": "code_change",
                "affected_files": ["backend/app/routes/repositories.py"],
            }
        }, indent=2)
    elif "investigation" in last_msg.lower() or "plan" in last_msg.lower():
        content = json.dumps({
            "tasks": [
                {"tool": "search_code", "description": "Search for error patterns in the codebase", "priority": 1},
                {"tool": "read_file", "description": "Read the request handler files", "priority": 2},
            ]
        }, indent=2)
    elif any(k in last_msg.lower() for k in ("patch", "fix", "old_code", "changes", "minimal fix")):
        content = json.dumps({
            "summary": "Standardize Sentinel logo component across application views",
            "commit_message": "fix: standardize Sentinel logo component across pages",
            "risk": "low",
            "risk_explanation": "Replaces inconsistent logo elements",
            "changes": [
                {
                    "file": "sentinel-ui/src/components/Sidebar.tsx",
                    "action": "modify",
                    "description": "Use canonical Logo component in Sidebar",
                    "old_code": '<img src="/sentinel_logo.png" />',
                    "new_code": '<Logo size="md" href="/" />',
                }
            ]
        }, indent=2)
    else:
        content = "Mock response: Operation completed successfully."

    return LLMResponse(
        content=content,
        model="mock",
        provider="mock",
        usage={"prompt_tokens": len(last_msg), "completion_tokens": len(content)},
        input_tokens=len(last_msg),
        output_tokens=len(content),
        latency_ms=1.0,
        finish_reason="stop",
    )


PROVIDERS = {
    LLMProvider.NEMOTRON: _call_openai_compatible,
    LLMProvider.OPENAI: _call_openai_compatible,
    LLMProvider.NVIDIA: _call_openai_compatible,
    LLMProvider.KIMI: _call_openai_compatible,
    LLMProvider.VICTOE: _call_openai_compatible,
    LLMProvider.ANTHROPIC: _call_anthropic,
    LLMProvider.MOCK: _call_mock,
}


# --- Public API ---

_config: Optional[LLMConfig] = None


def get_config() -> LLMConfig:
    """Retrieve and validate the singleton LLMConfig."""
    global _config
    if _config is None:
        _config = LLMConfig.from_env()
        _config.validate()
    return _config


def reset_config() -> None:
    """Reset configuration singleton and cache (primarily for unit tests)."""
    global _config
    _config = None
    clear_llm_cache()


async def chat_completion(
    messages: List[LLMMessage],
    config: Optional[LLMConfig] = None,
    http_client: Optional[httpx.AsyncClient] = None,
    use_cache: bool = True,
    schema_name: str = "",
) -> LLMResponse:
    """Send a chat completion request with caching and strict provider routing."""
    cfg = config or get_config()
    cfg.validate()

    provider_fn = PROVIDERS.get(cfg.provider)
    if not provider_fn:
        raise LLMConfigurationError(f"No execution handler registered for provider '{cfg.provider}'")

    cache_key = None
    if cfg.cache_enabled and use_cache and cfg.provider != LLMProvider.MOCK:
        cache_key = _build_cache_key(cfg.provider.value, cfg.model, messages, schema_name=schema_name)
        cached_resp = _get_cached_response(cache_key, cfg.cache_ttl_seconds)
        if cached_resp:
            return cached_resp

    response = await provider_fn(cfg, messages, http_client=http_client)

    if cache_key and response and not response.error_state:
        _store_cached_response(cache_key, response)

    return response


async def generate_text(
    system_prompt: str,
    user_prompt: str,
    config: Optional[LLMConfig] = None,
    http_client: Optional[httpx.AsyncClient] = None,
    use_cache: bool = True,
) -> str:
    """Simple text generation returning raw string content."""
    messages = [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt),
    ]
    response = await chat_completion(messages, config=config, http_client=http_client, use_cache=use_cache)
    return response.content


def _extract_json_payload(text: str) -> Any:
    """Defensively extract and parse JSON payload from response text."""
    import re
    # 1. Direct JSON parse
    try:
        return json.loads(text.strip())
    except Exception:
        pass

    # 2. Markdown code block
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except Exception:
            pass

    # 3. First JSON object or array in text
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except Exception:
            pass

    raise ValueError(f"No valid JSON found in response: {text[:200]}")


def _validate_schema(data: Any, schema: Optional[Any]) -> Any:
    """Validate parsed JSON against a Pydantic model or schema definition."""
    if schema is None:
        return data

    # 1. Pydantic Model Class
    if isinstance(schema, type):
        try:
            # Pydantic v2
            if hasattr(schema, "model_validate"):
                return schema.model_validate(data)
            # Pydantic v1
            if hasattr(schema, "parse_obj"):
                return schema.parse_obj(data)
        except Exception as exc:
            raise ValueError(f"Schema validation failed against {schema.__name__}: {exc}")

    # 2. JSON Schema Dict
    if isinstance(schema, dict):
        try:
            import jsonschema
            jsonschema.validate(instance=data, schema=schema)
            return data
        except ImportError:
            # Explicit structural validation when jsonschema library is unavailable
            expected_type = schema.get("type")
            if expected_type == "object" and not isinstance(data, dict):
                raise ValueError(f"Expected JSON object (dict), got {type(data).__name__}")
            if expected_type == "array" and not isinstance(data, list):
                raise ValueError(f"Expected JSON array (list), got {type(data).__name__}")
            
            # Check required properties
            if isinstance(data, dict):
                required = schema.get("required", [])
                missing = [req for req in required if req not in data]
                if missing:
                    raise ValueError(f"Missing required JSON schema fields: {missing}")
                
                # Check property types
                properties = schema.get("properties", {})
                for prop_name, prop_spec in properties.items():
                    if prop_name in data and isinstance(prop_spec, dict) and "type" in prop_spec:
                        ptype = prop_spec["type"]
                        val = data[prop_name]
                        if ptype == "string" and not isinstance(val, str):
                            raise ValueError(f"Field '{prop_name}' expected string, got {type(val).__name__}")
                        elif ptype == "integer" and not isinstance(val, int):
                            raise ValueError(f"Field '{prop_name}' expected integer, got {type(val).__name__}")
                        elif ptype == "array" and not isinstance(val, list):
                            raise ValueError(f"Field '{prop_name}' expected array, got {type(val).__name__}")
                        elif ptype == "object" and not isinstance(val, dict):
                            raise ValueError(f"Field '{prop_name}' expected object, got {type(val).__name__}")
            return data
        except Exception as exc:
            raise ValueError(f"JSON Schema validation error: {exc}")

    return data


async def generate_json_response(
    system_prompt: str,
    user_prompt: str,
    config: Optional[LLMConfig] = None,
    schema: Optional[Any] = None,
    http_client: Optional[httpx.AsyncClient] = None,
    use_cache: bool = True,
) -> LLMResponse:
    """Generate structured JSON response returning full LLMResponse with .parsed."""
    system_instruction = system_prompt + "\n\nRespond ONLY with valid JSON. No conversational text, no markdown preamble."

    messages = [
        LLMMessage(role="system", content=system_instruction),
        LLMMessage(role="user", content=user_prompt),
    ]

    schema_name = (
        schema.__name__
        if hasattr(schema, "__name__")
        else (json.dumps(schema, sort_keys=True) if isinstance(schema, dict) else "")
    )

    response = await chat_completion(
        messages,
        config=config,
        http_client=http_client,
        use_cache=use_cache,
        schema_name=schema_name,
    )

    try:
        raw_parsed = _extract_json_payload(response.content)
        validated = _validate_schema(raw_parsed, schema)
        response.parsed = validated
        return response
    except Exception as parse_err:
        # JSON Repair Attempt (exactly 1 retry)
        repair_messages = [
            LLMMessage(role="system", content="You are a JSON repair tool. Output ONLY valid, parsable JSON matching the requested schema. No explanation."),
            LLMMessage(role="user", content=f"Fix this invalid JSON output:\n\n{response.content}\n\nError encountered:\n{parse_err}"),
        ]
        try:
            repair_resp = await chat_completion(
                repair_messages,
                config=config,
                http_client=http_client,
                use_cache=False,
                schema_name=schema_name,
            )
            raw_parsed = _extract_json_payload(repair_resp.content)
            validated = _validate_schema(raw_parsed, schema)
            repair_resp.parsed = validated
            return repair_resp
        except Exception as final_err:
            raise LLMStructuredOutputError(f"Failed to generate valid structured JSON after repair retry: {final_err}")


async def generate_json(
    system_prompt: str,
    user_prompt: str,
    config: Optional[LLMConfig] = None,
    schema: Optional[Any] = None,
    http_client: Optional[httpx.AsyncClient] = None,
    use_cache: bool = True,
) -> Dict:
    """Generate structured JSON response, returning Dict for backward compatibility."""
    response = await generate_json_response(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        config=config,
        schema=schema,
        http_client=http_client,
        use_cache=use_cache,
    )
    if isinstance(response.parsed, dict):
        return response.parsed
    if hasattr(response.parsed, "model_dump"):
        return response.parsed.model_dump()
    if hasattr(response.parsed, "dict"):
        return response.parsed.dict()
    if isinstance(response.parsed, list):
        return {"items": response.parsed}
    return {"result": response.parsed}
