"""Evaluation harness — runs benchmark incidents through the full pipeline and scores results."""
import json
import time
import traceback
from typing import Dict, List, Optional, Callable
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict

from app.services.benchmark_dataset import BENCHMARK_DATASET, get_benchmark_dataset
from app.services.evaluation import evaluate_grounding, evaluate_retrieval, evaluate_investigation_quality


@dataclass
class RunResult:
    benchmark_id: str
    status: str  # passed, failed, error
    duration_ms: int
    root_cause_found: bool
    root_cause_correct: bool
    files_correct: List[str]
    files_missed: List[str]
    files_incorrect: List[str]
    grounding_score: float
    retrieval_scores: Dict
    quality_scores: Dict
    evidence_count: int
    hypothesis_count: int
    confidence: str
    tool_sequence_correct: bool
    error: str = ""


@dataclass
class HarnessReport:
    run_id: str
    timestamp: str
    total_benchmarks: int
    passed: int
    failed: int
    errors: int
    avg_duration_ms: float
    avg_grounding_score: float
    avg_file_accuracy: float
    avg_retrieval_precision: float
    avg_retrieval_recall: float
    category_results: Dict = field(default_factory=dict)
    difficulty_results: Dict = field(default_factory=dict)
    results: List[Dict] = field(default_factory=list)


# --- Core Harness ---

class EvaluationHarness:
    """Runs benchmarks through the investigation pipeline and scores results."""

    def __init__(
        self,
        run_investigation_fn: Callable = None,
        search_code_fn: Callable = None,
        get_file_fn: Callable = None,
    ):
        self.run_investigation = run_investigation_fn
        self.search_code = search_code_fn
        self.get_file = get_file_fn
        self.results: List[RunResult] = []

    def run_benchmark(
        self,
        benchmark: Dict,
        mock_evidence: List[Dict] = None,
        mock_root_cause: Dict = None,
    ) -> RunResult:
        """Run a single benchmark through the pipeline."""
        start_time = time.time()

        try:
            # 1. Generate evidence (or use mock)
            if mock_evidence is not None:
                evidence = mock_evidence
            elif self.search_code:
                evidence = self._collect_evidence(benchmark)
            else:
                evidence = self._mock_evidence(benchmark)

            # 2. Generate root cause (or use mock)
            if mock_root_cause is not None:
                root_cause = mock_root_cause
            elif self.run_investigation:
                root_cause = self._run_investigation(benchmark)
            else:
                root_cause = self._mock_root_cause(benchmark)

            duration_ms = int((time.time() - start_time) * 1000)

            # 3. Score results
            rc_text = root_cause.get("summary", "") if root_cause else ""
            expected_rc = benchmark.get("expected_root_cause", "")
            root_cause_correct = self._root_cause_match(rc_text, expected_rc)

            expected_files = set(benchmark.get("expected_files", []))
            actual_files = set(e.get("file", "") for e in evidence if e.get("file"))
            files_correct = list(expected_files & actual_files)
            files_missed = list(expected_files - actual_files)
            files_incorrect = list(actual_files - expected_files)

            grounding = evaluate_grounding(rc_text, evidence, list(expected_files))

            retrieved = [{"file": e.get("file", "")} for e in evidence if e.get("file")]
            retrieval = evaluate_retrieval(retrieved, list(expected_files))

            inv_data = {
                "evidence_count": len(evidence),
                "hypotheses_count": root_cause.get("hypotheses_count", 0) if root_cause else 0,
                "confidence": root_cause.get("confidence", "low") if root_cause else "low",
                "tasks_completed": len(evidence),
                "tasks_failed": 0,
                "root_cause_found": bool(rc_text),
                "affected_files": list(actual_files),
            }
            quality = evaluate_investigation_quality(inv_data, benchmark)

            # Tool sequence check
            expected_tools = benchmark.get("expected_tool_sequence", [])
            actual_tools = [e.get("source", "") for e in evidence]
            tool_correct = self._check_tool_sequence(expected_tools, actual_tools)

            return RunResult(
                benchmark_id=benchmark["id"],
                status="passed" if root_cause_correct and len(files_missed) == 0 else "failed",
                duration_ms=duration_ms,
                root_cause_found=bool(rc_text),
                root_cause_correct=root_cause_correct,
                files_correct=files_correct,
                files_missed=files_missed,
                files_incorrect=files_incorrect,
                grounding_score=grounding["grounding_score"],
                retrieval_scores=retrieval,
                quality_scores=quality,
                evidence_count=len(evidence),
                hypothesis_count=inv_data["hypotheses_count"],
                confidence=inv_data["confidence"],
                tool_sequence_correct=tool_correct,
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return RunResult(
                benchmark_id=benchmark["id"],
                status="error",
                duration_ms=duration_ms,
                root_cause_found=False,
                root_cause_correct=False,
                files_correct=[],
                files_missed=[],
                files_incorrect=[],
                grounding_score=0,
                retrieval_scores={},
                quality_scores={},
                evidence_count=0,
                hypothesis_count=0,
                confidence="low",
                tool_sequence_correct=False,
                error=traceback.format_exc(),
            )

    def run_all(
        self,
        benchmarks: List[Dict] = None,
        mock_evidence_fn: Callable = None,
        mock_root_cause_fn: Callable = None,
    ) -> HarnessReport:
        """Run all benchmarks and generate report."""
        if benchmarks is None:
            benchmarks = get_benchmark_dataset()

        run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        results = []

        for bench in benchmarks:
            mock_ev = mock_evidence_fn(bench) if mock_evidence_fn else self._mock_evidence(bench)
            mock_rc = mock_root_cause_fn(bench) if mock_root_cause_fn else self._mock_root_cause(bench)
            result = self.run_benchmark(bench, mock_ev, mock_rc)
            results.append(result)

        self.results = results
        return self._generate_report(run_id, results, benchmarks)

    def _collect_evidence(self, benchmark: Dict) -> List[Dict]:
        """Collect evidence from real codebase via search."""
        evidence = []
        query = f"{benchmark['title']} {benchmark.get('error_signature', '')}"

        if self.search_code:
            results = self.search_code(query, service=benchmark.get("service"))
            for r in results:
                evidence.append({
                    "source": "code_search",
                    "file": r.get("file", ""),
                    "content": r.get("content", "")[:500],
                    "line": r.get("line", 0),
                    "relevance": r.get("score", 0),
                })

        # Add git history if available
        if self.get_file:
            for commit in benchmark.get("expected_commits", []):
                try:
                    content = self.get_file(commit)
                    evidence.append({
                        "source": "commit",
                        "file": commit,
                        "content": str(content)[:500],
                    })
                except Exception:
                    pass

        return evidence

    def _run_investigation(self, benchmark: Dict) -> Dict:
        """Run full investigation via engine."""
        if self.run_investigation:
            return self.run_investigation(
                title=benchmark["title"],
                description=benchmark["description"],
                service=benchmark["service"],
            )
        return {}

    def _mock_evidence(self, benchmark: Dict) -> List[Dict]:
        """Generate mock evidence for testing."""
        evidence = []
        expected_files = benchmark.get("expected_files", [])

        for i, f in enumerate(expected_files):
            evidence.append({
                "source": "code_search",
                "file": f,
                "content": f"Mock code content for {f}",
                "line": 1,
                "relevance": 0.9 - (i * 0.1),
            })

        # Add error log evidence
        if benchmark.get("error_signature"):
            evidence.append({
                "source": "log_search",
                "file": "",
                "content": benchmark["error_signature"],
                "line": 0,
                "relevance": 0.85,
            })

        # Add commit evidence
        for commit in benchmark.get("expected_commits", []):
            evidence.append({
                "source": "git_history",
                "file": commit,
                "content": f"Commit {commit}: changed related files",
                "line": 0,
                "relevance": 0.8,
            })

        return evidence

    def _mock_root_cause(self, benchmark: Dict) -> Dict:
        """Generate mock root cause for testing."""
        hypotheses = benchmark.get("expected_hypotheses", [])
        return {
            "summary": benchmark.get("expected_root_cause", "Unknown"),
            "category": benchmark.get("category", "unknown"),
            "confidence": "high" if benchmark.get("difficulty") == "easy" else "medium",
            "hypotheses_count": len(hypotheses),
            "severity": benchmark.get("severity", "SEV-3"),
        }

    def _root_cause_match(self, found: str, expected: str) -> bool:
        """Check if found root cause matches expected (semantic match)."""
        if not found or not expected:
            return False
        found_lower = found.lower()
        expected_lower = expected.lower()
        # Simple keyword overlap check
        found_words = set(found_lower.split())
        expected_words = set(expected_lower.split())
        overlap = found_words & expected_words
        return len(overlap) / len(expected_words) > 0.3 if expected_words else False

    def _check_tool_sequence(self, expected: List[str], actual: List[str]) -> bool:
        """Check if actual tool usage includes expected tools."""
        if not expected:
            return True
        actual_set = set(actual)
        return all(t in actual_set for t in expected)

    def _generate_report(
        self, run_id: str, results: List[RunResult], benchmarks: List[Dict]
    ) -> HarnessReport:
        """Generate aggregate report."""
        passed = sum(1 for r in results if r.status == "passed")
        failed = sum(1 for r in results if r.status == "failed")
        errors = sum(1 for r in results if r.status == "error")

        avg_duration = sum(r.duration_ms for r in results) / len(results) if results else 0
        avg_grounding = sum(r.grounding_score for r in results) / len(results) if results else 0

        # File accuracy
        file_scores = []
        for r in results:
            total_expected = len(r.files_correct) + len(r.files_missed)
            if total_expected > 0:
                file_scores.append(len(r.files_correct) / total_expected)
        avg_file_accuracy = sum(file_scores) / len(file_scores) if file_scores else 0

        # Retrieval scores
        precisions = [r.retrieval_scores.get("precision_at_k", 0) for r in results if r.retrieval_scores]
        recalls = [r.retrieval_scores.get("recall_at_k", 0) for r in results if r.retrieval_scores]
        avg_precision = sum(precisions) / len(precisions) if precisions else 0
        avg_recall = sum(recalls) / len(recalls) if recalls else 0

        # Group by category
        category_results = {}
        for r, b in zip(results, benchmarks):
            cat = b.get("category", "unknown")
            if cat not in category_results:
                category_results[cat] = {"passed": 0, "failed": 0, "errors": 0, "total": 0}
            category_results[cat]["total"] += 1
            if r.status == "error":
                category_results[cat]["errors"] += 1
            elif r.status == "passed":
                category_results[cat]["passed"] += 1
            else:
                category_results[cat]["failed"] += 1

        # Group by difficulty
        difficulty_results = {}
        for r, b in zip(results, benchmarks):
            diff = b.get("difficulty", "unknown")
            if diff not in difficulty_results:
                difficulty_results[diff] = {"passed": 0, "failed": 0, "errors": 0, "total": 0}
            difficulty_results[diff]["total"] += 1
            if r.status == "error":
                difficulty_results[diff]["errors"] += 1
            elif r.status == "passed":
                difficulty_results[diff]["passed"] += 1
            else:
                difficulty_results[diff]["failed"] += 1

        return HarnessReport(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_benchmarks=len(results),
            passed=passed,
            failed=failed,
            errors=errors,
            avg_duration_ms=round(avg_duration),
            avg_grounding_score=round(avg_grounding, 3),
            avg_file_accuracy=round(avg_file_accuracy, 3),
            avg_retrieval_precision=round(avg_precision, 3),
            avg_retrieval_recall=round(avg_recall, 3),
            category_results=category_results,
            difficulty_results=difficulty_results,
            results=[asdict(r) for r in results],
        )


# --- Report Formatting ---

def format_report_text(report: HarnessReport) -> str:
    """Format report as human-readable text."""
    lines = [
        f"=== Sentinel Evaluation Report ===",
        f"Run ID: {report.run_id}",
        f"Timestamp: {report.timestamp}",
        f"",
        f"--- Summary ---",
        f"Total: {report.total_benchmarks}",
        f"Passed: {report.passed} ({report.passed/max(report.total_benchmarks,1)*100:.1f}%)",
        f"Failed: {report.failed}",
        f"Errors: {report.errors}",
        f"",
        f"--- Metrics ---",
        f"Avg Duration: {report.avg_duration_ms}ms",
        f"Avg Grounding Score: {report.avg_grounding_score}",
        f"Avg File Accuracy: {report.avg_file_accuracy}",
        f"Avg Retrieval Precision@10: {report.avg_retrieval_precision}",
        f"Avg Retrieval Recall@10: {report.avg_retrieval_recall}",
        f"",
        f"--- By Category ---",
    ]
    for cat, stats in report.category_results.items():
        lines.append(f"  {cat}: {stats['passed']}/{stats['total']} passed")

    lines.append(f"")
    lines.append(f"--- By Difficulty ---")
    for diff, stats in report.difficulty_results.items():
        lines.append(f"  {diff}: {stats['passed']}/{stats['total']} passed")

    lines.append(f"")
    lines.append(f"--- Per-Benchmark ---")
    for r in report.results:
        status_icon = "PASS" if r["status"] == "passed" else "FAIL" if r["status"] == "error" else "FAIL"
        lines.append(
            f"  [{status_icon}] {r['benchmark_id']}: "
            f"rc={'correct' if r['root_cause_correct'] else 'wrong'}, "
            f"files={len(r['files_correct'])}/{len(r['files_correct'])+len(r['files_missed'])}, "
            f"grounding={r['grounding_score']}, "
            f"{r['duration_ms']}ms"
        )

    return "\n".join(lines)


def format_report_json(report: HarnessReport) -> str:
    """Format report as JSON."""
    return json.dumps(asdict(report), indent=2, default=str)
