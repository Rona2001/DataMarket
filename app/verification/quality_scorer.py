"""
Quality Scorer — evaluates a dataset across 5 dimensions and produces
a weighted 0–100 score + per-dimension breakdown.

Dimensions and weights:
  1. Completeness   (30%) — how many values are non-null
  2. Consistency    (20%) — mixed types, duplicate rows
  3. Schema quality (20%) — column names, metadata richness
  4. Size adequacy  (15%) — enough rows to be useful
  5. GDPR readiness (15%) — based on PII scan results + seller declarations

A score ≥ 80 = "Verified" label
A score 60–79 = "Reviewed"
A score < 60   = "Needs improvement"
"""
import pandas as pd
from typing import Optional


WEIGHTS = {
    "completeness": 0.30,
    "consistency": 0.20,
    "schema_quality": 0.20,
    "size_adequacy": 0.15,
    "gdpr_readiness": 0.15,
}


# ── Main scorer ───────────────────────────────────────────────────────────────

def score_dataset(
    df: pd.DataFrame,
    pii_report: dict,
    seller_declared_gdpr: bool = False,
    seller_declared_no_pii: bool = False,
) -> dict:
    """
    Run all checks and return:
        {
          "score": float (0-100),
          "label": "verified" | "reviewed" | "needs_improvement",
          "dimensions": { ... },
          "recommendations": [ "..." ],
          "passed": bool
        }
    """
    dimensions = {}
    recommendations = []

    dimensions["completeness"] = _score_completeness(df, recommendations)
    dimensions["consistency"] = _score_consistency(df, recommendations)
    dimensions["schema_quality"] = _score_schema(df, recommendations)
    dimensions["size_adequacy"] = _score_size(df, recommendations)
    dimensions["gdpr_readiness"] = _score_gdpr(
        pii_report, seller_declared_gdpr, seller_declared_no_pii, recommendations
    )

    weighted_score = sum(
        dimensions[dim]["score"] * WEIGHTS[dim] for dim in dimensions
    )
    final_score = round(weighted_score, 1)

    if final_score >= 80:
        label = "verified"
    elif final_score >= 60:
        label = "reviewed"
    else:
        label = "needs_improvement"

    return {
        "score": final_score,
        "label": label,
        "passed": final_score >= 60,
        "dimensions": dimensions,
        "recommendations": recommendations,
    }


# ── Dimension scorers ─────────────────────────────────────────────────────────

def _score_completeness(df: pd.DataFrame, recs: list) -> dict:
    """Penalise missing values. Score = mean non-null rate across columns."""
    null_rates = df.isnull().mean()
    completeness = 1 - null_rates.mean()
    score = round(completeness * 100, 1)

    bad_cols = null_rates[null_rates > 0.2].index.tolist()
    if bad_cols:
        recs.append(
            f"Columns with >20% missing values: {', '.join(bad_cols[:5])}. "
            "Consider imputation or removing low-quality columns."
        )

    return {
        "score": score,
        "details": {
            "mean_null_rate_pct": round(null_rates.mean() * 100, 2),
            "columns_over_20pct_null": bad_cols,
        },
    }


def _score_consistency(df: pd.DataFrame, recs: list) -> dict:
    """Check for duplicate rows and mixed-type columns."""
    score = 100.0
    details = {}

    # Duplicate rows
    dup_count = df.duplicated().sum()
    dup_pct = dup_count / max(len(df), 1) * 100
    details["duplicate_rows"] = int(dup_count)
    details["duplicate_pct"] = round(dup_pct, 2)
    if dup_pct > 5:
        penalty = min(30, dup_pct)
        score -= penalty
        recs.append(
            f"{dup_count} duplicate rows detected ({dup_pct:.1f}%). "
            "De-duplicating is recommended."
        )

    # Mixed types in object columns (e.g. numbers stored as strings)
    mixed_cols = []
    for col in df.select_dtypes(include="object").columns:
        sample = df[col].dropna().head(100)
        numeric_count = pd.to_numeric(sample, errors="coerce").notna().sum()
        if 0 < numeric_count < len(sample) * 0.9:
            mixed_cols.append(col)

    details["mixed_type_columns"] = mixed_cols
    if mixed_cols:
        score -= min(20, len(mixed_cols) * 5)
        recs.append(
            f"Mixed-type values detected in: {', '.join(mixed_cols[:5])}. "
            "Ensure consistent data types per column."
        )

    return {"score": max(0.0, round(score, 1)), "details": details}


def _score_schema(df: pd.DataFrame, recs: list) -> dict:
    """Reward good column naming and schema clarity."""
    score = 100.0
    details = {}

    # Generic column names (col0, column_1, unnamed, etc.)
    generic_pattern = ["unnamed", "column", "col", "field", "var", "x", "y"]
    generic_cols = [
        c for c in df.columns
        if any(c.lower().startswith(p) for p in generic_pattern)
    ]
    details["generic_column_names"] = generic_cols
    if generic_cols:
        penalty = min(30, len(generic_cols) * 6)
        score -= penalty
        recs.append(
            f"Uninformative column names detected: {', '.join(generic_cols[:5])}. "
            "Use descriptive names to improve discoverability."
        )

    # Too few columns
    if len(df.columns) < 2:
        score -= 20
        recs.append("Dataset has only 1 column. Consider providing richer data.")

    details["total_columns"] = len(df.columns)
    details["column_names"] = df.columns.tolist()

    return {"score": max(0.0, round(score, 1)), "details": details}


def _score_size(df: pd.DataFrame, recs: list) -> dict:
    """Datasets should have enough rows to be useful."""
    n_rows = len(df)
    score: float

    if n_rows >= 1000:
        score = 100.0
    elif n_rows >= 500:
        score = 85.0
    elif n_rows >= 100:
        score = 65.0
    elif n_rows >= 50:
        score = 45.0
    else:
        score = 20.0
        recs.append(
            f"Dataset only has {n_rows} rows. Buyers may find this too small. "
            "Consider enriching or combining with other sources."
        )

    return {"score": score, "details": {"num_rows": n_rows}}


def _score_gdpr(
    pii_report: dict,
    seller_declared_gdpr: bool,
    seller_declared_no_pii: bool,
    recs: list,
) -> dict:
    score = 100.0
    details = {
        "pii_risk_level": pii_report.get("risk_level", "none"),
        "seller_declared_gdpr": seller_declared_gdpr,
        "seller_declared_no_pii": seller_declared_no_pii,
    }

    risk = pii_report.get("risk_level", "none")

    if risk == "high":
        score -= 60
        recs.append(
            "HIGH PII risk detected. Dataset cannot be published without "
            "anonymization or explicit GDPR compliance documentation."
        )
    elif risk == "medium":
        score -= 30
        recs.append(
            "Moderate PII risk. Verify that data subjects have consented and "
            "that the dataset is properly anonymized or pseudonymized."
        )
    elif risk == "low":
        score -= 10

    # Reward seller declarations
    if seller_declared_gdpr:
        score = min(100.0, score + 15)
    if seller_declared_no_pii and risk == "none":
        score = min(100.0, score + 10)

    if not seller_declared_gdpr and risk != "none":
        recs.append(
            "Tick the GDPR compliance checkbox and provide a data origin "
            "statement to improve your dataset's trust score."
        )

    return {"score": max(0.0, round(score, 1)), "details": details}
