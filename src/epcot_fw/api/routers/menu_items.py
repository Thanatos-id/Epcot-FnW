from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from epcot_fw.api.deps import get_db
from epcot_fw.api.schemas import ListResponse, MenuItemOut, Meta
from epcot_fw.db.models import Booth, DietaryTag, MenuItem

router = APIRouter(tags=["menu_items"])


@router.get("/festivals/{festival_id}/menu-items", response_model=ListResponse[MenuItemOut])
def list_menu_items(
    festival_id: int,
    dietary_tag: str | None = None,
    category: str | None = None,
    booth_id: int | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    stmt = (
        select(MenuItem)
        .join(Booth, MenuItem.booth_id == Booth.id)
        .where(Booth.festival_id == festival_id)
        .options(selectinload(MenuItem.dietary_tags))
    )
    if category:
        stmt = stmt.where(MenuItem.category == category)
    if booth_id:
        stmt = stmt.where(MenuItem.booth_id == booth_id)
    if min_price is not None:
        stmt = stmt.where(MenuItem.price_usd >= min_price)
    if max_price is not None:
        stmt = stmt.where(MenuItem.price_usd <= max_price)
    if dietary_tag:
        stmt = stmt.join(MenuItem.dietary_tags).where(DietaryTag.code == dietary_tag)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(MenuItem.canonical_name).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ListResponse(data=rows, meta=Meta(total=total or 0, page=page, page_size=page_size))


@router.get("/menu-items/{menu_item_id}", response_model=MenuItemOut)
def get_menu_item(menu_item_id: int, db: Session = Depends(get_db)):
    item = db.scalars(
        select(MenuItem)
        .where(MenuItem.id == menu_item_id)
        .options(selectinload(MenuItem.dietary_tags))
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="menu item not found")
    return item


@router.get("/dietary-tags")
def list_dietary_tags(db: Session = Depends(get_db)):
    rows = db.scalars(select(DietaryTag).order_by(DietaryTag.code)).all()
    return [{"code": r.code, "label": r.label} for r in rows]
