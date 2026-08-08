from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.api.deps import get_db
from epcot_fw.api.schemas import FestivalOut
from epcot_fw.db.models import Festival

router = APIRouter(prefix="/festivals", tags=["festivals"])


@router.get("", response_model=list[FestivalOut])
def list_festivals(db: Session = Depends(get_db)):
    return db.scalars(select(Festival).order_by(Festival.year.desc())).all()


@router.get("/{festival_id}", response_model=FestivalOut)
def get_festival(festival_id: int, db: Session = Depends(get_db)):
    festival = db.get(Festival, festival_id)
    if festival is None:
        raise HTTPException(status_code=404, detail="festival not found")
    return festival
