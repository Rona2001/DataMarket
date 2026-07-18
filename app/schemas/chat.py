from pydantic import BaseModel, field_validator
from typing import List, Literal


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatTurn] = []

    @field_validator("message")
    @classmethod
    def non_empty(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Message cannot be empty")
        return v[:2000]


class ChatResponse(BaseModel):
    answer: str
    disclaimer: str
