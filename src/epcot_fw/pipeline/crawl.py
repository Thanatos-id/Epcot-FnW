import datetime
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import CrawlRun, ExtractedRecord, Festival, Source
from epcot_fw.fetch import cache, http_client
from epcot_fw.fetch.http_client import RobotsDisallowedError
from epcot_fw.pipeline.manual import stage_manual_overrides
from epcot_fw.pipeline.resolve_pipeline import run_resolve
from epcot_fw.sources.base import SeedUrl, SourceAdapter
from epcot_fw.sources.registry import SOURCE_REGISTRY

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "1"
EMPTY_STATS = {"pages_fetched": 0, "pages_changed": 0, "records_extracted": 0, "errors": 0}


def _current_festival(session: Session) -> Festival:
    festival = session.scalars(select(Festival).order_by(Festival.year.desc())).first()
    if festival is None:
        raise RuntimeError("No festival row found - run `epcot-fw db seed` first.")
    return festival


def _fetch_and_stage(
    session: Session, adapter: SourceAdapter, source: Source, seed: SeedUrl
) -> dict:
    stats = dict(EMPTY_STATS)
    prior = cache.latest_raw_page(session, seed.url)

    try:
        result = http_client.fetch(
            seed.url,
            crawl_delay_sec=float(source.crawl_delay_sec),
            etag=prior.etag if prior else None,
            last_modified=prior.last_modified if prior else None,
        )
    except RobotsDisallowedError as exc:
        logger.warning(str(exc))
        stats["errors"] += 1
        return stats
    except Exception:
        logger.exception("fetch failed for %s", seed.url)
        stats["errors"] += 1
        return stats

    stats["pages_fetched"] += 1

    cache_result = cache.record_fetch(
        session,
        source_id=source.id,
        url=seed.url,
        page_kind=seed.page_kind,
        http_status=result.status_code,
        body_text=result.text,
        etag=result.etag,
        last_modified=result.last_modified,
        not_modified=result.not_modified,
    )

    if not cache_result.is_new_or_changed or not cache_result.raw_page.raw_html:
        return stats

    stats["pages_changed"] += 1

    try:
        dtos = adapter.parse(cache_result.raw_page.raw_html, seed.url, seed.page_kind)
    except Exception:
        logger.exception("parse failed for %s (%s)", seed.url, source.key)
        stats["errors"] += 1
        return stats

    now = datetime.datetime.now(datetime.UTC)
    for dto in dtos:
        session.add(
            ExtractedRecord(
                raw_page_id=cache_result.raw_page.id,
                source_id=source.id,
                entity_type=dto.entity_type,
                extracted_at=now,
                extractor_version=EXTRACTOR_VERSION,
                payload=dto.payload,
                natural_key_hint=dto.natural_key_hint,
            )
        )
    session.flush()
    stats["records_extracted"] += len(dtos)
    return stats


def _enabled_sources(session: Session, source_keys: list[str] | None) -> list[Source]:
    sources = list(session.scalars(select(Source).where(Source.enabled.is_(True))).all())
    if source_keys:
        sources = [s for s in sources if s.key in source_keys]
    return sources


def _sum_stats(totals: dict, stats: dict) -> None:
    for k in EMPTY_STATS:
        totals[k] += stats[k]


def run_full_crawl(
    session: Session, *, source_keys: list[str] | None = None, confirm_tos: bool, triggered_by: str = "cli"
) -> dict:
    if not confirm_tos:
        raise ValueError(
            "Full crawl requires explicit ToS confirmation. Pass --confirm-tos once you've "
            "reviewed each enabled source's terms of service / robots.txt."
        )

    festival = _current_festival(session)
    sources = _enabled_sources(session, source_keys)
    if not sources:
        raise RuntimeError(
            "No sources are enabled. Use `epcot-fw sources enable <key>` for each source "
            "you've reviewed and want to crawl."
        )

    run = CrawlRun(
        run_type="full",
        triggered_by=triggered_by,
        started_at=datetime.datetime.now(datetime.UTC),
        status="running",
    )
    session.add(run)
    session.flush()

    totals = dict(EMPTY_STATS)
    for source in sources:
        adapter = SOURCE_REGISTRY.get(source.key)
        if adapter is None:
            continue
        for seed in adapter.seed_urls(festival.year):
            _sum_stats(totals, _fetch_and_stage(session, adapter, source, seed))
        session.commit()

    totals["manual_overrides"] = stage_manual_overrides(session)
    resolve_stats = run_resolve(session, festival_id=festival.id)
    totals.update(resolve_stats)

    run.status = "success"
    run.finished_at = datetime.datetime.now(datetime.UTC)
    run.stats = totals
    session.commit()

    return totals
