"""
Datia chatbot routes (spec §14).

  POST /chat                 — ask Datia; pass dataset_id when on a dataset page
  POST /datasets/{id}/chat   — same, scoped to one dataset (kept for older clients)
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat_service

router = APIRouter(tags=["Chatbot"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    history = [t.model_dump() for t in body.history]
    dataset_id = str(body.dataset_id) if body.dataset_id else None
    return chat_service.ask(db, user, body.message, history, dataset_id)


@router.post("/datasets/{dataset_id}/chat", response_model=ChatResponse)
def chat_with_dataset(
    dataset_id: UUID,
    body: ChatRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    history = [t.model_dump() for t in body.history]
    return chat_service.ask(db, user, body.message, history, str(dataset_id))
