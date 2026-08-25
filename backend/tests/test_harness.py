"""Tests for the evaluation harness."""
import pytest
from app.services.harness import EvaluationHarness, format_report_text, format_report_json
from app.services.benchmark_dataset import BENCHMARK_DATASET


class TestEvaluationHarness:
    def test_run_single_benchmark_mock(self, sample_benchmark):
        harness = EvaluationHarness()
        result = harness.run_benchmark(sample_benchmark)
        assert result.benchmark_id == sample_benchmark["id"]
        assert result.status in ("passed", "failed")
        assert result.duration_ms >= 0
        assert result.evidence_count > 0

    def test_run_all_benchmarks_mock(self):
        harness = EvaluationHarness()
        report = harness.run_all()
        assert report.total_benchmarks == len(BENCHMARK_DATASET)
        assert report.passed + report.failed + report.errors == report.total_benchmarks
        assert report.avg_duration_ms >= 0
        assert report.avg_grounding_score >= 0

    def test_root_cause_scoring(self, sample_benchmark):
        harness = EvaluationHarness()
        mock_rc = {"summary": sample_benchmark["expected_root_cause"], "confidence": "high", "hypotheses_count": 3}
        result = harness.run_benchmark(sample_benchmark, mock_root_cause=mock_rc)
        assert result.root_cause_correct is True

    def test_root_cause_wrong(self, sample_benchmark):
        harness = EvaluationHarness()
        mock_rc = {"summary": "Completely wrong root cause about something else entirely", "confidence": "high", "hypotheses_count": 3}
        result = harness.run_benchmark(sample_benchmark, mock_root_cause=mock_rc)
        assert result.root_cause_correct is False

    def test_file_scoring(self, sample_benchmark):
        harness = EvaluationHarness()
        mock_ev = [
            {"source": "code_search", "file": f, "content": "code", "line": 1}
            for f in sample_benchmark["expected_files"]
        ]
        result = harness.run_benchmark(sample_benchmark, mock_evidence=mock_ev)
        assert len(result.files_missed) == 0
        assert len(result.files_correct) == len(sample_benchmark["expected_files"])

    def test_file_scoring_partial(self, sample_benchmark):
        harness = EvaluationHarness()
        mock_ev = [{"source": "code_search", "file": sample_benchmark["expected_files"][0], "content": "code", "line": 1}]
        result = harness.run_benchmark(sample_benchmark, mock_evidence=mock_ev)
        assert len(result.files_correct) == 1
        assert len(result.files_missed) == len(sample_benchmark["expected_files"]) - 1

    def test_report_generation(self):
        harness = EvaluationHarness()
        report = harness.run_all()
        text = format_report_text(report)
        assert "Sentinel Evaluation Report" in text
        assert "Total:" in text

    def test_report_json(self):
        import json
        harness = EvaluationHarness()
        report = harness.run_all()
        json_str = format_report_json(report)
        data = json.loads(json_str)
        assert "run_id" in data
        assert "total_benchmarks" in data

    def test_error_handling(self):
        harness = EvaluationHarness()
        bad_benchmark = {"id": "bad", "title": "", "description": "", "service": "", "expected_root_cause": "", "expected_files": [], "expected_commits": [], "severity": "", "category": "", "difficulty": ""}
        result = harness.run_benchmark(bad_benchmark)
        assert result.benchmark_id == "bad"

    def test_category_results(self):
        harness = EvaluationHarness()
        report = harness.run_all()
        assert len(report.category_results) > 0
        for cat, stats in report.category_results.items():
            assert "passed" in stats
            assert "total" in stats

    def test_difficulty_results(self):
        harness = EvaluationHarness()
        report = harness.run_all()
        assert len(report.difficulty_results) > 0
        for diff, stats in report.difficulty_results.items():
            assert stats["total"] > 0

    def test_results_list_populated(self):
        harness = EvaluationHarness()
        report = harness.run_all()
        assert len(report.results) == len(BENCHMARK_DATASET)
        for r in report.results:
            assert "benchmark_id" in r
            assert "status" in r


class TestBenchmarkDataset:
    def test_dataset_size(self):
        assert len(BENCHMARK_DATASET) >= 10

    def test_all_have_ids(self):
        for b in BENCHMARK_DATASET:
            assert b.id.startswith("bench_")

    def test_all_have_expected_files(self):
        for b in BENCHMARK_DATASET:
            assert len(b.expected_files) > 0, f"{b.id} has no expected files"

    def test_get_benchmark_dataset(self):
        from app.services.benchmark_dataset import get_benchmark_dataset
        data = get_benchmark_dataset()
        assert len(data) == len(BENCHMARK_DATASET)
        assert all("id" in d for d in data)

    def test_get_by_category(self):
        from app.services.benchmark_dataset import get_benchmarks_by_category
        dep = get_benchmarks_by_category("deployment_regression")
        assert len(dep) >= 2

    def test_get_by_difficulty(self):
        from app.services.benchmark_dataset import get_benchmarks_by_difficulty
        easy = get_benchmarks_by_difficulty("easy")
        assert len(easy) >= 2

    def test_get_by_id(self):
        from app.services.benchmark_dataset import get_benchmark_by_id
        result = get_benchmark_by_id("bench_001")
        assert result is not None
        assert result["id"] == "bench_001"

    def test_get_nonexistent(self):
        from app.services.benchmark_dataset import get_benchmark_by_id
        result = get_benchmark_by_id("bench_nonexistent")
        assert result is None
