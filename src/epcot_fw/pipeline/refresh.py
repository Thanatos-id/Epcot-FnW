import datetime
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import CrawlRun
from epcot_fw.pipeline.crawl import (
    EMPTY_STATS,
    _current_festival,
    _enabled_sources,
    _fetch_and_stage,
    _sum_stats,
)
from epcot_fw.pipeline.resolve_pipeline import run_resolve
from epcot_fw.sources.registry import SOURCE_REGISTRY

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 30


def run_refresh(session: Session, *, source_keys: list[str] | None = None, triggered_by: str = "cli") -> dict:
    """Weekly incremental refresh: re-fetch known seed URLs (cheap - conditional
    GET/hash diff means unchanged pages don't get reparsed) plus discover any
    new posts published since the last successful run, then re-resolve."""
    festival = _current_festival(session)
    sources = _enabled_sources(session, source_keys)
    if not sources:
        raise RuntimeError(
            "No sources are enabled. Use `epcot-fw sources enable <key>` for each source "
            "you've reviewed and want to crawl."
        )

    last_run = session.scalars(
        select(CrawlRun).where(CrawlRun.status == "success").order_by(CrawlRun.finished_at.desc())
    ).first()
    since = (
        last_run.finished_at
        if last_run is not None
        else datetime.datetime.now(datetime.UTC)
        - datetime.timedelta(days=DEFAULT_LOOKBACK_DAYS)
    )

    run = CrawlRun(
        run_type="refresh",
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

        seeds = list(adapter.seed_urls(festival.year))
        try:
            seeds.extend(adapter.discover_new_urls(since))
        except Exception:
            logger.exception("discover_new_urls failed for %s", source.key)

        for seed in seeds:
            _sum_stats(totals, _fetch_and_stage(session, adapter, source, seed))
        session.commit()

    resolve_stats = run_resolve(session, festival_id=festival.id)
    totals.update(resolve_stats)

    run.status = "success"
    run.finished_at = datetime.datetime.now(datetime.UTC)
    run.stats = totals
    session.commit()

    return totals
