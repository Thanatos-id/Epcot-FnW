"""Fetch and ingest one page, named on the command line.

The crawl finds pages two ways: a fixed seed list, and each source's own
discovery. Both are built for keeping up with a site, and neither reaches
backwards. Disney Food Blog's festival tag feed holds about ten entries -
four days at festival pace - so a review published before the crawler
learned to read that shape is not reachable by re-running anything.

This is the way in for one you found yourself: one URL, one polite request,
through exactly the same fetch/cache/parse/resolve path a crawled page
takes, so what lands is indistinguishable from what a crawl would have
landed and the page is cached against being fetched twice.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import Source
from epcot_fw.pipeline.crawl import _current_festival, _fetch_and_stage
from epcot_fw.pipeline.resolve_pipeline import run_resolve
from epcot_fw.sources.base import SeedUrl
from epcot_fw.sources.registry import SOURCE_REGISTRY

logger = logging.getLogger(__name__)


class IngestError(RuntimeError):
    """The URL does not belong to a source this build knows how to read."""


def source_for_url(session: Session, url: str) -> Source:
    """The configured source whose site this URL belongs to."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if not host:
        raise IngestError(f"{url!r} is not a URL with a host in it")

    for source in session.scalars(select(Source).order_by(Source.priority_rank)).all():
        if urlparse(source.base_url).netloc.lower().removeprefix("www.") == host:
            return source
    known = ", ".join(sorted(urlparse(s.base_url).netloc for s in session.scalars(select(Source)).all() if s.base_url.startswith("http")))
    raise IngestError(f"no source configured for {host} - known hosts: {known}")


def ingest_one_url(session: Session, url: str, *, page_kind: str | None = None) -> dict:
    """Fetch `url`, stage what it parses to, and resolve. Returns crawl stats.

    Deliberately ignores whether the source is enabled: naming a URL by hand
    is a decision to read that page, not a change to what gets crawled on a
    schedule.
    """
    source = source_for_url(session, url)
    adapter = SOURCE_REGISTRY.get(source.key)
    if adapter is None:
        raise IngestError(f"source {source.key!r} has no adapter in this build")

    kind = page_kind or adapter.page_kind_for(url)
    if kind is None:
        raise IngestError(
            f"cannot tell what kind of page {url} is - pass --page-kind "
            f"(e.g. booth_review for a dated review permalink)"
        )

    festival = _current_festival(session)
    stats = _fetch_and_stage(session, adapter, source, SeedUrl(url=url, page_kind=kind))
    stats["page_kind"] = kind
    stats["source"] = source.key
    stats.update(run_resolve(session, festival_id=festival.id))
    return stats
