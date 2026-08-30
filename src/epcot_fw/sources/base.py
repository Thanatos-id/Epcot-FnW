import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass

from epcot_fw.parse.schemas import ExtractedRecordDTO


@dataclass(frozen=True)
class SeedUrl:
    url: str
    page_kind: str  # 'booth_list','booth_detail','menu','event_schedule',
    # 'seminar_schedule','blog_post','festival_overview'


class SourceAdapter(ABC):
    key: str
    priority_rank: int

    @abstractmethod
    def seed_urls(self, festival_year: int) -> list[SeedUrl]:
        """Fixed set of URLs to (re)fetch every crawl/refresh run."""

    def discover_new_urls(self, since: datetime.datetime, festival_year: int) -> list[SeedUrl]:
        """New URLs (e.g. blog posts) published since `since`. Default: none -
        override for sources with an RSS feed or a "recent posts" index.

        `festival_year` is the year being crawled. Sources whose discovered
        URLs are year-specific must use it to reject other years' pages:
        booth and dish names repeat season to season, so a prior year's post
        will happily fuzzy-match onto this year's entities.
        """
        return []

    def page_kind_for(self, url: str) -> str | None:
        """What kind of page this URL is, judged from the URL alone, or None
        when the source cannot tell.

        Only used by one-off ingestion (`epcot-fw ingest`), where there is no
        seed or discovery step to have decided already. A source whose page
        kinds are not readable from the URL should leave this alone and let
        the caller say.
        """
        return None

    @abstractmethod
    def parse(self, raw_html: str, url: str, page_kind: str) -> list[ExtractedRecordDTO]:
        """Extract structured records from one fetched page."""
