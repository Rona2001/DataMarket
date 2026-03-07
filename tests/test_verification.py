"""Tests for PII detection and quality scoring."""
import pytest
import pandas as pd
from app.verification.pii_detector import scan_for_pii
from app.verification.quality_scorer import score_dataset


class TestPIIDetector:
    def test_clean_dataset_no_pii(self):
        df = pd.DataFrame({
            "product_id": [1, 2, 3],
            "category": ["electronics", "books", "clothing"],
            "price_eur": [299.99, 12.50, 45.00],
            "stock": [100, 250, 75],
        })
        result = scan_for_pii(df)
        assert result["pii_detected"] is False
        assert result["risk_level"] == "none"
        assert result["flagged_columns"] == []

    def test_detects_email_column(self):
        df = pd.DataFrame({
            "user_id": [1, 2, 3],
            "email": ["alice@example.com", "bob@test.fr", "charlie@mail.org"],
            "score": [88, 92, 75],
        })
        result = scan_for_pii(df)
        assert result["pii_detected"] is True
        assert result["risk_level"] in ("medium", "high")
        flagged_names = [f["column"] for f in result["flagged_columns"]]
        assert "email" in flagged_names

    def test_detects_email_content(self):
        df = pd.DataFrame({
            "contact_info": ["alice@example.com", "bob@test.fr", "no-email-here"],
        })
        result = scan_for_pii(df)
        assert result["pii_detected"] is True

    def test_detects_ssn_column_name(self):
        df = pd.DataFrame({
            "ssn": ["1 85 05 75 123 456 78", "2 92 03 69 987 654 32"],
            "name": ["Alice", "Bob"],
        })
        result = scan_for_pii(df)
        assert result["pii_detected"] is True
        assert result["risk_level"] == "high"

    def test_detects_iban_content(self):
        df = pd.DataFrame({
            "bank_ref": ["FR7630006000011234567890189", "DE89370400440532013000"],
        })
        result = scan_for_pii(df)
        assert result["pii_detected"] is True
        assert result["risk_level"] == "high"

    def test_detects_ip_addresses(self):
        df = pd.DataFrame({
            "ip_address": ["192.168.1.1", "10.0.0.42", "172.16.0.1"],
        })
        result = scan_for_pii(df)
        assert result["pii_detected"] is True

    def test_summary_populated(self):
        df = pd.DataFrame({"email": ["test@test.com"]})
        result = scan_for_pii(df)
        assert len(result["summary"]) > 0


class TestQualityScorer:
    def _make_clean_df(self, n=200):
        return pd.DataFrame({
            "product_id": range(n),
            "product_name": [f"Product {i}" for i in range(n)],
            "price": [float(i * 10) for i in range(n)],
            "category": ["electronics"] * n,
            "in_stock": [True] * n,
        })

    def test_clean_dataset_high_score(self):
        df = self._make_clean_df(500)
        pii = {"pii_detected": False, "risk_level": "none", "flagged_columns": []}
        result = score_dataset(df, pii, seller_declared_gdpr=True)
        assert result["score"] >= 75
        assert result["passed"] is True

    def test_small_dataset_penalised(self):
        df = self._make_clean_df(10)
        pii = {"pii_detected": False, "risk_level": "none", "flagged_columns": []}
        result = score_dataset(df, pii)
        size_score = result["dimensions"]["size_adequacy"]["score"]
        assert size_score < 50

    def test_high_null_rate_penalised(self):
        df = pd.DataFrame({
            "col_a": [1, None, None, None, None],
            "col_b": [None, None, None, None, 5],
        })
        pii = {"pii_detected": False, "risk_level": "none", "flagged_columns": []}
        result = score_dataset(df, pii)
        completeness_score = result["dimensions"]["completeness"]["score"]
        assert completeness_score < 50

    def test_duplicate_rows_penalised(self):
        row = {"id": 1, "name": "Alice", "value": 100}
        df = pd.DataFrame([row] * 50)
        pii = {"pii_detected": False, "risk_level": "none", "flagged_columns": []}
        result = score_dataset(df, pii)
        consistency_score = result["dimensions"]["consistency"]["score"]
        assert consistency_score < 70

    def test_high_pii_risk_reduces_gdpr_score(self):
        df = self._make_clean_df(200)
        pii = {"pii_detected": True, "risk_level": "high", "flagged_columns": [{"column": "email"}]}
        result = score_dataset(df, pii, seller_declared_gdpr=False)
        gdpr_score = result["dimensions"]["gdpr_readiness"]["score"]
        assert gdpr_score <= 40

    def test_seller_gdpr_declaration_boosts_score(self):
        df = self._make_clean_df(200)
        pii_none = {"pii_detected": False, "risk_level": "none", "flagged_columns": []}

        without_gdpr = score_dataset(df, pii_none, seller_declared_gdpr=False)
        with_gdpr = score_dataset(df, pii_none, seller_declared_gdpr=True)

        assert with_gdpr["score"] >= without_gdpr["score"]

    def test_recommendations_populated_for_bad_data(self):
        df = pd.DataFrame({"col0": [None] * 10, "column_1": [None] * 10})
        pii = {"pii_detected": False, "risk_level": "none", "flagged_columns": []}
        result = score_dataset(df, pii)
        assert len(result["recommendations"]) > 0

    def test_label_verified_for_high_score(self):
        df = self._make_clean_df(1000)
        pii = {"pii_detected": False, "risk_level": "none", "flagged_columns": []}
        result = score_dataset(df, pii, seller_declared_gdpr=True)
        assert result["label"] == "verified"

    def test_label_needs_improvement_for_low_score(self):
        df = pd.DataFrame({"x": [None] * 5})
        pii = {"pii_detected": True, "risk_level": "high", "flagged_columns": [{"column": "x"}]}
        result = score_dataset(df, pii, seller_declared_gdpr=False)
        assert result["label"] == "needs_improvement"
        assert result["passed"] is False
