"""touring_plans, wdw_prep_school, and disney_parks_blog all delegate parse()
to the shared extract_priced_items() (see test_generic_blog.py for the
extraction logic itself) - these tests just confirm each adapter's own
container-selection fallback (<article> / .entry-content / whole soup) and
seed/feed wiring are correct."""

import datetime

import httpx
import pytest
import respx

from epcot_fw.fetch import rate_limiter
from epcot_fw.sources.disney_parks_blog import FEED_URL as PARKS_BLOG_FEED_URL
from epcot_fw.sources.disney_parks_blog import DisneyParksBlogAdapter
from epcot_fw.sources.touring_plans import EVENT_PAGE_PATH, TouringPlansAdapter
from epcot_fw.sources.touring_plans import FEED_URL as TOURING_PLANS_FEED_URL
from epcot_fw.sources.wdw_prep_school import FEED_URL as PREP_SCHOOL_FEED_URL
from epcot_fw.sources.wdw_prep_school import WdwPrepSchoolAdapter

ARTICLE_HTML = "<html><body><article><ul><li>Cheese Plate - $8</li></ul></article></body></html>"
ENTRY_CONTENT_HTML = (
    '<html><body><div class="entry-content"><ul><li>Cheese Plate - $8</li></ul></div></body></html>'
)
NO_CONTAINER_HTML = "<html><body><ul><li>Cheese Plate - $8</li></ul></body></html>"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)


@pytest.mark.parametrize(
    "adapter_cls",
    [TouringPlansAdapter, WdwPrepSchoolAdapter, DisneyParksBlogAdapter],
)
@pytest.mark.parametrize("html", [ARTICLE_HTML, ENTRY_CONTENT_HTML, NO_CONTAINER_HTML])
def test_parse_extracts_priced_items_regardless_of_container(adapter_cls, html):
    records = adapter_cls().parse(html, "https://example.test/post", "blog_post")
    assert len(records) == 1
    assert records[0].payload["name"] == "Cheese Plate"
    assert records[0].payload["price_usd"] == "8"


def test_touring_plans_seed_urls_point_at_the_event_page():
    seeds = TouringPlansAdapter().seed_urls(2026)
    assert len(seeds) == 1
    assert seeds[0].url.endswith(EVENT_PAGE_PATH)
    assert seeds[0].page_kind == "festival_overview"


def test_wdw_prep_school_has_no_fixed_seed_urls():
    assert WdwPrepSchoolAdapter().seed_urls(2026) == []


def test_disney_parks_blog_has_no_fixed_seed_urls():
    assert DisneyParksBlogAdapter().seed_urls(2026) == []


def _feed_xml(link: str) -> str:
    date = datetime.datetime(2026, 8, 5, tzinfo=datetime.UTC)
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>EPCOT Food and Wine Festival update</title>
    <link>{link}</link>
    <pubDate>{date.strftime("%a, %d %b %Y %H:%M:%S GMT")}</pubDate>
  </item>
</channel></rss>"""


def test_touring_plans_discover_new_urls_hits_its_own_feed():
    since = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://touringplans.com/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(TOURING_PLANS_FEED_URL).mock(
            return_value=httpx.Response(200, text=_feed_xml("https://touringplans.com/blog/new-post"))
        )
        seeds = TouringPlansAdapter().discover_new_urls(since, 2026)

    assert [s.url for s in seeds] == ["https://touringplans.com/blog/new-post"]


def test_wdw_prep_school_discover_new_urls_hits_its_own_feed():
    since = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://wdwprepschool.com/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(PREP_SCHOOL_FEED_URL).mock(
            return_value=httpx.Response(200, text=_feed_xml("https://wdwprepschool.com/new-post"))
        )
        seeds = WdwPrepSchoolAdapter().discover_new_urls(since, 2026)

    assert [s.url for s in seeds] == ["https://wdwprepschool.com/new-post"]


def test_disney_parks_blog_discover_new_urls_hits_its_own_feed():
    since = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://disneyparksblog.com/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(PARKS_BLOG_FEED_URL).mock(
            return_value=httpx.Response(200, text=_feed_xml("https://disneyparksblog.com/new-post"))
        )
        seeds = DisneyParksBlogAdapter().discover_new_urls(since, 2026)

    assert [s.url for s in seeds] == ["https://disneyparksblog.com/new-post"]
