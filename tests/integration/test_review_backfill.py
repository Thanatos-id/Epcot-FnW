"""Sweeping a season's review posts.

The daily refresh reads a ten-entry feed and cannot reach backwards. This
walks the tag's HTML archive instead, which carries thirty-odd posts a page.
The interesting behaviour is all about restraint: not refetching what is
already held, and stopping when the site starts saying no.
"""

import httpx
import pytest
import respx
from sqlalchemy import select

from epcot_fw.db.models import Booth, MenuItem, RawPage
from epcot_fw.fetch import rate_limiter
from epcot_fw.pipeline.review_backfill import backfill_reviews
from epcot_fw.sources.disney_food_blog import BASE_URL, REVIEW_ARCHIVE_PATH

ARCHIVE = f"{BASE_URL}{REVIEW_ARCHIVE_PATH}/"
ARCHIVE_2 = f"{BASE_URL}{REVIEW_ARCHIVE_PATH}/page/2/"


def _post(year, slug):
    return f"{BASE_URL}/{year}/08/27/{slug}/"


def _photo(booth, dish):
    return (
        f"{BASE_URL}/wp-content/uploads/2026/08/"
        f"2026-Disney-World-WDW-EPCOT-Food-and-Wine-Festival-{booth}-Booth-{dish}-700x525.jpg"
    )


def _archive_html(*links):
    body = "".join(f'<a href="{u}">post</a>' for u in links)
    return f"<html><body><main>{body}</main></body></html>"


def _review_html(booth, *dishes):
    """A real review carries a dozen captioned photos. Two is the minimum the
    booth vote will act on, so a fixture with one would test the refusal
    rather than the ingest."""
    figures = "".join(
        f'<figure><img src="{_photo(booth, d.replace(" ", "-"))}" />'
        f"<figcaption>{d}</figcaption></figure>"
        for d in dishes
    )
    return f"<html><body><article><h1>Get the DFB Newsletter</h1>{figures}</article></body></html>"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)


@pytest.fixture()
def belgium(db_session):
    festival_id = db_session.info["festival_id"]
    booth = Booth(festival_id=festival_id, canonical_name="Belgium", slug="belgium")
    db_session.add(booth)
    db_session.flush()
    dish = MenuItem(booth_id=booth.id, canonical_name="Belgian Waffle", category="food")
    db_session.add(dish)
    db_session.flush()
    return dish


def _mock(routes):
    mock = respx.mock(assert_all_called=False)
    mock.get(f"{BASE_URL}/robots.txt").mock(return_value=httpx.Response(404))
    for url, response in routes.items():
        mock.get(url).mock(return_value=response)
    return mock


def test_the_seasons_posts_are_found_and_ingested(db_session, belgium):
    post = _post(2026, "review-belgium")
    with _mock({
        ARCHIVE: httpx.Response(200, text=_archive_html(post)),
        post: httpx.Response(200, text=_review_html("Belgium", "Belgian Waffle", "Beer-braised Beef", "Full Spread")),
    }):
        report = backfill_reviews(db_session)

    assert report.discovered == 1
    assert report.fetched == 1
    db_session.refresh(belgium)
    assert belgium.image_url == _photo("Belgium", "Belgian-Waffle")


def test_last_seasons_posts_are_not_swept_in(db_session, belgium):
    """Booth and dish names repeat season to season, so a 2025 review would
    fuzzy-match onto this year's rows and fill the ledger with old plates."""
    with _mock({
        ARCHIVE: httpx.Response(200, text=_archive_html(_post(2025, "review-belgium-last-year"))),
    }):
        report = backfill_reviews(db_session)

    assert report.discovered == 0
    assert report.fetched == 0


def test_a_post_already_held_is_not_refetched(db_session, belgium):
    post = _post(2026, "review-belgium")
    routes = {
        ARCHIVE: httpx.Response(200, text=_archive_html(post)),
        post: httpx.Response(200, text=_review_html("Belgium", "Belgian Waffle", "Beer-braised Beef", "Full Spread")),
    }
    with _mock(routes):
        backfill_reviews(db_session)
    with _mock(routes):
        again = backfill_reviews(db_session)

    assert again.already_cached == 1
    assert again.fetched == 0
    assert len(db_session.scalars(select(RawPage).where(RawPage.url == post)).all()) == 1


def test_the_sweep_stops_once_the_site_starts_refusing(db_session):
    """A run collecting errors has been asked to slow down. Walking the rest
    of the list is how a source that rate-limits you starts blocking you."""
    posts = [_post(2026, f"review-{i}") for i in range(6)]
    routes = {ARCHIVE: httpx.Response(200, text=_archive_html(*posts))}
    for p in posts:
        routes[p] = httpx.Response(429, text="slow down")

    with _mock(routes):
        report = backfill_reviews(db_session, stop_after_errors=3)

    assert report.stopped_early
    assert report.errors == 3, "should give up after three, not walk all six"
    assert report.fetched == 0


def test_an_archive_page_that_fails_ends_the_walk(db_session):
    with _mock({ARCHIVE: httpx.Response(429, text="slow down")}):
        report = backfill_reviews(db_session, max_pages=3)
    assert report.discovered == 0


def test_pagination_stops_when_a_page_has_none_of_this_season(db_session):
    """Past the end of the season's archive everything is last year's."""
    post = _post(2026, "review-belgium")
    with _mock({
        ARCHIVE: httpx.Response(200, text=_archive_html(post)),
        ARCHIVE_2: httpx.Response(200, text=_archive_html(_post(2025, "old-review"))),
    }):
        report = backfill_reviews(db_session, max_pages=4, dry_run=True)

    assert report.discovered == 1


def test_a_dry_run_lists_without_fetching(db_session, belgium):
    post = _post(2026, "review-belgium")
    with _mock({
        ARCHIVE: httpx.Response(200, text=_archive_html(post)),
        post: httpx.Response(200, text=_review_html("Belgium", "Belgian Waffle", "Beer-braised Beef", "Full Spread")),
    }):
        report = backfill_reviews(db_session, dry_run=True)

    assert report.discovered == 1
    assert report.ingested == [post]
    assert report.fetched == 0
    assert db_session.scalars(select(RawPage).where(RawPage.url == post)).all() == []
    db_session.refresh(belgium)
    assert belgium.image_url is None


def test_the_same_post_linked_twice_is_fetched_once(db_session, belgium):
    """The archive links each post from its thumbnail and its title."""
    post = _post(2026, "review-belgium")
    with _mock({
        ARCHIVE: httpx.Response(200, text=_archive_html(post, post, post)),
        post: httpx.Response(200, text=_review_html("Belgium", "Belgian Waffle", "Beer-braised Beef", "Full Spread")),
    }):
        report = backfill_reviews(db_session)

    assert report.discovered == 1
    assert report.fetched == 1
