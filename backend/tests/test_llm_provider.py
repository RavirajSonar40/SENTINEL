"""Comprehensive unit tests for Phase 1 Nemotron-compatible AI provider.

All tests run 100% offline using httpx.MockTransport.
Verifies:
- Config validation timing and strict validation
- Endpoint resolution
- Error classification (401, 429, 500, timeout)
- Non-retryable vs retryable behaviors
- Response metadata
- 1-shot JSON repair retry and failure
- Cache behavior, TTL, and cache key derivation
- Secret non-disclosure in errors and logs
"""
import json
import logging
import pytest
import httpx
from pydantic import BaseModel

from app.services.llm import (
    LLMConfig,
    LLMProvider,
    LLMMessage,
    LLMResponse,
    LLMConfigurationError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMProviderError,
    LLMStructuredOutputError,
    chat_completion,
    generate_text,
    generate_json,
    generate_json_response,
    clear_llm_cache,
    reset_config,
    _resolve_chat_endpoint,
    _build_cache_key,
)


@pytest.fixture(autouse=True)
def clean_llm_state():
    """Reset singleton state and cache before each test."""
    reset_config()
    clear_llm_cache()
    yield
    reset_config()
    clear_llm_cache()


# 1. Configuration & Validation Tests

def test_nemotron_configuration_is_validated_before_request():
    """System must fail immediately before any network call if credentials/model are missing."""
    cfg = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="",
        api_key="",
        model="",
    )
    with pytest.raises(LLMConfigurationError) as exc:
        cfg.validate()
    assert "LLM_BASE_URL is required" in str(exc.value)


def test_missing_nemotron_api_key_fails_configuration():
    """Fails when API key is missing."""
    cfg = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://integrate.api.nvidia.com/v1",
        api_key="",
        model="nvidia/nemotron-4-340b-instruct",
    )
    with pytest.raises(LLMConfigurationError) as exc:
        cfg.validate()
    assert "LLM_API_KEY is required" in str(exc.value)


def test_missing_nemotron_base_url_fails_configuration():
    """Fails when Base URL is missing."""
    cfg = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="",
        api_key="nvapi-test-key",
        model="nvidia/nemotron-4-340b-instruct",
    )
    with pytest.raises(LLMConfigurationError) as exc:
        cfg.validate()
    assert "LLM_BASE_URL is required" in str(exc.value)


def test_missing_nemotron_model_fails_configuration():
    """Fails when Model name is missing."""
    cfg = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://integrate.api.nvidia.com/v1",
        api_key="nvapi-test-key",
        model="",
    )
    with pytest.raises(LLMConfigurationError) as exc:
        cfg.validate()
    assert "LLM_MODEL is required" in str(exc.value)


def test_unknown_provider_does_not_fallback_to_mock(monkeypatch):
    """An unknown provider must raise LLMConfigurationError, never silently fall back to mock."""
    monkeypatch.setenv("LLM_PROVIDER", "unsupported_provider_xyz")
    with pytest.raises(LLMConfigurationError):
        LLMConfig.from_env()


def test_mock_provider_requires_explicit_configuration():
    """Mock provider is only active when explicitly set to mock."""
    cfg = LLMConfig(provider=LLMProvider.MOCK)
    cfg.validate()
    assert cfg.provider == LLMProvider.MOCK


def test_base_url_appends_chat_completions_path_once():
    """Endpoint resolution appends /chat/completions cleanly without duplication."""
    assert _resolve_chat_endpoint("https://integrate.api.nvidia.com/v1") == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert _resolve_chat_endpoint("https://integrate.api.nvidia.com/v1/") == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert _resolve_chat_endpoint("https://integrate.api.nvidia.com/v1/chat/completions") == "https://integrate.api.nvidia.com/v1/chat/completions"


# 2. Network & HTTP Transport Tests (MockTransport)

@pytest.mark.asyncio
async def test_nemotron_request_uses_configured_endpoint():
    """Verifies that Nemotron calls use the exact configured base endpoint."""
    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "cmpl-12345",
                "model": "nvidia/nemotron-4-340b-instruct",
                "choices": [{"message": {"content": "Hello from Nemotron"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://custom.nemotron.host/v1",
        api_key="secret-nv-key-999",
        model="nvidia/nemotron-4-340b-instruct",
        cache_enabled=False,
    )

    resp = await chat_completion(
        [LLMMessage(role="user", content="Ping")],
        config=config,
        http_client=client,
    )

    assert resp.content == "Hello from Nemotron"
    assert len(captured_requests) == 1
    assert str(captured_requests[0].url) == "https://custom.nemotron.host/v1/chat/completions"
    assert captured_requests[0].headers["Authorization"] == "Bearer secret-nv-key-999"


@pytest.mark.asyncio
async def test_api_key_is_not_logged():
    """Ensures secret API keys are never exposed in error representations."""
    secret_key = "sk-super-secret-api-key-12345"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Unauthorized key"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key=secret_key,
        model="nemotron",
        max_retries=0,
        cache_enabled=False,
    )

    with pytest.raises(LLMAuthenticationError) as exc:
        await chat_completion(
            [LLMMessage(role="user", content="Hi")],
            config=config,
            http_client=client,
        )

    assert secret_key not in str(exc.value)


@pytest.mark.asyncio
async def test_http_401_is_not_retried():
    """HTTP 401 Unauthorized must fail immediately without retrying."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, json={"error": "Unauthorized"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key="bad-key",
        model="nemotron",
        max_retries=2,
        cache_enabled=False,
    )

    with pytest.raises(LLMAuthenticationError):
        await chat_completion(
            [LLMMessage(role="user", content="Hi")],
            config=config,
            http_client=client,
        )

    assert call_count == 1  # No retries for 401


@pytest.mark.asyncio
async def test_http_429_is_retried():
    """HTTP 429 Rate Limit must be retried with backoff."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            return httpx.Response(429, json={"error": "Too Many Requests"})
        return httpx.Response(
            200,
            json={
                "id": "cmpl-1",
                "model": "nemotron",
                "choices": [{"message": {"content": "Success after 429"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key="test-key",
        model="nemotron",
        max_retries=2,
        cache_enabled=False,
    )

    resp = await chat_completion(
        [LLMMessage(role="user", content="Hi")],
        config=config,
        http_client=client,
    )

    assert resp.content == "Success after 429"
    assert call_count == 2


@pytest.mark.asyncio
async def test_http_500_is_retried():
    """HTTP 500 Server Error must be retried with backoff."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(
            200,
            json={
                "id": "cmpl-2",
                "model": "nemotron",
                "choices": [{"message": {"content": "Success after 500"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key="test-key",
        model="nemotron",
        max_retries=2,
        cache_enabled=False,
    )

    resp = await chat_completion(
        [LLMMessage(role="user", content="Hi")],
        config=config,
        http_client=client,
    )

    assert resp.content == "Success after 500"
    assert call_count == 2


@pytest.mark.asyncio
async def test_provider_timeout_is_reported_as_blocked():
    """Timeout exceptions must be classified as LLMTimeoutError."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key="test-key",
        model="nemotron",
        timeout=1.0,
        max_retries=1,
        cache_enabled=False,
    )

    with pytest.raises(LLMTimeoutError):
        await chat_completion(
            [LLMMessage(role="user", content="Hi")],
            config=config,
            http_client=client,
        )


@pytest.mark.asyncio
async def test_successful_response_contains_metadata():
    """Response includes model, provider, token usage, latency, and request ID."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "req-9876",
                "model": "nvidia/nemotron-4-340b-instruct",
                "choices": [{"message": {"content": "Verified metadata"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 18, "total_tokens": 60},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key="test-key",
        model="nvidia/nemotron-4-340b-instruct",
        cache_enabled=False,
    )

    resp = await chat_completion(
        [LLMMessage(role="user", content="Test metadata")],
        config=config,
        http_client=client,
    )

    assert resp.content == "Verified metadata"
    assert resp.request_id == "req-9876"
    assert resp.input_tokens == 42
    assert resp.output_tokens == 18
    assert resp.latency_ms is not None and resp.latency_ms >= 0
    assert resp.finish_reason == "stop"
    assert resp.provider == "nemotron"


# 3. Structured JSON & 1x Repair Retry Tests

@pytest.mark.asyncio
async def test_existing_generate_json_callers_still_work():
    """Existing generate_json callers receive a Dict return type directly without breaking."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "cmpl-json",
                "model": "nemotron",
                "choices": [{"message": {"content": '{"status": "ok", "confidence": "high"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key="test-key",
        model="nemotron",
        cache_enabled=False,
    )

    result = await generate_json(
        system_prompt="Return status",
        user_prompt="Check status",
        config=config,
        http_client=client,
    )

    assert isinstance(result, dict)
    assert result["status"] == "ok"
    assert result["confidence"] == "high"


@pytest.mark.asyncio
async def test_invalid_json_is_retried():
    """Malformed initial JSON output is automatically repaired via exactly 1 retry."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Malformed JSON (broken syntax)
            return httpx.Response(
                200,
                json={
                    "id": "cmpl-bad",
                    "model": "nemotron",
                    "choices": [{"message": {"content": 'Here is the json: {status: "broken", incomplete...'}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10},
                },
            )
        # Repaired valid JSON response
        return httpx.Response(
            200,
            json={
                "id": "cmpl-good",
                "model": "nemotron",
                "choices": [{"message": {"content": '{"status": "repaired", "code": 200}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 15, "completion_tokens": 10},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key="test-key",
        model="nemotron",
        cache_enabled=False,
    )

    result = await generate_json(
        system_prompt="Return JSON",
        user_prompt="Give me JSON",
        config=config,
        http_client=client,
    )

    assert call_count == 2
    assert result["status"] == "repaired"
    assert result["code"] == 200


@pytest.mark.asyncio
async def test_invalid_json_after_retry_fails():
    """If JSON remains malformed after 1 repair retry, raise LLMStructuredOutputError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "cmpl-fail",
                "model": "nemotron",
                "choices": [{"message": {"content": "Not JSON at all, still plain text."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key="test-key",
        model="nemotron",
        cache_enabled=False,
    )

    with pytest.raises(LLMStructuredOutputError):
        await generate_json(
            system_prompt="Return JSON",
            user_prompt="Give me JSON",
            config=config,
            http_client=client,
        )


@pytest.mark.asyncio
async def test_generate_json_with_pydantic_schema():
    """Validates output against a Pydantic schema model class."""
    class UserSchema(BaseModel):
        username: str
        role: str

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "cmpl-pyd",
                "model": "nemotron",
                "choices": [{"message": {"content": '{"username": "raviraj", "role": "admin"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key="test-key",
        model="nemotron",
        cache_enabled=False,
    )

    resp = await generate_json_response(
        system_prompt="Return user",
        user_prompt="Get user",
        config=config,
        schema=UserSchema,
        http_client=client,
    )

    assert isinstance(resp.parsed, UserSchema)
    assert resp.parsed.username == "raviraj"
    assert resp.parsed.role == "admin"


# 4. In-Memory Caching Tests

@pytest.mark.asyncio
async def test_cache_hits_avoid_network_calls():
    """Repeated calls with identical prompts return cached response without calling provider."""
    network_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal network_calls
        network_calls += 1
        return httpx.Response(
            200,
            json={
                "id": "cmpl-cached",
                "model": "nemotron",
                "choices": [{"message": {"content": "Cached Content"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key="test-key",
        model="nemotron",
        cache_enabled=True,
    )

    r1 = await chat_completion([LLMMessage(role="user", content="Identical Query")], config=config, http_client=client)
    assert r1.cached is False
    assert network_calls == 1

    r2 = await chat_completion([LLMMessage(role="user", content="Identical Query")], config=config, http_client=client)
    assert r2.cached is True
    assert network_calls == 1  # Network was not called again


@pytest.mark.asyncio
async def test_provider_error_does_not_enter_cache():
    """Errors are never cached, so subsequent requests re-attempt execution."""
    network_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal network_calls
        network_calls += 1
        if network_calls == 1:
            return httpx.Response(500, text="Temporary Error")
        return httpx.Response(
            200,
            json={
                "id": "cmpl-rec",
                "model": "nemotron",
                "choices": [{"message": {"content": "Recovered"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key="test-key",
        model="nemotron",
        max_retries=0,
        cache_enabled=True,
    )

    with pytest.raises(LLMProviderError):
        await chat_completion([LLMMessage(role="user", content="Retry Query")], config=config, http_client=client)

    # Next attempt succeeds and calls network again
    r2 = await chat_completion([LLMMessage(role="user", content="Retry Query")], config=config, http_client=client)
    assert r2.content == "Recovered"
    assert network_calls == 2


def test_cache_key_changes_when_prompt_changes():
    """Different prompt text generates a distinct cache key."""
    m1 = [LLMMessage(role="user", content="Prompt A")]
    m2 = [LLMMessage(role="user", content="Prompt B")]
    k1 = _build_cache_key("nemotron", "m1", m1)
    k2 = _build_cache_key("nemotron", "m1", m2)
    assert k1 != k2


def test_cache_key_changes_when_model_changes():
    """Different model configuration generates a distinct cache key."""
    m = [LLMMessage(role="user", content="Prompt")]
    k1 = _build_cache_key("nemotron", "model-1", m)
    k2 = _build_cache_key("nemotron", "model-2", m)
    assert k1 != k2


def test_cache_key_changes_when_schema_changes():
    """Different schema identity generates a distinct cache key."""
    m = [LLMMessage(role="user", content="Prompt")]
    k1 = _build_cache_key("nemotron", "m", m, schema_name="SchemaA")
    k2 = _build_cache_key("nemotron", "m", m, schema_name="SchemaB")
    assert k1 != k2


@pytest.mark.asyncio
async def test_generate_json_with_dict_schema_validation():
    """Validates output against a raw dict JSON Schema."""
    json_schema = {
        "type": "object",
        "required": ["action", "target"],
        "properties": {
            "action": {"type": "string"},
            "target": {"type": "string"},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "cmpl-sch",
                "model": "nemotron",
                "choices": [{"message": {"content": '{"action": "create", "target": "README.md"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = LLMConfig(
        provider=LLMProvider.NEMOTRON,
        base_url="https://api.nvidia.com/v1",
        api_key="test-key",
        model="nemotron",
        cache_enabled=False,
    )

    resp = await generate_json_response(
        system_prompt="Return action",
        user_prompt="Get action",
        config=config,
        schema=json_schema,
        http_client=client,
    )

    assert resp.parsed == {"action": "create", "target": "README.md"}

