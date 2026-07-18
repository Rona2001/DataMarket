from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class FollowInput(BaseModel):
    category: str


class FollowPublic(BaseModel):
    id: UUID
    category: str
    created_at: datetime

    class Config:
        from_attributes = True
