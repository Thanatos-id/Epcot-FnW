import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from epcot_fw.api.deps import get_db
from epcot_fw.api.schemas import ConcertEventOut
from epcot_fw.db.models import ConcertEvent

router = APIRouter(tags=["events"])


@router.get("/festivals/{festival_id}/events", response_model=list[ConcertEventOut])
def list_events(
    festival_id: int,
    artist: str | None = None,
    date: datetime.date | None = None,
    db: Session = Depends(get_db),
):
    stmt = (
        select(ConcertEvent)
        .where(ConcertEvent.festival_id == festival_id)
        .options(selectinload(ConcertEvent.showtimes))
    )
    if artist:
        stmt = stmt.where(ConcertEvent.artist_name.ilike(f"%{artist}%"))
    if date:
        stmt = stmt.where(ConcertEvent.performance_date == date)
    return db.scalars(stmt.order_by(ConcertEvent.performance_date)).all()


@router.get("/events/{event_id}", response_model=ConcertEventOut)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.scalars(
        select(ConcertEvent)
        .where(ConcertEvent.id == event_id)
        .options(selectinload(ConcertEvent.showtimes))
    ).first()
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    return event
