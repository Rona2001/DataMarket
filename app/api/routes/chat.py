"""
Dataset Chatbot route (spec §14) — Premium, pre-purchase discovery.

  POST /datasets/{id}/chat   — ask the dataset a question (Premium + rate-limited)
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat_service

router = APIRouter(tags=["Chatbot"])


@router.post("/datasets/{dataset_id}/chat", response_model=ChatResponse)
def chat_with_dataset(
    dataset_id: str,
    body: ChatRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    history = [t.model_dump() for t in body.history]
    return chat_service.ask(db, user, dataset_id, body.message, history)
