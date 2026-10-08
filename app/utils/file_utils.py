"""
File processing utilities:
- Extension & MIME type validation
- SHA-256 checksum
- Auto-generate row/column stats
- Extract a sample preview (first N rows)
"""
import hashlib
import io
import json
from typing import Optional
import pandas as pd

from app.core.config import settings
from app.models.dataset import DataFormat


EXTENSION_MAP = {
    "csv": DataFormat.CSV,
    "json": DataFormat.JSON,
    "parquet": DataFormat.PARQUET,
    "xlsx": DataFormat.EXCEL,
    "xls": DataFormat.EXCEL,
    "zip": DataFormat.ZIP,
}


# ── Validation ────────────────────────────────────────────────────────────────

def validate_extension(filename: str) -> DataFormat:
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise ValueError(
            f"File type '.{ext}' is not allowed. "
            f"Accepted: {', '.join(settings.ALLOWED_EXTENSIONS)}"
        )
    return EXTENSION_MAP.get(ext, DataFormat.OTHER)


def validate_size(size_bytes: int) -> None:
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if size_bytes > max_bytes:
        raise ValueError(
            f"File too large ({size_bytes / 1024 / 1024:.1f} MB). "
            f"Maximum allowed: {settings.MAX_UPLOAD_SIZE_MB} MB."
        )


# ── Checksum ──────────────────────────────────────────────────────────────────

def compute_checksum(data: bytes) -> str:
    """SHA-256 hash of file contents. Used to verify integrity after download."""
    return hashlib.sha256(data).hexdigest()


# ── DataFrame loading ─────────────────────────────────────────────────────────

def load_dataframe(data: bytes, data_format: DataFormat) -> Optional[pd.DataFrame]:
    """
    Try to load uploaded bytes into a DataFrame for analysis.
    Returns None for ZIP files (can't introspect directly).
    """
    try:
        buf = io.BytesIO(data)
        if data_format == DataFormat.CSV:
            return pd.read_csv(buf)
        elif data_format == DataFormat.JSON:
            return pd.read_json(buf)
        elif data_format == DataFormat.PARQUET:
            return pd.read_parquet(buf)
        elif data_format == DataFormat.EXCEL:
            return pd.read_excel(buf)
    except Exception:
        pass
    return None


# ── Stats extraction ──────────────────────────────────────────────────────────

def _num(value):
    """JSON-safe number: plain int/float, 4 significant decimals, None for NaN/inf."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return int(value) if value.is_integer() else round(value, 4)


def _date_range(series: pd.Series) -> tuple[str, str] | None:
    """(min, max) ISO dates if the column holds dates, else None."""
    values = series.dropna()
    if values.empty:
        return None
    if not pd.api.types.is_datetime64_any_dtype(values):
        if values.dtype != object:
            return None
        probe = values.head(200).astype(str)
        # Cheap pre-filter: real dates carry a separator; plain numbers and words don't.
        if not probe.str.contains(r"\d[-/:.]\d", regex=True).mean() >= 0.9:
            return None
        if pd.to_datetime(probe, errors="coerce").notna().mean() < 0.9:
            return None
        values = pd.to_datetime(values.astype(str), errors="coerce").dropna()
        if values.empty:
            return None
    return values.min().date().isoformat(), values.max().date().isoformat()


def _column_profile(series: pd.Series) -> dict:
    """
    Per-column profile beyond type and null rate: distinct count, numeric range,
    date range, and the most frequent values of category-like columns. This is
    what lets a buyer (and the Datia assistant) judge coverage before buying.
    """
    profile: dict = {}
    non_null = series.dropna()
    if non_null.empty:
        return profile

    try:
        distinct = int(non_null.nunique())
    except TypeError:          # unhashable cells (lists, dicts)
        return profile
    profile["distinct_count"] = distinct

    if pd.api.types.is_bool_dtype(series):
        pass
    elif pd.api.types.is_numeric_dtype(series):
        profile["min"] = _num(non_null.min())
        profile["max"] = _num(non_null.max())
        profile["mean"] = _num(non_null.mean())
        profile["median"] = _num(non_null.median())
    else:
        dates = _date_range(series)
        if dates:
            profile["date_min"], profile["date_max"] = dates

    # Category-like columns only: listing top values of a free-text or id column
    # would just republish rows of the dataset.
    if "date_min" not in profile and distinct <= 50 and distinct <= max(1, len(non_null) // 2):
        counts = non_null.astype(str).value_counts().head(5)
        profile["top_values"] = [
            {"value": str(value)[:60], "pct": round(count / len(non_null) * 100, 1)}
            for value, count in counts.items()
        ]
    return profile


def extract_stats(df: pd.DataFrame) -> dict:
    """
    Extract lightweight metadata from the DataFrame.
    This is stored in the DB as schema_info and shown on the listing.
    """
    columns = []
    for col in df.columns:
        col_info = {
            "name": col,
            "dtype": str(df[col].dtype),
            "null_count": int(df[col].isnull().sum()),
            "null_pct": round(df[col].isnull().mean() * 100, 2),
        }
        # Add sample values for non-sensitive previews (max 3 unique values)
        try:
            samples = df[col].dropna().unique()[:3].tolist()
            col_info["sample_values"] = [str(s) for s in samples]
        except Exception:
            col_info["sample_values"] = []

        try:
            col_info.update(_column_profile(df[col]))
        except Exception:
            pass  # profiling is best effort, never blocks an upload

        columns.append(col_info)

    return {
        "num_rows": len(df),
        "num_columns": len(df.columns),
        "columns": columns,
        "duplicate_rows": _duplicate_rows(df),
        "memory_usage_bytes": int(df.memory_usage(deep=True).sum()),
    }


def _duplicate_rows(df: pd.DataFrame) -> int | None:
    try:
        return int(df.duplicated().sum())
    except TypeError:
        return None


# ── Sample generation ─────────────────────────────────────────────────────────

def generate_sample(df: pd.DataFrame, n_rows: int = None) -> bytes:
    """
    Create a CSV sample with the first N rows.
    This is stored in the PUBLIC bucket for free preview.
    """
    n = n_rows or settings.SAMPLE_ROWS
    sample_df = df.head(n)
    buf = io.BytesIO()
    sample_df.to_csv(buf, index=False)
    return buf.getvalue()


# ── Structured preview (spec §6 — in-browser sample-first checkout) ─────────────

PREVIEW_ROWS = 10   # deliberately truncated so the preview has no standalone value


def generate_preview(df: pd.DataFrame, n_rows: int = PREVIEW_ROWS) -> dict:
    """
    Build the structured, JSON-serializable preview shown before checkout:
    column names + types + null rates, plus the first N rows.

    Deliberately truncated (fewer rows than the CSV sample) so it carries no
    standalone value. Uses pandas' JSON serializer to safely coerce NaN → null
    and numpy types → JSON natives.
    """
    head = df.head(n_rows)
    columns = [
        {
            "name": str(col),
            "dtype": str(df[col].dtype),
            "null_pct": round(float(df[col].isnull().mean()) * 100, 2),
        }
        for col in df.columns
    ]
    rows = json.loads(head.to_json(orient="records", date_format="iso"))
    return {
        "columns": columns,
        "rows": rows,
        "num_rows": int(len(df)),
        "num_columns": int(len(df.columns)),
        "preview_rows": int(len(head)),
        "truncated": bool(len(df) > len(head)),
    }
