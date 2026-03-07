"""
File processing utilities:
- Extension & MIME type validation
- SHA-256 checksum
- Auto-generate row/column stats
- Extract a sample preview (first N rows)
"""
import hashlib
import io
from typing import Optional
import pandas as pd

from app.core.config import settings
from app.models.dataset import DataFormat


MIME_MAP = {
    "text/csv": DataFormat.CSV,
    "application/json": DataFormat.JSON,
    "application/vnd.ms-excel": DataFormat.EXCEL,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": DataFormat.EXCEL,
    "application/octet-stream": DataFormat.PARQUET,  # parquet has no standard MIME
    "application/zip": DataFormat.ZIP,
    "application/x-zip-compressed": DataFormat.ZIP,
}

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

        columns.append(col_info)

    return {
        "num_rows": len(df),
        "num_columns": len(df.columns),
        "columns": columns,
        "memory_usage_bytes": int(df.memory_usage(deep=True).sum()),
    }


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
