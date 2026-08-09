import datetime

import httpx
import pytest
import respx

from epcot_fw.fetch import rate_limiter
from epcot_fw.sources.common import rss_discover

FEED_URL = "https://example.test/feed/"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    # rate_limiter tracks last-request-time per domain in module-global state,
    # so back-to-back tests hitting the same fake domain would otherwise incur
    # a real time.sleep for the source's crawl_delay_sec - rate limiting
    # itself isn't what these tests are about.
    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)

FEED_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Example Blog</title>
  <item>
    <title>Old post about Epcot Food and Wine</title>
    <link>https://example.test/old-post</link>
    <pubDate>{old_date}</pubDate>
  </item>
  <item>
    <title>New post, unrelated topic</title>
    <link>https://example.test/unrelated-post</link>
    <pubDate>{new_date}</pubDate>
  </item>
  <item>
    <title>New post about the EPCOT Food &amp; Wine Festival</title>
    <link>https://example.test/relevant-post</link>
    <pubDate>{new_date}</pubDate>
  </item>
  <item>
    <title>New post about Food and Wine, no link</title>
    <pubDate>{new_date}</pubDate>
  </item>
</channel>
</rss>
"""


def _feed_text(since: datetime.datetime) -> str:
    old_date = (since - datetime.timedelta(days=5)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    new_date = (since + datetime.timedelta(days=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    return FEED_TEMPLATE.format(old_date=old_date, new_date=new_date)


def test_filters_out_entries_published_before_since():
    since = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://example.test/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(FEED_URL).mock(return_value=httpx.Response(200, text=_feed_text(since)))
        seeds = rss_discover(FEED_URL, since)

    urls = {s.url for s in seeds}
    assert "https://example.test/old-post" not in urls
    assert "https://example.test/relevant-post" in urls


def test_filters_out_entries_that_do_not_match_the_keyword_pattern():
    since = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://example.test/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(FEED_URL).mock(return_value=httpx.Response(200, text=_feed_text(since)))
        seeds = rss_discover(FEED_URL, since)

    urls = {s.url for s in seeds}
    assert "https://example.test/unrelated-post" not in urls


def test_entries_without_a_link_are_skipped():
    since = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://example.test/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(FEED_URL).mock(return_value=httpx.Response(200, text=_feed_text(since)))
        seeds = rss_discover(FEED_URL, since)

    assert all(s.url for s in seeds)
    assert len(seeds) == 1


def test_seed_urls_carry_the_requested_page_kind():
    since = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://example.test/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(FEED_URL).mock(return_value=httpx.Response(200, text=_feed_text(since)))
        seeds = rss_discover(FEED_URL, since, page_kind="blog_post")

    assert all(s.page_kind == "blog_post" for s in seeds)


def test_returns_empty_list_when_feed_body_is_empty():
    since = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://example.test/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(FEED_URL).mock(return_value=httpx.Response(200, text=""))
        seeds = rss_discover(FEED_URL, since)

    assert seeds == []
