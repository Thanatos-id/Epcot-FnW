from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.api.deps import get_db
from epcot_fw.db.models import Booth, ConcertEvent, MenuItem, Seminar

router = APIRouter(tags=["search"])

ALL_TYPES = ("booth", "menu_item", "event", "seminar")


@router.get("/search")
def search(
    q: str = Query(..., min_length=1),
    festival_id: int | None = None,
    types: str | None = Query(None, description="Comma-separated: booth,menu_item,event,seminar"),
    db: Session = Depends(get_db),
):
    wanted = set(t.strip() for t in types.split(",")) if types else set(ALL_TYPES)
    like = f"%{q}%"
    results: dict[str, list[dict]] = {}

    if "booth" in wanted:
        stmt = select(Booth).where(Booth.canonical_name.ilike(like))
        if festival_id:
            stmt = stmt.where(Booth.festival_id == festival_id)
        results["booths"] = [
            {"id": b.id, "name": b.canonical_name, "category": b.category}
            for b in db.scalars(stmt.limit(25)).all()
        ]

    if "menu_item" in wanted:
        stmt = select(MenuItem).where(MenuItem.canonical_name.ilike(like))
        if festival_id:
            stmt = stmt.join(Booth, MenuItem.booth_id == Booth.id).where(Booth.festival_id == festival_id)
        results["menu_items"] = [
            {"id": m.id, "name": m.canonical_name, "booth_id": m.booth_id, "price_usd": m.price_usd}
            for m in db.scalars(stmt.limit(25)).all()
        ]

    if "event" in wanted:
        stmt = select(ConcertEvent).where(ConcertEvent.artist_name.ilike(like))
        if festival_id:
            stmt = stmt.where(ConcertEvent.festival_id == festival_id)
        results["events"] = [
            {"id": e.id, "artist_name": e.artist_name, "performance_date": e.performance_date}
            for e in db.scalars(stmt.limit(25)).all()
        ]

    if "seminar" in wanted:
        stmt = select(Seminar).where(Seminar.title.ilike(like))
        if festival_id:
            stmt = stmt.where(Seminar.festival_id == festival_id)
        results["seminars"] = [
            {"id": s.id, "title": s.title, "seminar_type": s.seminar_type}
            for s in db.scalars(stmt.limit(25)).all()
        ]

    return results
