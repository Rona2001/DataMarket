"""
Dataset Chatbot service (spec §14).

Pre-purchase discovery: a buyer can 'talk to' a dataset before buying. The bot
answers ONLY from verification artefacts (schema, profiling stats, sample values,
metadata) — it never sees the full dataset (an RGPD and an anti-leakage
guarantee). Gated behind Premium; rate-limited per user.
"""
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core import llm
from app.models.dataset import Dataset, DatasetStatus
from app.models.chat import ChatLog
from app.models.user import User


SYSTEM_RULES = (
    "You are the datrust dataset assistant. You help a prospective buyer decide whether a "
    "dataset fits their needs, BEFORE they purchase. Answer ONLY from the dataset context "
    "provided below — schema, column types, null rates, sample values, and metadata. You do "
    "NOT have access to the full dataset. If a question can't be answered from this context, "
    "say so plainly and suggest the buyer post on the request board. Never invent columns, "
    "values, or statistics. Keep answers concise and factual. Always remind the buyer, when "
    "relevant, that your answer is based on the sample and metadata only."
)


def _build_context(dataset: Dataset) -> str:
    """Assemble the per-dataset context from verification artefacts already in the DB."""
    lines = [
        f"Title: {dataset.title}",
        f"Category: {dataset.category or '—'}",
        f"Description: {dataset.description}",
        f"Format: {dataset.data_format.value if dataset.data_format else '—'}",
        f"Rows: {dataset.num_rows if dataset.num_rows is not None else 'unknown'}",
        f"Columns: {dataset.num_columns if dataset.num_columns is not None else 'unknown'}",
        f"Quality score: {dataset.quality_score if dataset.quality_score is not None else 'not verified'}/100",
        f"PII risk level: {dataset.pii_risk_level or 'unknown'}",
        f"Licence: {dataset.license_type or '—'}",
        f"Price: {'Free' if dataset.price == 0 else f'€{dataset.price}'}",
    ]

    schema = dataset.schema_info if isinstance(dataset.schema_info, dict) else {}
    columns = schema.get("columns") if isinstance(schema, dict) else None
    if columns:
        lines.append("\nColumns (name · type · null% · sample values):")
        for col in columns[:60]:
            name = col.get("name")
            dtype = col.get("dtype")
            null_pct = col.get("null_pct")
            samples = ", ".join(str(s) for s in (col.get("sample_values") or [])[:3])
            lines.append(f"  - {name} · {dtype} · {null_pct}% null · e.g. {samples}")

    return "\n".join(lines)


def _check_access(db: Session, user: User) -> None:
    if not user.is_premium:
        raise HTTPException(
            status_code=402,
            detail="The dataset assistant is a Premium feature. Upgrade to ask datasets questions before you buy.",
        )
    window = datetime.utcnow() - timedelta(hours=1)
    recent = (
        db.query(ChatLog)
        .filter(ChatLog.user_id == user.id, ChatLog.created_at >= window)
        .count()
    )
    if recent >= settings.CHAT_RATE_LIMIT_PER_HOUR:
        raise HTTPException(status_code=429, detail="You've reached the hourly message limit. Please try again later.")


def ask(db: Session, user: User, dataset_id: str, message: str, history: list[dict]) -> dict:
    _check_access(db, user)

    dataset = (
        db.query(Dataset)
        .filter(Dataset.id == dataset_id, Dataset.status == DatasetStatus.PUBLISHED)
        .first()
    )
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    context = _build_context(dataset)
    system = f"{SYSTEM_RULES}\n\n--- DATASET CONTEXT ---\n{context}"

    # Keep only the last few turns to bound token cost; append the new question.
    turns = [
        {"role": m["role"], "content": m["content"]}
        for m in (history or [])[-6:]
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    turns.append({"role": "user", "content": message})

    answer = llm.chat_completion(system, turns)

    db.add(ChatLog(user_id=user.id, dataset_id=dataset.id))
    db.commit()

    return {
        "answer": answer,
        "disclaimer": "Based on the sample and metadata only — the assistant does not access the full dataset.",
    }
