import datetime
import re

from epcot_fw.parse.generic_blog import extract_priced_items
from epcot_fw.parse.html_utils import soupify
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.sources.base import SeedUrl, SourceAdapter

BASE_URL = "https://www.wdwmagic.com"
NEWS_INDEX_PATH = "/events/international-food-and-wine-festival/news.htm"
OVERVIEW_PATH = "/events/international-food-and-wine-festival.htm"

# News article URLs look like:
#   /events/international-food-and-wine-festival/news/07aug2026-epcot-food-wine-...htm
_ARTICLE_DATE_RE = re.compile(r"/news/(\d{2})([a-z]{3})(\d{4})-", re.IGNORECASE)
_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}


class WdwMagicAdapter(SourceAdapter):
    key = "wdwmagic"
    priority_rank = 5

    def seed_urls(self, festival_year: int) -> list[SeedUrl]:
        return [
            SeedUrl(url=f"{BASE_URL}{OVERVIEW_PATH}", page_kind="festival_overview"),
            SeedUrl(url=f"{BASE_URL}{NEWS_INDEX_PATH}", page_kind="blog_post"),
        ]

    def discover_new_urls(self, since: datetime.datetime, festival_year: int) -> list[SeedUrl]:
        from epcot_fw.fetch.http_client import fetch

        result = fetch(f"{BASE_URL}{NEWS_INDEX_PATH}", crawl_delay_sec=5)
        if result.not_modified or not result.text:
            return []
        soup = soupify(result.text)
        seeds: list[SeedUrl] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            match = _ARTICLE_DATE_RE.search(href)
            if not match:
                continue
            day, mon, year = match.groups()
            month = _MONTHS.get(mon.lower())
            if not month:
                continue
            try:
                published = datetime.datetime(int(year), month, int(day), tzinfo=datetime.UTC)
            except ValueError:
                continue
            if published < since:
                continue
            url = href if href.startswith("http") else f"{BASE_URL}{href}"
            if url not in seen:
                seen.add(url)
                seeds.append(SeedUrl(url=url, page_kind="blog_post"))
        return seeds

    def parse(self, raw_html: str, url: str, page_kind: str) -> list[ExtractedRecordDTO]:
        soup = soupify(raw_html)
        article = soup.find("article") or soup.find(class_="content") or soup
        return extract_priced_items(article)
