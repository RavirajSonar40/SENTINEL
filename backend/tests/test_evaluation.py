"""Tests for evaluation scoring functions."""
import pytest
from app.services.evaluation import (
    evaluate_grounding,
    evaluate_retrieval,
    evaluate_investigation_quality,
)


class TestGrounding:
    def test_grounded_with_all_evidence(self, sample_root_cause, sample_evidence):
        result = evaluate_grounding(
            sample_root_cause["summary"],
            sample_evidence,
            affected_files=["src/payment.py"],
        )
        assert result["verdict"] == "GROUNDED"
        assert result["grounding_score"] >= 0.5
        assert result["passed_checks"] >= 2

    def test_ungrounded_with_no_evidence(self):
        result = evaluate_grounding("Some claim about code", [])
        assert result["verdict"] == "UNGROUNDed"
        assert result["grounding_score"] < 0.5

    def test_vague_claim_gets_low_score(self, sample_evidence):
        result = evaluate_grounding("x", sample_evidence)
        # Vague claim fails claim_is_specific check
        specific_check = [c for c in result["checks"] if c["check"] == "claim_is_specific"]
        assert specific_check[0]["passed"] is False

    def test_has_temporal_evidence(self):
        evidence = [{"source": "deployment", "file": "", "content": "deployed v2.8.1"}]
        result = evaluate_grounding("Config change caused issue", evidence)
        temporal_check = [c for c in result["checks"] if c["check"] == "temporal_evidence"]
        assert temporal_check[0]["passed"] is True

    def test_has_code_evidence(self):
        evidence = [{"source": "code_search", "file": "src/app.py", "content": "code"}]
        result = evaluate_grounding("Code issue in app.py", evidence)
        code_check = [c for c in result["checks"] if c["check"] == "code_evidence"]
        assert code_check[0]["passed"] is True

    def test_affected_files_found(self):
        evidence = [
            {"source": "code_search", "file": "src/app.py", "content": "code"},
            {"source": "code_search", "file": "src/config.py", "content": "config"},
        ]
        result = evaluate_grounding("Issue in app and config", evidence, ["src/app.py", "src/config.py"])
        files_check = [c for c in result["checks"] if c["check"] == "affected_files_in_evidence"]
        assert files_check[0]["passed"] is True

    def test_returns_all_checks(self):
        result = evaluate_grounding("test claim about something specific enough", [{"source": "code_search", "file": "a.py", "content": "c"}], ["a.py"])
        assert len(result["checks"]) == 5
        assert "grounding_score" in result
        assert "verdict" in result


class TestRetrieval:
    def test_perfect_retrieval(self):
        retrieved = [
            {"file": "src/a.py"},
            {"file": "src/b.py"},
            {"file": "src/c.py"},
        ]
        result = evaluate_retrieval(retrieved, ["src/a.py", "src/b.py", "src/c.py"], k=3)
        assert result["precision_at_k"] == 1.0
        assert result["recall_at_k"] == 1.0

    def test_partial_retrieval(self):
        retrieved = [
            {"file": "src/a.py"},
            {"file": "src/other.py"},
            {"file": "src/b.py"},
        ]
        result = evaluate_retrieval(retrieved, ["src/a.py", "src/b.py"], k=3)
        assert result["precision_at_k"] > 0

    def test_no_retrieval(self):
        retrieved = [{"file": "src/other.py"}]
        result = evaluate_retrieval(retrieved, ["src/a.py"])
        assert result["precision_at_k"] == 0
        assert result["recall_at_k"] == 0

    def test_empty_retrieved(self):
        result = evaluate_retrieval([], ["src/a.py"])
        assert result["precision_at_k"] == 0
        assert result["recall_at_k"] == 0

    def test_empty_relevant(self):
        retrieved = [{"file": "src/a.py"}]
        result = evaluate_retrieval(retrieved, [])
        assert result["recall_at_k"] == 0


class TestInvestigationQuality:
    def test_high_quality_investigation(self):
        inv = {
            "evidence_count": 8,
            "hypotheses_count": 4,
            "confidence": "high",
            "tasks_completed": 6,
            "tasks_failed": 0,
            "root_cause_found": True,
            "affected_files": ["src/a.py", "src/b.py"],
        }
        benchmark = {"expected_files": ["src/a.py", "src/b.py"]}
        result = evaluate_investigation_quality(inv, benchmark)
        assert result["overall"] >= 0.7
        assert result["root_cause_found"] == 1.0
        assert result["file_accuracy"] == 1.0

    def test_low_quality_investigation(self):
        inv = {
            "evidence_count": 1,
            "hypotheses_count": 1,
            "confidence": "low",
            "tasks_completed": 1,
            "tasks_failed": 3,
            "root_cause_found": False,
        }
        result = evaluate_investigation_quality(inv)
        assert result["overall"] < 0.5
        assert result["root_cause_found"] == 0

    def test_without_benchmark(self):
        inv = {
            "evidence_count": 5,
            "hypotheses_count": 3,
            "confidence": "medium",
            "tasks_completed": 4,
            "tasks_failed": 1,
            "root_cause_found": True,
        }
        result = evaluate_investigation_quality(inv)
        assert result["overall"] > 0
