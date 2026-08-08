import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.api.deps import get_db
from epcot_fw.api.schemas import SeminarOut
from epcot_fw.db.models import Seminar

router = APIRouter(tags=["seminars"])


@router.get("/festivals/{festival_id}/seminars", response_model=list[SeminarOut])
def list_seminars(
    festival_id: int,
    type: str | None = None,
    date: datetime.date | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Seminar).where(Seminar.festival_id == festival_id)
    if type:
        stmt = stmt.where(Seminar.seminar_type == type)
    if date:
        stmt = stmt.where(Seminar.event_date == date)
    return db.scalars(stmt.order_by(Seminar.event_date)).all()


@router.get("/seminars/{seminar_id}", response_model=SeminarOut)
def get_seminar(seminar_id: int, db: Session = Depends(get_db)):
    seminar = db.get(Seminar, seminar_id)
    if seminar is None:
        raise HTTPException(status_code=404, detail="seminar not found")
    return seminar
