"""Pytest configuration — fixtures for testing."""
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["ENVIRONMENT"] = "testing"

from app.core.config import settings
settings.ENVIRONMENT = "testing"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear slowapi rate limit state between every test."""
    from app.core.rate_limit import limiter
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.count.return_value = 0
    return db


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    user = MagicMock()
    user.id = "test-user-id"
    user.username = "testuser"
    user.email = "test@example.com"
    user.role = "admin"
    return user


@pytest.fixture
def sample_incident():
    """Sample incident data."""
    return {
        "id": "test-incident-001",
        "number": 1,
        "title": "Test incident: payment API crash",
        "description": "Payment API returning 500 errors after deployment",
        "severity": "SEV-1",
        "status": "detected",
        "service": "payment-api",
        "error_signature": "NullPointerException at payment.py:42",
    }


@pytest.fixture
def sample_investigation():
    """Sample investigation data."""
    return {
        "id": "test-inv-001",
        "incident_id": "test-incident-001",
        "status": "completed",
        "confidence": "high",
        "llm_model": "gpt-4",
        "total_tokens": 5000,
        "total_cost_usd": 0.15,
        "tasks_completed": 5,
        "tasks_failed": 0,
        "evidence_count": 8,
        "hypotheses_count": 3,
        "root_cause_found": True,
    }


@pytest.fixture
def sample_evidence():
    """Sample evidence items."""
    return [
        {"source": "code_search", "file": "src/payment.py", "content": "def process_payment():", "line": 10},
        {"source": "git_history", "file": "commit:abc123", "content": "Updated payment config"},
        {"source": "log_search", "file": "", "content": "NullPointerException at payment.py:42"},
    ]


@pytest.fixture
def sample_root_cause():
    """Sample root cause."""
    return {
        "summary": "Database connection pool exhaustion from config change",
        "category": "deployment_regression",
        "confidence": "high",
        "severity": "SEV-1",
    }


@pytest.fixture
def sample_benchmark():
    """Sample benchmark incident."""
    return {
        "id": "bench_test_001",
        "title": "Payment API latency spike after deployment",
        "description": "p95 latency increased from 200ms to 4.2s after deployment",
        "service": "payment-api",
        "expected_root_cause": "Database connection pool exhaustion from config change",
        "expected_files": ["src/db/pool.js", "config/database.js"],
        "expected_commits": ["abc1234"],
        "severity": "SEV-1",
        "category": "deployment_regression",
        "difficulty": "medium",
        "error_signature": "ConnectionPoolTimeout",
        "expected_hypotheses": ["DB pool exhaustion", "Slow query", "Network latency"],
        "expected_tool_sequence": ["search_code", "git_history"],
    }


@pytest.fixture
def mock_llm_response():
    """Mock LLM response."""
    return MagicMock(
        content="The root cause is database connection pool exhaustion due to a configuration change in v2.8.1 that reduced max_connections from 20 to 5.",
        usage=MagicMock(prompt_tokens=500, completion_tokens=200),
    )


@pytest.fixture
def mock_search_results():
    """Mock code search results."""
    return [
        {"file": "src/db/pool.js", "content": "max_connections: 5", "line": 15, "score": 0.95},
        {"file": "config/database.js", "content": "pool: { max: 5 }", "line": 8, "score": 0.90},
        {"file": "src/handlers/payment.js", "content": "await db.query(...)", "line": 42, "score": 0.75},
    ]
