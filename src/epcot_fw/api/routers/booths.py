import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from epcot_fw.api.deps import get_db
from epcot_fw.api.schemas import (
    BoothDetailOut,
    BoothOut,
    FieldProvenanceOut,
    ListResponse,
    Meta,
    ReviewCreate,
    ReviewOut,
)
from epcot_fw.db.models import Booth, EntityFieldProvenance, Review

router = APIRouter(tags=["booths"])


def _rating_aggregates(db: Session, booth_ids: list[int]) -> dict[int, tuple[float, int]]:
    """entity_id -> (average_rating, review_count) for the given booths."""
    if not booth_ids:
        return {}
    rows = db.execute(
        select(Review.entity_id, func.avg(Review.rating), func.count(Review.id))
        .where(Review.entity_type == "booth", Review.entity_id.in_(booth_ids))
        .group_by(Review.entity_id)
    ).all()
    return {entity_id: (float(avg), count) for entity_id, avg, count in rows}


def _apply_rating(booth_out: BoothOut, agg: dict[int, tuple[float, int]]) -> BoothOut:
    avg, count = agg.get(booth_out.id, (None, 0))
    booth_out.average_rating = round(avg, 2) if avg is not None else None
    booth_out.review_count = count
    return booth_out


@router.get("/festivals/{festival_id}/booths", response_model=ListResponse[BoothOut])
def list_booths(
    festival_id: int,
    category: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    stmt = select(Booth).where(Booth.festival_id == festival_id)
    if category:
        stmt = stmt.where(Booth.category == category)
    if search:
        stmt = stmt.where(Booth.canonical_name.ilike(f"%{search}%"))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(Booth.canonical_name).offset((page - 1) * page_size).limit(page_size)
    ).all()

    agg = _rating_aggregates(db, [b.id for b in rows])
    data = [_apply_rating(BoothOut.model_validate(b), agg) for b in rows]
    return ListResponse(data=data, meta=Meta(total=total or 0, page=page, page_size=page_size))


@router.get("/booths/{booth_id}", response_model=BoothDetailOut)
def get_booth(
    booth_id: int,
    include: str | None = Query(None, description="Comma-separated: menu_items,provenance"),
    db: Session = Depends(get_db),
):
    parts = set((include or "").split(",")) if include else set()
    stmt = select(Booth).where(Booth.id == booth_id)
    if "menu_items" in parts:
        stmt = stmt.options(selectinload(Booth.menu_items))
    booth = db.scalars(stmt).first()
    if booth is None:
        raise HTTPException(status_code=404, detail="booth not found")

    out = BoothDetailOut.model_validate(booth)
    if "menu_items" not in parts:
        out.menu_items = []
    _apply_rating(out, _rating_aggregates(db, [booth.id]))
    return out


@router.get("/booths/{booth_id}/reviews", response_model=list[ReviewOut])
def list_booth_reviews(booth_id: int, db: Session = Depends(get_db)):
    if db.get(Booth, booth_id) is None:
        raise HTTPException(status_code=404, detail="booth not found")
    rows = db.scalars(
        select(Review)
        .where(Review.entity_type == "booth", Review.entity_id == booth_id)
        .order_by(Review.reviewed_at.desc().nulls_last(), Review.id.desc())
    ).all()
    return [
        ReviewOut(
            id=r.id,
            reviewer_name=r.reviewer_name,
            rating=r.rating,
            rating_raw=r.rating_raw,
            recommended=r.recommended,
            review_text=r.review_text,
            review_url=r.review_url,
            reviewed_at=r.reviewed_at,
            match_method=r.match_method,
            is_user_submitted=r.source_id is None,
        )
        for r in rows
    ]


@router.post("/booths/{booth_id}/reviews", response_model=ReviewOut, status_code=201)
def create_booth_review(booth_id: int, payload: ReviewCreate, db: Session = Depends(get_db)):
    """Lets this app's own users leave a review, alongside the reviews mined
    from external sources. User reviews have source_id=NULL and no
    external_review_id - the reviews table's uniqueness constraint treats
    NULLs as distinct, so any number of user reviews can coexist here."""
    if db.get(Booth, booth_id) is None:
        raise HTTPException(status_code=404, detail="booth not found")
    if not (1 <= payload.rating <= 5):
        raise HTTPException(status_code=422, detail="rating must be between 1 and 5")

    review = Review(
        entity_type="booth",
        entity_id=booth_id,
        source_id=None,
        external_review_id=None,
        reviewer_name=payload.reviewer_name,
        rating=payload.rating,
        rating_raw=None,
        recommended=None,
        review_text=payload.review_text,
        review_url=None,
        reviewed_at=datetime.date.today(),
        match_method="user_submitted",
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    return ReviewOut(
        id=review.id,
        reviewer_name=review.reviewer_name,
        rating=review.rating,
        rating_raw=review.rating_raw,
        recommended=review.recommended,
        review_text=review.review_text,
        review_url=review.review_url,
        reviewed_at=review.reviewed_at,
        match_method=review.match_method,
        is_user_submitted=True,
    )


@router.get("/booths/{booth_id}/provenance", response_model=list[FieldProvenanceOut])
def get_booth_provenance(booth_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(EntityFieldProvenance).where(
            EntityFieldProvenance.entity_type == "booth",
            EntityFieldProvenance.canonical_id == booth_id,
        )
    ).all()
    return [
        FieldProvenanceOut(
            field_name=r.field_name,
            source_key=r.source.key,
            value=r.value,
            observed_at=r.observed_at,
            is_selected=r.is_selected,
        )
        for r in rows
    ]
