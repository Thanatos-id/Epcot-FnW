import datetime
import re
from calendar import timegm

import feedparser

from epcot_fw.fetch.http_client import fetch
from epcot_fw.sources.base import SeedUrl

_DEFAULT_KEYWORD_RE = re.compile(r"food\s*(and|&)?\s*wine|epcot", re.IGNORECASE)


def rss_discover(
    feed_url: str,
    since: datetime.datetime,
    *,
    crawl_delay_sec: float = 5.0,
    keyword_re: re.Pattern = _DEFAULT_KEYWORD_RE,
    page_kind: str = "blog_post",
) -> list[SeedUrl]:
    """Fetch an RSS feed and return entries published since `since` whose
    title/summary look Food & Wine Festival related. Used by blog-style
    sources to pick up new posts between full crawls."""
    result = fetch(feed_url, crawl_delay_sec=crawl_delay_sec)
    if result.not_modified or not result.text:
        return []

    parsed = feedparser.parse(result.text)
    seeds: list[SeedUrl] = []
    for entry in parsed.entries:
        published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if published_struct:
            published_at = datetime.datetime.fromtimestamp(
                timegm(published_struct), tz=datetime.UTC
            )
            if published_at < since:
                continue
        haystack = f"{entry.get('title', '')} {entry.get('summary', '')}"
        if not keyword_re.search(haystack):
            continue
        link = entry.get("link")
        if link:
            seeds.append(SeedUrl(url=link, page_kind=page_kind))
    return seeds
