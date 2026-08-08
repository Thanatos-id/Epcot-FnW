from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import CanonicalLink, ExtractedRecord, MergeConflict, Source
from epcot_fw.resolve.merge import resolve_extracted_record
from epcot_fw.resolve.reviews import attach_review

# Parents must be resolved before children reference them (menu_item needs its
# booth to already exist as a canonical row; reviews are matched against
# booth names, so booths must exist first too - handled by running the
# review pass after this loop, not inside ENTITY_TYPE_ORDER).
ENTITY_TYPE_ORDER = ("festival", "booth", "menu_item", "event", "seminar")


def run_resolve(session: Session, *, festival_id: int) -> dict:
    """Idempotently match+merge every staged extracted_record into the
    canonical layer. Safe to call repeatedly - resolve_extracted_record()
    short-circuits records that already have a canonical_links row."""
    canonical_upserts = 0
    sources_cache: dict[int, Source] = {}

    for entity_type in ENTITY_TYPE_ORDER:
        records = session.scalars(
            select(ExtractedRecord)
            .where(ExtractedRecord.entity_type == entity_type)
            .order_by(ExtractedRecord.id)
        ).all()

        for record in records:
            already_linked = session.scalars(
                select(CanonicalLink).where(CanonicalLink.extracted_record_id == record.id)
            ).first()
            if already_linked is not None:
                continue

            source = sources_cache.get(record.source_id)
            if source is None:
                source = session.get(Source, record.source_id)
                sources_cache[record.source_id] = source

            resolve_extracted_record(session, record, source, festival_id=festival_id)

            newly_linked = session.scalars(
                select(CanonicalLink).where(CanonicalLink.extracted_record_id == record.id)
            ).first()
            if newly_linked is not None:
                canonical_upserts += 1

        session.flush()

    reviews_matched = 0
    review_records = session.scalars(
        select(ExtractedRecord).where(ExtractedRecord.entity_type == "review").order_by(ExtractedRecord.id)
    ).all()
    for record in review_records:
        source = sources_cache.get(record.source_id)
        if source is None:
            source = session.get(Source, record.source_id)
            sources_cache[record.source_id] = source
        reviews_matched += attach_review(session, record, source, festival_id=festival_id)
    session.flush()

    open_conflict_count = len(
        session.scalars(select(MergeConflict).where(MergeConflict.status == "open")).all()
    )

    return {
        "canonical_upserts": canonical_upserts,
        "open_conflicts": open_conflict_count,
        "reviews_matched": reviews_matched,
    }
