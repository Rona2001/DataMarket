from pydantic import BaseModel, field_validator
from typing import List, Literal, Optional
from uuid import UUID
from datetime import datetime


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatTurn] = []
    # The dataset page the user is on, if any (sent by the frontend, never typed).
    dataset_id: Optional[UUID] = None

    @field_validator("message")
    @classmethod
    def non_empty(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Message cannot be empty")
        return v[:2000]


class ChatDatasetCard(BaseModel):
    id: str
    title: str
    category: Optional[str] = None
    data_format: Optional[str] = None
    num_rows: Optional[int] = None
    price: float = 0.0
    is_free: bool = False
    quality_score: Optional[float] = None


class ChatContextDataset(BaseModel):
    id: str
    title: str


class ChatResponse(BaseModel):
    answer: str
    disclaimer: str
    datasets: List[ChatDatasetCard] = []          # datasets Datia recommended in this answer
    context_dataset: Optional[ChatContextDataset] = None
    premium_required: bool = False                # column-level detail was withheld (free plan)


class ChatHistory(BaseModel):
    history: List[ChatTurn] = []


class RequestDraft(BaseModel):
    """A request-board survey pre-filled from a conversation; empty fields are left to the user."""
    domain: Optional[str] = None
    data_types: List[str] = []
    volume: Optional[str] = None
    intended_use: Optional[str] = None
    rgpd_constraint: Optional[str] = None
    budget_range: Optional[str] = None
    free_text: Optional[str] = None


class DatasetQuestion(BaseModel):
    question: str
    answered: bool
    created_at: datetime


class DatasetQuestions(BaseModel):
    dataset_id: str
    total: int
    unanswered_total: int
    questions: List[DatasetQuestion] = []
