from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.api.deps import get_db
from epcot_fw.api.schemas import CrawlRunOut, SourceOut
from epcot_fw.db.models import CrawlRun, Source

router = APIRouter(tags=["meta"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/sources", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)):
    return db.scalars(select(Source).order_by(Source.priority_rank)).all()


@router.get("/meta/crawl-status", response_model=list[CrawlRunOut])
def crawl_status(limit: int = 10, db: Session = Depends(get_db)):
    stmt = select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(limit)
    return db.scalars(stmt).all()
