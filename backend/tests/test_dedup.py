"""Tests for deduplication service."""
import pytest
from unittest.mock import MagicMock
from app.services.dedup import compute_fingerprint, find_existing_incident


class TestFingerprint:
    def test_same_title_same_service(self):
        fp1 = compute_fingerprint("Payment API crash", "payment-api")
        fp2 = compute_fingerprint("Payment API crash", "payment-api")
        assert fp1 == fp2

    def test_different_title(self):
        fp1 = compute_fingerprint("Payment API crash", "payment-api")
        fp2 = compute_fingerprint("Search API crash", "payment-api")
        assert fp1 != fp2

    def test_different_service(self):
        fp1 = compute_fingerprint("API crash", "payment-api")
        fp2 = compute_fingerprint("API crash", "search-api")
        assert fp1 != fp2

    def test_includes_error_signature(self):
        fp1 = compute_fingerprint("Error", "api", error_signature="NullPointerException")
        fp2 = compute_fingerprint("Error", "api", error_signature="TimeoutException")
        assert fp1 != fp2

    def test_case_insensitive(self):
        fp1 = compute_fingerprint("PAYMENT API CRASH", "payment-api")
        fp2 = compute_fingerprint("payment api crash", "payment-api")
        assert fp1 == fp2

    def test_returns_string(self):
        fp = compute_fingerprint("test", "service")
        assert isinstance(fp, str)
        assert len(fp) > 0


class TestDeduplication:
    def test_no_existing_incident(self, mock_db):
        mock_db.query.return_value.filter.return_value.all.return_value = []
        result = find_existing_incident(
            title="Payment API crash",
            service="payment-api",
            error_signature="NPE",
            source="pagerduty",
            window_minutes=30,
            db=mock_db,
        )
        assert result is None

    def test_finds_existing_incident(self, mock_db):
        mock_incident = MagicMock()
        mock_incident.title = "Payment API crash"
        mock_incident.service_name = "payment-api"
        mock_incident.error_signature = "NPE"
        mock_incident.source = MagicMock()
        mock_incident.source.value = "pagerduty"
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_incident]
        result = find_existing_incident(
            title="Payment API crash",
            service="payment-api",
            error_signature="NPE",
            source="pagerduty",
            window_minutes=30,
            db=mock_db,
        )
        assert result is not None

    def test_returns_none_on_empty_db(self, mock_db):
        mock_db.query.return_value.filter.return_value.all.return_value = []
        result = find_existing_incident(
            title="Any incident",
            service="any-service",
            error_signature="",
            source="generic",
            window_minutes=60,
            db=mock_db,
        )
        assert result is None
