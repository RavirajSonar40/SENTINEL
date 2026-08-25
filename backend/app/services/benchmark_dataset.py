"""Expanded benchmark dataset — 12 incidents across 5 categories and 3 difficulty levels."""
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class BenchmarkIncident:
    id: str
    title: str
    description: str
    service: str
    expected_root_cause: str
    expected_files: List[str]
    expected_commits: List[str]
    severity: str
    category: str
    difficulty: str
    error_signature: str = ""
    expected_hypotheses: List[str] = field(default_factory=list)
    expected_tool_sequence: List[str] = field(default_factory=list)


BENCHMARK_DATASET: List[BenchmarkIncident] = [
    # --- Deployment Regressions ---
    BenchmarkIncident(
        id="bench_001",
        title="Payment API latency spike after deployment",
        description="p95 latency increased from 200ms to 4.2s after deployment v2.8.1. "
                    "All other services unaffected. Deploy went out at 14:32 UTC, "
                    "latency started climbing at 14:35 UTC.",
        service="payment-api",
        expected_root_cause="Database connection pool exhaustion from config change in v2.8.1",
        expected_files=["src/db/pool.js", "config/database.js"],
        expected_commits=["abc1234"],
        severity="SEV-1",
        category="deployment_regression",
        difficulty="medium",
        error_signature="ConnectionPoolTimeout: timeout waiting for available connection",
        expected_hypotheses=[
            "Database connection pool exhaustion",
            "Slow query regression",
            "Network latency increase",
        ],
        expected_tool_sequence=["search_code", "git_history", "get_file", "git_diff"],
    ),
    BenchmarkIncident(
        id="bench_002",
        title="Search endpoint 500 errors after frontend deploy",
        description="Search API returning 500s since 09:15 UTC. "
                    "Frontend deploy at 09:00 UTC added new search parameters. "
                    "Backend was not deployed.",
        service="search-api",
        expected_root_cause="New frontend sends unsupported query parameter causing validation error",
        expected_files=["src/handlers/search.js", "src/validators/query.js"],
        expected_commits=["fed5678"],
        severity="SEV-2",
        category="deployment_regression",
        difficulty="easy",
        error_signature="ValidationError: unknown parameter 'facets'",
        expected_hypotheses=[
            "Frontend sends unknown parameter",
            "Backend validation too strict",
            "Missing parameter schema update",
        ],
        expected_tool_sequence=["search_code", "git_history", "git_diff"],
    ),
    BenchmarkIncident(
        id="bench_003",
        title="Memory leak in worker after library upgrade",
        description="Worker process memory growing 50MB/hour since v3.2.0 upgrade. "
                    "OOM killed after 4 hours. Was stable before upgrade.",
        service="worker",
        expected_root_cause="New version of 'image-processor' library holds references in global cache",
        expected_files=["src/worker.js", "package.json"],
        expected_commits=["ghi9012"],
        severity="SEV-1",
        category="deployment_regression",
        difficulty="hard",
        error_signature="JavaScript heap out of memory",
        expected_hypotheses=[
            "Memory leak in new library version",
            "Cache not being evicted",
            "Event listener leak",
            "Circular reference in data",
        ],
        expected_tool_sequence=["search_code", "git_history", "get_file", "git_diff", "grep_log"],
    ),

    # --- Code Changes ---
    BenchmarkIncident(
        id="bench_004",
        title="Null pointer exception in user profile",
        description="Intermittent NPE in UserService.getProfile. "
                    "Affects ~5% of users. Started after commit def456.",
        service="user-service",
        expected_root_cause="Missing null check when user has no profile photo",
        expected_files=["src/services/user.py", "src/handlers/profile.py"],
        expected_commits=["def4567"],
        severity="SEV-2",
        category="code_change",
        difficulty="easy",
        error_signature="NullPointerException at profile.py:42",
        expected_hypotheses=[
            "Missing null check on profile photo",
            "Race condition in profile creation",
            "Stale cache entry",
        ],
        expected_tool_sequence=["search_code", "git_history", "get_file"],
    ),
    BenchmarkIncident(
        id="bench_005",
        title="Race condition in order processing",
        description="Orders being charged twice intermittently. "
                    "~0.1% of orders affected. No obvious pattern.",
        service="order-service",
        expected_root_cause="Missing distributed lock allows duplicate charge processing",
        expected_files=["src/services/order.py", "src/workers/charge.py", "src/db/locks.py"],
        expected_commits=["jkl3456"],
        severity="SEV-1",
        category="code_change",
        difficulty="hard",
        error_signature="DuplicateChargeError: order already charged",
        expected_hypotheses=[
            "Race condition in charge processing",
            "Missing idempotency key check",
            "Database deadlock causing retry",
            "Message queue duplicate delivery",
        ],
        expected_tool_sequence=["search_code", "git_history", "get_file", "grep_log"],
    ),
    BenchmarkIncident(
        id="bench_006",
        title="Off-by-one error in pagination",
        description="Last page of results always empty. "
                    "Reported by multiple customers since deploy.",
        service="catalog-api",
        expected_root_cause="Off-by-one in LIMIT calculation using <= instead of <",
        expected_files=["src/handlers/catalog.py", "src/utils/pagination.py"],
        expected_commits=["mno7890"],
        severity="SEV-3",
        category="code_change",
        difficulty="easy",
        expected_hypotheses=[
            "Off-by-one in pagination query",
            "Missing boundary check",
            "Incorrect total count",
        ],
        expected_tool_sequence=["search_code", "get_file"],
    ),

    # --- Infrastructure ---
    BenchmarkIncident(
        id="bench_007",
        title="Redis connection timeout cascade",
        description="Multiple services timing out on Redis. "
                    "Started at 03:00 UTC. Redis memory at 98%.",
        service="cache-service",
        expected_root_cause="Redis instance OOM from unbounded key growth in session store",
        expected_files=["config/redis.js", "src/services/session.js"],
        expected_commits=[],
        severity="SEV-2",
        category="infrastructure",
        difficulty="medium",
        error_signature="RedisConnectionTimeout: connection timed out after 5000ms",
        expected_hypotheses=[
            "Redis memory exhaustion",
            "Network partition",
            "Redis process crash loop",
            "Too many connections",
        ],
        expected_tool_sequence=["search_code", "grep_log"],
    ),
    BenchmarkIncident(
        id="bench_008",
        title="Disk space exhaustion on log volume",
        description="Application crashing with 'No space left on device'. "
                    "Log volume at 100%.",
        service="api-gateway",
        expected_root_cause="Debug logging enabled in production filling disk rapidly",
        expected_files=["config/logging.js", "src/middleware/access_log.js"],
        expected_commits=[],
        severity="SEV-2",
        category="infrastructure",
        difficulty="easy",
        error_signature="ENOSPC: no space left on device",
        expected_hypotheses=[
            "Debug logging too verbose",
            "Log rotation not working",
            "Large response bodies logged",
        ],
        expected_tool_sequence=["search_code", "grep_log"],
    ),

    # --- Dependency Issues ---
    BenchmarkIncident(
        id="bench_009",
        title="SSL certificate expiry causing connection failures",
        description="All outbound HTTPS connections failing. "
                    "Started at 00:00 UTC. Root CA cert expired.",
        service="auth-service",
        expected_root_cause="System CA certificate bundle not updated, expired root cert",
        expected_files=["Dockerfile", "config/ssl.js"],
        expected_commits=[],
        severity="SEV-1",
        category="dependency",
        difficulty="medium",
        error_signature="SSLHandshakeError: certificate verify failed",
        expected_hypotheses=[
            "Expired SSL certificate",
            "Missing intermediate certificate",
            "Wrong certificate chain",
            "Clock skew",
        ],
        expected_tool_sequence=["get_file", "grep_log"],
    ),
    BenchmarkIncident(
        id="bench_010",
        title="Third-party API breaking change",
        description="Payment processing failing with 422 errors. "
                    "Started after vendor deployed new API version.",
        service="payment-api",
        expected_root_cause="Vendor API v3 removed deprecated field 'currency_code' we depend on",
        expected_files=["src/clients/payment_vendor.py", "src/schemas/payment.py"],
        expected_commits=[],
        severity="SEV-1",
        category="dependency",
        difficulty="medium",
        error_signature="HTTP 422: Unprocessable Entity - unknown field 'currency_code'",
        expected_hypotheses=[
            "Vendor API breaking change",
            "Missing API version header",
            "Request schema mismatch",
        ],
        expected_tool_sequence=["search_code", "get_file", "grep_log"],
    ),

    # --- Configuration ---
    BenchmarkIncident(
        id="bench_011",
        title="Feature flag causing 50% error rate",
        description="New feature flag 'enhanced_search' causing errors for flagged users. "
                    "50% of users affected.",
        service="search-api",
        expected_root_cause="Feature flag enabled code path that references non-existent Elasticsearch index",
        expected_files=["src/services/search.js", "config/features.js", "config/elasticsearch.js"],
        expected_commits=["pqr1234"],
        severity="SEV-1",
        category="configuration",
        difficulty="medium",
        error_signature="IndexNotFoundException: index 'search_v2' does not exist",
        expected_hypotheses=[
            "Feature flag references missing index",
            "Index not created yet",
            "Wrong index name in config",
        ],
        expected_tool_sequence=["search_code", "get_file", "git_diff"],
    ),
    BenchmarkIncident(
        id="bench_012",
        title="Missing environment variable after migration",
        description="Service crashing on startup with undefined variable. "
                    "Started after K8s migration.",
        service="notification-service",
        expected_root_cause="Missing SMTP_PASSWORD env var not migrated to new K8s secret",
        expected_files=["src/config.js", "k8s/deployment.yaml"],
        expected_commits=[],
        severity="SEV-2",
        category="configuration",
        difficulty="easy",
        expected_hypotheses=[
            "Missing environment variable",
            "Secret not mounted",
            "Wrong secret name",
        ],
        expected_tool_sequence=["search_code", "get_file"],
    ),
]


def get_benchmark_dataset() -> List[Dict]:
    """Get the full benchmark dataset."""
    return [
        {
            "id": b.id,
            "title": b.title,
            "description": b.description,
            "service": b.service,
            "expected_root_cause": b.expected_root_cause,
            "expected_files": b.expected_files,
            "expected_commits": b.expected_commits,
            "severity": b.severity,
            "category": b.category,
            "difficulty": b.difficulty,
            "error_signature": b.error_signature,
            "expected_hypotheses": b.expected_hypotheses,
            "expected_tool_sequence": b.expected_tool_sequence,
        }
        for b in BENCHMARK_DATASET
    ]


def get_benchmark_by_id(bench_id: str) -> Dict:
    """Get a single benchmark by ID."""
    for b in BENCHMARK_DATASET:
        if b.id == bench_id:
            return get_benchmark_dataset()[BENCHMARK_DATASET.index(b)]
    return None


def get_benchmarks_by_category(category: str) -> List[Dict]:
    """Get benchmarks filtered by category."""
    return [b for b in get_benchmark_dataset() if b["category"] == category]


def get_benchmarks_by_difficulty(difficulty: str) -> List[Dict]:
    """Get benchmarks filtered by difficulty."""
    return [b for b in get_benchmark_dataset() if b["difficulty"] == difficulty]
