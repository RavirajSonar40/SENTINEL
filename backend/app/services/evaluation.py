"""Evaluation framework — benchmarks and grounding checks."""
import json
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone


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
    difficulty: str  # easy, medium, hard


# --- Sample Benchmark Dataset ---

BENCHMARK_DATASET: List[BenchmarkIncident] = [
    BenchmarkIncident(
        id="bench_001",
        title="Payment API latency spike after deployment",
        description="p95 latency increased from 200ms to 4.2s after deployment v2.8.1",
        service="payment-api",
        expected_root_cause="Database connection pool exhaustion from config change",
        expected_files=["src/db/pool.js", "config/database.js"],
        expected_commits=["abc123"],
        severity="SEV-1",
        category="deployment_regression",
        difficulty="medium",
    ),
    BenchmarkIncident(
        id="bench_002",
        title="Null pointer exception in user service",
        description="Intermittent NPE in UserService.getProfile after recent deploy",
        service="user-service",
        expected_root_cause="Missing null check in user profile handler",
        expected_files=["src/services/user.py", "src/handlers/profile.py"],
        expected_commits=["def456"],
        severity="SEV-2",
        category="code_change",
        difficulty="easy",
    ),
    BenchmarkIncident(
        id="bench_003",
        title="Redis connection timeout",
        description="Multiple services reporting Redis timeout errors",
        service="cache-service",
        expected_root_cause="Redis instance memory exhaustion",
        expected_files=["config/redis.js"],
        expected_commits=[],
        severity="SEV-2",
        category="infrastructure",
        difficulty="hard",
    ),
]


def get_benchmark_dataset() -> List[Dict]:
    """Get the benchmark dataset for evaluation."""
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
        }
        for b in BENCHMARK_DATASET
    ]


# --- Grounding Evaluation ---

def evaluate_grounding(
    root_cause_claim: str,
    evidence: List[Dict],
    affected_files: List[str] = None,
) -> Dict:
    """Evaluate if a root cause claim is grounded in evidence.

    For every important claim, check:
    - Does supporting evidence actually exist?
    - Is the claim contradicted by any evidence?
    """
    checks = []

    # Check 1: Is there any evidence at all?
    checks.append({
        "check": "evidence_exists",
        "passed": len(evidence) > 0,
        "detail": f"{len(evidence)} evidence items collected",
    })

    # Check 2: Are affected files mentioned in evidence?
    if affected_files:
        evidence_files = set()
        for ev in evidence:
            fp = ev.get("file", "")
            if fp:
                evidence_files.add(fp)

        mentioned = [f for f in affected_files if f in evidence_files]
        checks.append({
            "check": "affected_files_in_evidence",
            "passed": len(mentioned) > 0,
            "detail": f"{len(mentioned)}/{len(affected_files)} affected files found in evidence",
            "matched_files": mentioned,
        })

    # Check 3: Is there temporal evidence (deployment before incident)?
    has_temporal = any(
        ev.get("source") in ("deployment", "commit", "git_history")
        for ev in evidence
    )
    checks.append({
        "check": "temporal_evidence",
        "passed": has_temporal,
        "detail": "Deployment/commit evidence present" if has_temporal else "No temporal evidence found",
    })

    # Check 4: Is there code evidence?
    has_code = any(
        ev.get("source") in ("code_search", "file", "function", "commit")
        for ev in evidence
    )
    checks.append({
        "check": "code_evidence",
        "passed": has_code,
        "detail": "Code evidence present" if has_code else "No code evidence found",
    })

    # Check 5: Claim is not just "unknown" or empty
    is_specific = len(root_cause_claim.strip()) > 20 and "unknown" not in root_cause_claim.lower()
    checks.append({
        "check": "claim_is_specific",
        "passed": is_specific,
        "detail": "Claim is specific" if is_specific else "Claim is too vague or says 'unknown'",
    })

    # Overall grounding score
    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)
    grounding_score = passed / total if total > 0 else 0

    return {
        "grounding_score": round(grounding_score, 2),
        "passed_checks": passed,
        "total_checks": total,
        "verdict": "GROUNDED" if grounding_score >= 0.6 else "UNGROUNDed",
        "checks": checks,
    }


# --- Retrieval Evaluation ---

def evaluate_retrieval(
    retrieved_items: List[Dict],
    relevant_items: List[str],
    k: int = 10,
) -> Dict:
    """Evaluate retrieval quality using Precision@K, Recall@K, MRR."""
    retrieved_files = [item.get("file", "") for item in retrieved_items[:k]]
    relevant_set = set(relevant_items)

    # Precision@K
    hits = sum(1 for f in retrieved_files if f in relevant_set)
    precision_at_k = hits / k if k > 0 else 0

    # Recall@K
    recall_at_k = hits / len(relevant_set) if relevant_set else 0

    # MRR (Mean Reciprocal Rank)
    rr = 0
    for i, f in enumerate(retrieved_files):
        if f in relevant_set:
            rr = 1 / (i + 1)
            break

    return {
        "precision_at_k": round(precision_at_k, 3),
        "recall_at_k": round(recall_at_k, 3),
        "mrr": round(rr, 3),
        "relevant_found": hits,
        "relevant_total": len(relevant_set),
        "retrieved_count": len(retrieved_files),
    }


# --- Investigation Quality ---

def evaluate_investigation_quality(
    investigation: Dict,
    benchmark: Optional[Dict] = None,
) -> Dict:
    """Evaluate the quality of an investigation."""
    scores = {}

    # Evidence collection quality
    evidence_count = investigation.get("evidence_count", 0)
    scores["evidence_richness"] = min(evidence_count / 5, 1.0)  # 5+ evidence = full score

    # Hypothesis quality
    hypothesis_count = investigation.get("hypotheses_count", 0)
    scores["hypothesis_richness"] = min(hypothesis_count / 3, 1.0)  # 3+ hypotheses = full score

    # Confidence calibration
    confidence = investigation.get("confidence", "low")
    confidence_scores = {"high": 1.0, "medium": 0.6, "low": 0.3, "insufficient": 0.1}
    scores["confidence_calibration"] = confidence_scores.get(confidence, 0)

    # Task completion
    tasks_completed = investigation.get("tasks_completed", 0)
    tasks_failed = investigation.get("tasks_failed", 0)
    total_tasks = tasks_completed + tasks_failed
    scores["task_success_rate"] = tasks_completed / total_tasks if total_tasks > 0 else 0

    # Root cause found
    scores["root_cause_found"] = 1.0 if investigation.get("root_cause_found") else 0

    # Benchmark comparison (if available)
    if benchmark:
        expected_files = set(benchmark.get("expected_files", []))
        actual_files = set(investigation.get("affected_files", []))
        if expected_files:
            scores["file_accuracy"] = len(expected_files & actual_files) / len(expected_files)
        else:
            scores["file_accuracy"] = 0

    # Overall score
    scores["overall"] = round(sum(scores.values()) / len(scores), 3) if scores else 0

    return scores
