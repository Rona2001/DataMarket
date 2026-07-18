"""
Favourites / saved datasets.

  GET    /favorites          — datasets the current user has favourited
  GET    /favorites/ids      — just the favourited dataset ids (for heart state)
  POST   /favorites/{id}     — add a dataset to favourites
  DELETE /favorites/{id}     — remove a dataset from favourites
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.favorite import Favorite
from app.models.dataset import Dataset
from app.schemas.dataset import DatasetPublic

router = APIRouter(tags=["Favourites"])


@router.get("/favorites", response_model=List[DatasetPublic])
def list_favorites(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(Dataset)
        .join(Favorite, Favorite.dataset_id == Dataset.id)
        .filter(Favorite.user_id == user.id)
        .order_by(Favorite.created_at.desc())
        .all()
    )


@router.get("/favorites/ids", response_model=List[str])
def list_favorite_ids(user=Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Favorite.dataset_id).filter(Favorite.user_id == user.id).all()
    return [str(r[0]) for r in rows]


@router.post("/favorites/{dataset_id}", status_code=201)
def add_favorite(dataset_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.query(Dataset).filter(Dataset.id == dataset_id).first():
        raise HTTPException(status_code=404, detail="Dataset not found")
    exists = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.dataset_id == dataset_id)
        .first()
    )
    if not exists:
        db.add(Favorite(user_id=user.id, dataset_id=dataset_id))
        db.commit()
    return {"favorited": True}


@router.delete("/favorites/{dataset_id}")
def remove_favorite(dataset_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Favorite).filter(
        Favorite.user_id == user.id, Favorite.dataset_id == dataset_id
    ).delete()
    db.commit()
    return {"favorited": False}
