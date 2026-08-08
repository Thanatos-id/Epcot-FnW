import datetime

from epcot_fw.parse.generic_blog import extract_priced_items
from epcot_fw.parse.html_utils import soupify
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.sources.base import SeedUrl, SourceAdapter
from epcot_fw.sources.common import rss_discover

BASE_URL = "https://touringplans.com"
FEED_URL = f"{BASE_URL}/blog/feed/"
EVENT_PAGE_PATH = "/walt-disney-world/events/epcot-international-food-wine-festival"


class TouringPlansAdapter(SourceAdapter):
    key = "touring_plans"
    priority_rank = 3

    def seed_urls(self, festival_year: int) -> list[SeedUrl]:
        # Note: this event page is a client-rendered SPA view - a plain HTTP
        # fetch may only capture the initial shell. Kept as a seed anyway
        # since Touring Plans sometimes server-renders enough for parsing;
        # the RSS feed (discover_new_urls) is the primary channel for this
        # source and doesn't have that limitation.
        return [SeedUrl(url=f"{BASE_URL}{EVENT_PAGE_PATH}", page_kind="festival_overview")]

    def discover_new_urls(self, since: datetime.datetime) -> list[SeedUrl]:
        return rss_discover(FEED_URL, since, crawl_delay_sec=5)

    def parse(self, raw_html: str, url: str, page_kind: str) -> list[ExtractedRecordDTO]:
        soup = soupify(raw_html)
        article = soup.find("article") or soup.find(class_="entry-content") or soup
        return extract_priced_items(article)
