import datetime

import httpx
import pytest
import respx

from epcot_fw.fetch import rate_limiter
from epcot_fw.sources.wdwmagic import BASE_URL, NEWS_INDEX_PATH, OVERVIEW_PATH, WdwMagicAdapter


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)


def test_seed_urls_are_the_overview_and_news_index():
    seeds = WdwMagicAdapter().seed_urls(2026)
    urls = {s.url for s in seeds}
    assert f"{BASE_URL}{OVERVIEW_PATH}" in urls
    assert f"{BASE_URL}{NEWS_INDEX_PATH}" in urls


def test_parse_extracts_priced_items_from_the_content_container():
    html = '<html><body><div class="content"><ul><li>Cheese Plate - $8</li></ul></div></body></html>'
    records = WdwMagicAdapter().parse(html, f"{BASE_URL}{OVERVIEW_PATH}", "festival_overview")
    assert len(records) == 1
    assert records[0].payload["name"] == "Cheese Plate"


NEWS_INDEX_HTML = """
<html><body>
  <a href="/events/international-food-and-wine-festival/news/07aug2026-epcot-food-wine-menus.htm">Menus revealed</a>
  <a href="/events/international-food-and-wine-festival/news/01jan2020-old-news-article.htm">Old news</a>
  <a href="/some/unrelated/link.htm">Unrelated</a>
</body></html>
"""


def test_discover_new_urls_filters_by_date_embedded_in_the_article_url():
    since = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(f"{BASE_URL}{NEWS_INDEX_PATH}").mock(return_value=httpx.Response(200, text=NEWS_INDEX_HTML))

        seeds = WdwMagicAdapter().discover_new_urls(since)

    urls = {s.url for s in seeds}
    assert f"{BASE_URL}/events/international-food-and-wine-festival/news/07aug2026-epcot-food-wine-menus.htm" in urls
    assert not any("01jan2020" in u for u in urls)
    assert not any("unrelated" in u for u in urls)
    assert all(s.page_kind == "blog_post" for s in seeds)


def test_discover_new_urls_returns_empty_when_not_modified():
    since = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(f"{BASE_URL}{NEWS_INDEX_PATH}").mock(return_value=httpx.Response(304))

        seeds = WdwMagicAdapter().discover_new_urls(since)

    assert seeds == []


def test_discover_new_urls_dedupes_repeated_links():
    since = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    html = (
        '<a href="/events/international-food-and-wine-festival/news/07aug2026-a.htm">A</a>'
        '<a href="/events/international-food-and-wine-festival/news/07aug2026-a.htm">A again</a>'
    )
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(f"{BASE_URL}{NEWS_INDEX_PATH}").mock(return_value=httpx.Response(200, text=html))

        seeds = WdwMagicAdapter().discover_new_urls(since)

    assert len(seeds) == 1
