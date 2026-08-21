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
)
from epcot_fw.db.models import Booth, EntityFieldProvenance

router = APIRouter(tags=["booths"])


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

    data = [BoothOut.model_validate(b) for b in rows]
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
    return out


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
