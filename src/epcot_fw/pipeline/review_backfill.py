"""Sweeps a season's Disney Food Blog review posts for dish photos.

The daily refresh reads the festival tag's feed, which holds about ten
entries - four days at festival pace. That keeps a running crawl current and
cannot reach backwards, so every review published before the crawler learned
to read that shape, or during any gap in the schedule, is simply missing.
`epcot-fw ingest` fixes one of those at a time if you know the URL. This
fixes the whole backlog without you having to.

Posts already cached are not refetched. fetch/cache.py would answer most of
them with a conditional GET anyway, but skipping them outright is what keeps
a second run of this cheap instead of merely polite, and DFB is a site that
answers a burst with 429.

Which is the other thing worth knowing: this stops early. A run that starts
collecting errors is a run that has been asked to slow down, and walking the
rest of the list at that point is how a source that rate-limits you becomes
a source that blocks you - see what allears.net now returns to everybody.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import RawPage, Source
from epcot_fw.pipeline.crawl import _current_festival, _fetch_and_stage
from epcot_fw.pipeline.resolve_pipeline import run_resolve
from epcot_fw.sources.registry import SOURCE_REGISTRY

logger = logging.getLogger(__name__)

SOURCE_KEY = "disney_food_blog"

# Consecutive failures before the sweep gives up. One is a bad page; three in
# a row is the site telling you something.
DEFAULT_STOP_AFTER_ERRORS = 3


@dataclass
class ReviewBackfillReport:
    discovered: int = 0
    already_cached: int = 0
    fetched: int = 0
    records: int = 0
    errors: int = 0
    stopped_early: bool = False
    ingested: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "discovered": self.discovered,
            "already_cached": self.already_cached,
            "fetched": self.fetched,
            "records": self.records,
            "errors": self.errors,
            "stopped_early": self.stopped_early,
        }


def _cached_urls(session: Session, urls: list[str]) -> set[str]:
    if not urls:
        return set()
    return set(
        session.scalars(
            select(RawPage.url).where(
                RawPage.url.in_(urls), RawPage.superseded_by_id.is_(None)
            )
        ).all()
    )


def backfill_reviews(
    session: Session,
    *,
    max_pages: int = 1,
    stop_after_errors: int = DEFAULT_STOP_AFTER_ERRORS,
    dry_run: bool = False,
) -> ReviewBackfillReport:
    """Find this season's review posts and ingest the ones not already held."""
    source = session.scalars(select(Source).where(Source.key == SOURCE_KEY)).first()
    if source is None:
        raise RuntimeError(f"no '{SOURCE_KEY}' source row - run `epcot-fw db seed`")
    adapter = SOURCE_REGISTRY[SOURCE_KEY]
    festival = _current_festival(session)

    report = ReviewBackfillReport()
    seeds = adapter.review_archive_seeds(festival.year, max_pages=max_pages)
    report.discovered = len(seeds)

    cached = _cached_urls(session, [s.url for s in seeds])
    todo = [s for s in seeds if s.url not in cached]
    report.already_cached = len(seeds) - len(todo)

    if dry_run:
        report.ingested = [s.url for s in todo]
        return report

    consecutive_errors = 0
    for seed in todo:
        stats = _fetch_and_stage(session, adapter, source, seed)
        report.fetched += stats["pages_fetched"]
        report.records += stats["records_extracted"]
        report.errors += stats["errors"]

        if stats["errors"]:
            consecutive_errors += 1
            if consecutive_errors >= stop_after_errors:
                logger.warning(
                    "%d fetches in a row failed - stopping the sweep rather than pressing on",
                    consecutive_errors,
                )
                report.stopped_early = True
                break
            continue

        consecutive_errors = 0
        if stats["records_extracted"]:
            report.ingested.append(seed.url)

    if report.fetched:
        run_resolve(session, festival_id=festival.id)
    return report
