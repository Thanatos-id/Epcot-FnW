import datetime

from epcot_fw.parse.generic_blog import extract_priced_items
from epcot_fw.parse.html_utils import soupify
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.sources.base import SeedUrl, SourceAdapter
from epcot_fw.sources.common import rss_discover

# The historical disneyparks.disney.go.com/blog URL now redirects here.
BASE_URL = "https://disneyparksblog.com"
FEED_URL = f"{BASE_URL}/feed/"


class DisneyParksBlogAdapter(SourceAdapter):
    key = "disney_parks_blog"
    priority_rank = 2

    def seed_urls(self, festival_year: int) -> list[SeedUrl]:
        return []

    def discover_new_urls(self, since: datetime.datetime, festival_year: int) -> list[SeedUrl]:
        return rss_discover(FEED_URL, since, crawl_delay_sec=8)

    def parse(self, raw_html: str, url: str, page_kind: str) -> list[ExtractedRecordDTO]:
        soup = soupify(raw_html)
        article = soup.find("article") or soup.find(class_="entry-content") or soup
        return extract_priced_items(article)
