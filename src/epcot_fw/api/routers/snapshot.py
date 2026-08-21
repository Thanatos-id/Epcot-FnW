"""One-request bundle of everything a client needs, for offline use.

A phone in World Showcase has poor signal, and the whole festival is small -
tens of booths, a couple of hundred dishes. Rather than have a client stitch
together a dozen paginated calls while walking, this returns the lot in one
response and lets it cache aggressively.

The payload is content-addressed with a strong ETag. Data changes on the
weekly refresh, so a client that re-checks on launch gets a 304 and near-zero
bytes almost every time.
"""

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from epcot_fw.api.deps import get_db
from epcot_fw.api.schemas import (
    BoothOut,
    ConcertEventOut,
    FestivalOut,
    MenuItemOut,
    SeminarOut,
    SnapshotOut,
)
from epcot_fw.db.models import Booth, ConcertEvent, Festival, MenuItem, Seminar

router = APIRouter(tags=["snapshot"])

# The dataset is small and changes weekly. A short max-age keeps a launch
# feeling live, while must-revalidate means the client still asks - and
# almost always gets a cheap 304.
CACHE_CONTROL = "public, max-age=300, must-revalidate"


def _etag(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return '"' + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32] + '"'


def build_snapshot(db: Session, festival: Festival) -> dict:
    # Retired entities are excluded: this payload is what a client shows a
    # guest standing in the park, and a booth that stopped running would
    # send them somewhere that isn't there. See pipeline/reconcile.py.
    booths = db.scalars(
        select(Booth)
        .where(Booth.festival_id == festival.id, Booth.is_active.is_(True))
        .order_by(Booth.canonical_name)
    ).all()
    booth_ids = [b.id for b in booths]
    booth_out = [BoothOut.model_validate(b) for b in booths]

    items = (
        db.scalars(
            select(MenuItem)
            .where(MenuItem.booth_id.in_(booth_ids), MenuItem.is_active.is_(True))
            .options(selectinload(MenuItem.dietary_tags))
            .order_by(MenuItem.canonical_name)
        ).all()
        if booth_ids
        else []
    )

    events = db.scalars(
        select(ConcertEvent)
        .where(ConcertEvent.festival_id == festival.id)
        .options(selectinload(ConcertEvent.showtimes))
        .order_by(ConcertEvent.performance_date)
    ).all()

    seminars = db.scalars(
        select(Seminar).where(Seminar.festival_id == festival.id).order_by(Seminar.event_date)
    ).all()

    return SnapshotOut(
        festival=FestivalOut.model_validate(festival),
        booths=booth_out,
        menu_items=[MenuItemOut.model_validate(i) for i in items],
        events=[ConcertEventOut.model_validate(e) for e in events],
        seminars=[SeminarOut.model_validate(s) for s in seminars],
    ).model_dump(mode="json")


@router.get("/snapshot", response_model=SnapshotOut)
def get_snapshot(
    request: Request,
    response: Response,
    festival_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Everything for one festival in a single cacheable response.

    Defaults to the newest festival so a client needs no prior knowledge to
    make its first call.
    """
    stmt = select(Festival)
    stmt = (
        stmt.where(Festival.id == festival_id)
        if festival_id
        else stmt.order_by(Festival.year.desc())
    )
    festival = db.scalars(stmt).first()
    if festival is None:
        raise HTTPException(status_code=404, detail="festival not found")

    payload = build_snapshot(db, festival)
    etag = _etag(payload)

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = CACHE_CONTROL

    # A 304 must carry the validators but no body, so return early rather
    # than serialising the payload the client already has.
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": CACHE_CONTROL})

    return payload
