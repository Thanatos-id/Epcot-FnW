import datetime

from sqlalchemy import select

from epcot_fw.db.models import ExtractedRecord, RawPage, Source
from epcot_fw.resolve.merge import resolve_extracted_record


def ingest(session, dtos, source_key: str, festival_id: int, url: str = "https://example.test/fixture"):
    """Stage a source adapter's parsed DTOs as extracted_records (behind a
    fake raw_page) and run them through entity resolution, mirroring what
    pipeline/crawl.py does for a real fetch."""
    source = session.scalars(select(Source).where(Source.key == source_key)).one()
    now = datetime.datetime.now(datetime.UTC)

    raw_page = RawPage(
        source_id=source.id,
        url=url,
        page_kind="booth_list",
        fetched_at=now,
        http_status=200,
        content_hash=f"test-{source_key}-{url}",
        first_seen_at=now,
    )
    session.add(raw_page)
    session.flush()

    # Parents before children, same as pipeline/resolve_pipeline.py's ordering.
    for entity_type in ("festival", "booth", "menu_item", "event", "seminar"):
        for dto in dtos:
            if dto.entity_type != entity_type:
                continue
            record = ExtractedRecord(
                raw_page_id=raw_page.id,
                source_id=source.id,
                entity_type=dto.entity_type,
                extracted_at=now,
                extractor_version="test",
                payload=dto.payload,
                natural_key_hint=dto.natural_key_hint,
            )
            session.add(record)
            session.flush()
            resolve_extracted_record(session, record, source, festival_id=festival_id)

    session.flush()
