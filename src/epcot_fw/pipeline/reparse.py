"""Reparse already-cached raw pages with today's parser, without refetching.

fetch/cache.py skips reparsing a page whose visible-text content hasn't
changed since the last fetch (see cache.record_fetch) - the right call for a
normal crawl/refresh, since a source's markup rarely moves and reparsing
thousands of untouched pages every run would be wasted work. But it has a
blind spot: when the *parser* changes - af2d195 and 869f8f9 taught the Disney
Food Blog adapter to stop leaving a dish's price and description glued onto
its name - a page whose HTML hasn't moved keeps its old, pre-fix
extracted_records forever, because nothing ever asks it to be reparsed. A
weekly `epcot-fw refresh` against an unchanged page does nothing to fix
already-stored data; only a genuine site content change would, and DFB's
2026 hub can sit unchanged for weeks at a time.

This walks every source's latest (non-superseded) raw_pages - the HTML is
already sitting in raw_pages.raw_html from whenever it was last fetched - and
runs each one through the adapter's current parse() again. The result is
matched back to the *same* canonical entities the page's prior extraction
already resolved to, positionally within the page (see _reparse_page): a
detail page that used to yield 12 menu_item DTOs and still yields 12 today is
assumed to be the same 12 dishes, just parsed more correctly - a safe
assumption for a reparse of unchanged content, though not one a fresh crawl
of genuinely *changed* content could make. A page's dish count changing
falls back to the ordinary fuzzy-match path via run_resolve(), the same as
any newly-discovered record would take.

No network access, no robots.txt, no crawl-delay: there is nothing to fetch.
"""

import datetime
import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import CanonicalLink, ExtractedRecord, RawPage, Source
from epcot_fw.pipeline.crawl import EXTRACTOR_VERSION, _current_festival, _enabled_sources
from epcot_fw.pipeline.manual import stage_manual_overrides
from epcot_fw.pipeline.reconcile import run_reconciliation
from epcot_fw.pipeline.resolve_pipeline import run_resolve
from epcot_fw.resolve.merge import apply_match_outcome
from epcot_fw.sources.registry import SOURCE_REGISTRY

logger = logging.getLogger(__name__)

PAGE_STATS = {"records_extracted": 0, "records_relinked": 0, "errors": 0}


def _reparse_page(session: Session, source: Source, page: RawPage, *, festival_id: int) -> dict:
    """Reparse one cached page, reusing each new record's canonical link from
    the record it lines up with positionally (same entity_type, page order)
    among what this exact page already resolved to."""
    adapter = SOURCE_REGISTRY[source.key]
    stats = dict(PAGE_STATS)

    try:
        dtos = adapter.parse(page.raw_html, page.url, page.page_kind)
    except Exception:
        logger.exception("reparse failed for %s (%s)", page.url, source.key)
        stats["errors"] += 1
        return stats

    old_records = session.scalars(
        select(ExtractedRecord)
        .where(ExtractedRecord.raw_page_id == page.id)
        .order_by(ExtractedRecord.id)
    ).all()
    old_links: dict[int, CanonicalLink] = (
        {
            link.extracted_record_id: link
            for link in session.scalars(
                select(CanonicalLink).where(
                    CanonicalLink.extracted_record_id.in_([r.id for r in old_records])
                )
            ).all()
        }
        if old_records
        else {}
    )

    old_by_type: dict[str, list[ExtractedRecord]] = defaultdict(list)
    for r in old_records:
        old_by_type[r.entity_type].append(r)

    dto_by_type: dict[str, list] = defaultdict(list)
    for dto in dtos:
        dto_by_type[dto.entity_type].append(dto)

    now = datetime.datetime.now(datetime.UTC)
    for entity_type, dto_list in dto_by_type.items():
        old_list = old_by_type.get(entity_type, [])
        for i, dto in enumerate(dto_list):
            new_record = ExtractedRecord(
                raw_page_id=page.id,
                source_id=source.id,
                entity_type=entity_type,
                extracted_at=now,
                extractor_version=EXTRACTOR_VERSION,
                payload=dto.payload,
                natural_key_hint=dto.natural_key_hint,
            )
            session.add(new_record)
            session.flush()
            stats["records_extracted"] += 1

            old_link = old_links.get(old_list[i].id) if i < len(old_list) else None
            if old_link is not None:
                apply_match_outcome(
                    session,
                    new_record,
                    source,
                    entity_type=entity_type,
                    outcome="auto_merge",
                    canonical_id=old_link.canonical_id,
                    booth_id=None,
                    match_score=old_link.match_confidence,
                    match_method="reparse",
                    festival_id=festival_id,
                )
                stats["records_relinked"] += 1
            # else: no prior record at this position (a genuinely new item,
            # or the page is being reparsed for the first time) - left
            # unlinked, so run_resolve() below matches it the normal,
            # fresh-fuzzy-match way.

    return stats


def run_reparse(session: Session, *, source_keys: list[str] | None = None) -> dict:
    """Reparse every enabled source's already-cached pages with today's
    parser code and re-resolve - a recovery tool for when a parser bug is
    fixed after content was already crawled, so the fix needs no live
    refetch to take effect. See the module docstring for how a reparsed
    record reconnects to the entity it already resolved to."""
    festival = _current_festival(session)
    sources = _enabled_sources(session, source_keys)
    if not sources:
        raise RuntimeError(
            "No sources are enabled. Use `epcot-fw sources enable <key>` for each source you want reparsed."
        )

    totals = {"pages_reparsed": 0, "records_extracted": 0, "records_relinked": 0, "errors": 0}
    for source in sources:
        if source.key not in SOURCE_REGISTRY:
            continue
        pages = session.scalars(
            select(RawPage).where(
                RawPage.source_id == source.id,
                RawPage.superseded_by_id.is_(None),
                RawPage.raw_html.isnot(None),
            )
        ).all()
        for page in pages:
            stats = _reparse_page(session, source, page, festival_id=festival.id)
            totals["pages_reparsed"] += 1
            for key in ("records_extracted", "records_relinked", "errors"):
                totals[key] += stats[key]
        session.commit()

    totals["manual_overrides"] = stage_manual_overrides(session)
    resolve_stats = run_resolve(session, festival_id=festival.id)
    totals.update(resolve_stats)
    totals.update(run_reconciliation(session, festival_id=festival.id).as_dict())
    session.commit()

    return totals
