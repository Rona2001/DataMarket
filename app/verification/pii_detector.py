"""
PII Detector — scans dataset columns for personally identifiable information.

Uses two layers:
  1. Pattern matching  — regex for emails, phone numbers, IBANs, SSNs, IPs, etc.
  2. Column name heuristics — flags suspicious column names instantly

For production, plug in Microsoft Presidio (already in requirements.txt)
for deeper NLP-based detection on text columns.

Returns a structured report used by the quality scorer.
"""
import re
import pandas as pd
from typing import Dict, List


# ── PII patterns ──────────────────────────────────────────────────────────────

PII_PATTERNS: Dict[str, re.Pattern] = {
    "email": re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.IGNORECASE
    ),
    "phone_fr": re.compile(
        r"(?:(?:\+|00)33|0)\s*[1-9](?:[\s.\-]?\d{2}){4}"
    ),
    "phone_intl": re.compile(
        r"\+?\d[\d\s\-().]{7,}\d"
    ),
    "iban": re.compile(
        r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b"
    ),
    "french_ssn": re.compile(
        r"\b[12]\s?\d{2}\s?\d{2}\s?\d{2,3}\s?\d{3}\s?\d{3}\s?\d{2}\b"
    ),
    "ip_address": re.compile(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    ),
    "credit_card": re.compile(
        r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b"
    ),
    "passport": re.compile(
        r"\b[A-Z]{1,2}\d{6,9}\b"
    ),
    "date_of_birth": re.compile(
        r"\b(?:0[1-9]|[12]\d|3[01])[\/\-.](?:0[1-9]|1[0-2])[\/\-.](?:19|20)\d{2}\b"
    ),
}

# Column names that strongly suggest PII regardless of content
PII_COLUMN_KEYWORDS = {
    "high": [
        "ssn", "social_security", "nss", "passport", "national_id",
        "carte_identite", "credit_card", "card_number", "iban", "bic",
        "password", "mot_de_passe", "secret", "token",
    ],
    "medium": [
        "email", "mail", "phone", "tel", "mobile", "fax",
        "address", "adresse", "street", "rue", "zip", "postal",
        "ip", "ip_address", "device_id", "mac_address",
        "first_name", "last_name", "prenom", "nom", "full_name",
        "date_of_birth", "dob", "birth", "naissance", "age",
        "salary", "salaire", "income", "revenue",
        "health", "medical", "diagnosis", "condition", "disease",
        "religion", "political", "sexuality", "ethnic",
    ],
}


# ── Main scanner ──────────────────────────────────────────────────────────────

def scan_for_pii(df: pd.DataFrame, sample_size: int = 500) -> dict:
    """
    Scan a DataFrame for PII. Samples rows to keep it fast.

    Returns:
        {
          "pii_detected": bool,
          "risk_level": "none" | "low" | "medium" | "high",
          "flagged_columns": [ { "column", "risk_level", "pii_types", "match_count" } ],
          "summary": "..."
        }
    """
    sample = df.head(sample_size)
    flagged_columns = []
    overall_risk = "none"

    for col in sample.columns:
        col_lower = col.lower().replace(" ", "_")
        col_flags = _check_column(sample[col], col_lower)
        if col_flags:
            flagged_columns.append({"column": col, **col_flags})
            # Escalate overall risk
            if col_flags["risk_level"] == "high":
                overall_risk = "high"
            elif col_flags["risk_level"] == "medium" and overall_risk != "high":
                overall_risk = "medium"
            elif col_flags["risk_level"] == "low" and overall_risk == "none":
                overall_risk = "low"

    pii_detected = len(flagged_columns) > 0

    summary_parts = []
    if not pii_detected:
        summary_parts.append("No PII patterns detected.")
    else:
        types = set()
        for fc in flagged_columns:
            types.update(fc.get("pii_types", []))
        summary_parts.append(
            f"Potential PII found in {len(flagged_columns)} column(s): "
            f"{', '.join(sorted(types))}."
        )
        if overall_risk == "high":
            summary_parts.append(
                "HIGH RISK: Dataset likely contains directly identifying information. "
                "GDPR compliance review strongly recommended before publishing."
            )
        elif overall_risk == "medium":
            summary_parts.append(
                "MEDIUM RISK: Dataset may contain quasi-identifying information. "
                "Consider anonymization or pseudonymization."
            )

    return {
        "pii_detected": pii_detected,
        "risk_level": overall_risk,
        "flagged_columns": flagged_columns,
        "summary": " ".join(summary_parts),
    }


# ── Per-column check ──────────────────────────────────────────────────────────

def _check_column(series: pd.Series, col_lower: str) -> dict | None:
    pii_types = []
    risk_level = "none"
    match_count = 0

    # 1. Column name heuristics (fast, no content scan needed)
    for keyword in PII_COLUMN_KEYWORDS["high"]:
        if keyword in col_lower:
            pii_types.append(f"column_name:{keyword}")
            risk_level = "high"

    for keyword in PII_COLUMN_KEYWORDS["medium"]:
        if keyword in col_lower and risk_level != "high":
            pii_types.append(f"column_name:{keyword}")
            risk_level = "medium"

    # 2. Content pattern scan (only on string columns)
    if series.dtype == object:
        str_values = series.dropna().astype(str)
        combined = " ".join(str_values.head(200).tolist())

        for pii_type, pattern in PII_PATTERNS.items():
            matches = pattern.findall(combined)
            if matches:
                pii_types.append(pii_type)
                match_count += len(matches)
                if pii_type in ("email", "french_ssn", "credit_card", "iban", "passport"):
                    risk_level = "high"
                elif risk_level != "high":
                    risk_level = "medium"

    if not pii_types:
        return None

    return {
        "risk_level": risk_level,
        "pii_types": list(set(pii_types)),
        "match_count": match_count,
    }
