"""
Unit Tests for Two-Tier Intent Router.

Verifies:
- Direct task classification for files (README.md, CONTRIBUTING.md, docker-compose.yml)
- False positive guards (e.g. "Add support for README parsing" is FEATURE)
- Bug classification with conditional runtime evidence (prod vs non-prod)
- Feature classification
- Production incident detection from alerts and telemetry
- Security incident classification
- Direct task hypothesis skipping
- Tier 2 LLM structured classification & ambiguity guards (< 0.70 -> NEEDS_CLARIFICATION)
"""

import pytest
import httpx
from app.models.work_item import WorkType
from app.schemas.work_item import WorkTypeEnvelope
from app.services.intent_router import classify_intent
from app.services.llm import LLMConfig, LLMProvider, clear_llm_cache


@pytest.fixture(autouse=True)
def clean_cache():
    clear_llm_cache()


@pytest.mark.asyncio
async def test_readme_is_direct_task():
    """'Add README.md' is classified as DIRECT_TASK targeting README.md."""
    envelope = await classify_intent(title="Add README.md")
    assert envelope.work_type == WorkType.DIRECT_TASK
    assert "README.md" in envelope.target_files
    assert envelope.workflow == "repository_task"
    assert envelope.requires_runtime_evidence is False
    assert envelope.confidence >= 0.85


@pytest.mark.asyncio
async def test_create_contributing_is_direct_task():
    """'Create CONTRIBUTING.md' is classified as DIRECT_TASK targeting CONTRIBUTING.md."""
    envelope = await classify_intent(title="Create CONTRIBUTING.md")
    assert envelope.work_type == WorkType.DIRECT_TASK
    assert "CONTRIBUTING.md" in envelope.target_files
    assert envelope.workflow == "repository_task"
    assert envelope.requires_runtime_evidence is False


@pytest.mark.asyncio
async def test_update_docker_compose_is_direct_task():
    """'Update docker-compose.yml' is classified as DIRECT_TASK targeting docker-compose.yml."""
    envelope = await classify_intent(title="Update docker-compose.yml")
    assert envelope.work_type == WorkType.DIRECT_TASK
    assert "docker-compose.yml" in envelope.target_files
    assert envelope.workflow == "repository_task"


@pytest.mark.asyncio
async def test_add_support_for_readme_is_not_direct_task():
    """'Add support for README parsing' contains feature phrase -> FEATURE, not DIRECT_TASK."""
    envelope = await classify_intent(title="Add support for README parsing")
    assert envelope.work_type == WorkType.FEATURE
    assert envelope.workflow == "feature"
    assert envelope.requires_runtime_evidence is False


@pytest.mark.asyncio
async def test_login_error_without_prod_context_is_bug():
    """Code-level bug without production context does not require runtime evidence."""
    envelope = await classify_intent(title="Fix login returns 500 when password is empty")
    assert envelope.work_type == WorkType.BUG
    assert envelope.workflow == "bug"
    assert envelope.requires_runtime_evidence is False
    assert "sufficient" in (envelope.runtime_evidence_reason or "").lower()


@pytest.mark.asyncio
async def test_login_error_with_prod_context_requires_runtime_evidence():
    """Bug with production context requires runtime telemetry evidence."""
    envelope = await classify_intent(
        title="Fix login returns 500 in production during checkout traffic"
    )
    assert envelope.work_type == WorkType.BUG
    assert envelope.workflow == "bug"
    assert envelope.requires_runtime_evidence is True
    assert "production" in (envelope.runtime_evidence_reason or "").lower()


@pytest.mark.asyncio
async def test_dark_mode_is_feature():
    """'Add dark mode toggle to settings' is classified as FEATURE."""
    envelope = await classify_intent(title="Add dark mode toggle to settings")
    assert envelope.work_type == WorkType.FEATURE
    assert envelope.workflow == "feature"
    assert envelope.requires_runtime_evidence is False


@pytest.mark.asyncio
async def test_cpu_alert_is_production_incident():
    """'CPU is high in production' is classified as PRODUCTION_INCIDENT."""
    envelope = await classify_intent(title="CPU is high in production")
    assert envelope.work_type == WorkType.PRODUCTION_INCIDENT
    assert envelope.workflow == "production_incident"
    assert envelope.requires_runtime_evidence is True


@pytest.mark.asyncio
async def test_production_checkout_down_is_production_incident():
    """'Production checkout is down' is classified as PRODUCTION_INCIDENT."""
    envelope = await classify_intent(title="Production checkout is down")
    assert envelope.work_type == WorkType.PRODUCTION_INCIDENT
    assert envelope.workflow == "production_incident"
    assert envelope.requires_runtime_evidence is True


@pytest.mark.asyncio
async def test_security_signal_uses_security_workflow():
    """'Suspicious login activity detected' is classified as SECURITY_INCIDENT."""
    envelope = await classify_intent(title="Suspicious login activity detected")
    assert envelope.work_type == WorkType.SECURITY_INCIDENT
    assert envelope.workflow == "security_incident"
    assert envelope.requires_runtime_evidence is True
    assert envelope.requires_code_change is False


@pytest.mark.asyncio
async def test_direct_task_skips_incident_hypotheses():
    """Verifies direct tasks have requires_runtime_evidence=False and workflow='repository_task'."""
    envelope = await classify_intent(title="Write requirements.txt")
    assert envelope.work_type == WorkType.DIRECT_TASK
    assert envelope.requires_runtime_evidence is False
    assert envelope.workflow == "repository_task"


@pytest.mark.asyncio
async def test_low_confidence_ambiguity_returns_clarification():
    """Ambiguous requests returning confidence < 0.70 halt into NEEDS_CLARIFICATION."""
    # Mock LLM to return low-confidence envelope
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "cmpl-ambig",
                "model": "nemotron",
                "choices": [{
                    "message": {
                        "content": '{"work_type": "NEEDS_CLARIFICATION", "confidence": 0.45, "workflow": "clarification", "target_files": [], "requires_runtime_evidence": false, "requires_code_change": false, "questions": ["Which repo?", "Is this an outage?"], "rationale": "Ambiguous input"}'
                    },
                    "finish_reason": "stop",
                }],
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

    # Use title that bypasses Tier 1 regex patterns
    envelope = await classify_intent(
        title="Check system overview performance and stuff",
        config=config,
    )

    assert envelope.work_type == WorkType.NEEDS_CLARIFICATION
    assert envelope.confidence < 0.70
    assert len(envelope.questions) > 0
