"""
Datia chatbot routes (spec §14).

  POST /chat                      — ask Datia; pass dataset_id when on a dataset page
  POST /chat/stream               — same, streamed as server-sent events
  POST /chat/request-draft        — turn the conversation into a request-board draft
  GET  /datasets/{id}/questions   — seller: what buyers asked about this dataset
"""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user, get_current_active_seller
from app.schemas.chat import ChatRequest, ChatResponse, ChatHistory, RequestDraft, DatasetQuestions
from app.services import chat_service

router = APIRouter(tags=["Chatbot"])


def _args(body: ChatRequest) -> tuple:
    history = [t.model_dump() for t in body.history]
    return body.message, history, str(body.dataset_id) if body.dataset_id else None


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return chat_service.ask(db, user, *_args(body))


@router.post("/chat/stream")
def chat_stream(
    body: ChatRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    events = chat_service.ask_stream(db, user, *_args(body))
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/request-draft", response_model=RequestDraft)
def chat_request_draft(
    body: ChatHistory,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return chat_service.draft_request(db, user, [t.model_dump() for t in body.history])


@router.get("/datasets/{dataset_id}/questions", response_model=DatasetQuestions)
def dataset_questions(
    dataset_id: str,
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    return chat_service.dataset_questions(db, seller, dataset_id)
