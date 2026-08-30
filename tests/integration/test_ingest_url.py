"""Ingesting one page named on the command line.

The crawl keeps up with a site; it does not reach backwards. DFB's festival
feed holds about ten entries, so a review published before the crawler
learned to read that shape cannot be reached by re-running anything. This is
the way in for one you found yourself.
"""

import httpx
import pytest
import respx
from sqlalchemy import select

from epcot_fw.db.models import Booth, MenuItem, RawPage
from epcot_fw.fetch import rate_limiter
from epcot_fw.pipeline.ingest_url import IngestError, ingest_one_url, source_for_url
from epcot_fw.sources.disney_food_blog import BASE_URL

REVIEW_URL = f"{BASE_URL}/2026/08/27/review-a-booth-that-keeps-it-simple/"
PHOTO = (
    f"{BASE_URL}/wp-content/uploads/2026/08/"
    "2026-Disney-World-WDW-EPCOT-Food-and-Wine-Festival-Belgium-Booth-Belgian-Waffle-700x525.jpg"
)
PHOTO_2 = (
    f"{BASE_URL}/wp-content/uploads/2026/08/"
    "2026-Disney-World-WDW-EPCOT-Food-and-Wine-Festival-Belgium-Booth-Beer-700x525.jpg"
)

REVIEW_HTML = f"""
<html><body><article><h1>Get the DFB Newsletter</h1>
  <figure><img src="{PHOTO}" /><figcaption>Belgian Waffle</figcaption></figure>
  <figure><img src="{PHOTO_2}" /><figcaption>Full Spread</figcaption></figure>
</article></body></html>
"""


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


def _ingest(db_session, url=REVIEW_URL, html=REVIEW_HTML, status=200, **kw):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(url).mock(return_value=httpx.Response(status, text=html))
        return ingest_one_url(db_session, url, **kw)


# ---------------------------------------------------------------------------
# picking the source
# ---------------------------------------------------------------------------


def test_the_source_is_found_from_the_urls_host(db_session):
    assert source_for_url(db_session, REVIEW_URL).key == "disney_food_blog"


def test_a_www_prefix_does_not_change_the_answer(db_session):
    plain = "https://disneyfoodblog.com/2026/08/27/review-x/"
    assert source_for_url(db_session, plain).key == "disney_food_blog"


def test_a_host_no_source_covers_is_refused_by_name(db_session):
    with pytest.raises(IngestError, match="no source configured for example.test"):
        source_for_url(db_session, "https://example.test/whatever/")


def test_something_that_is_not_a_url_is_refused(db_session):
    with pytest.raises(IngestError):
        source_for_url(db_session, "not-a-url")


# ---------------------------------------------------------------------------
# ingesting
# ---------------------------------------------------------------------------


def test_a_review_permalink_is_read_as_a_review_without_being_told(db_session, belgium):
    stats = _ingest(db_session)
    assert stats["page_kind"] == "booth_review"
    assert stats["source"] == "disney_food_blog"


def test_the_photo_lands_on_the_dish(db_session, belgium):
    _ingest(db_session)
    db_session.refresh(belgium)
    assert belgium.image_url == PHOTO


def test_the_chatty_caption_does_not_become_a_dish(db_session, belgium):
    _ingest(db_session)
    names = {
        i.canonical_name
        for i in db_session.scalars(select(MenuItem).where(MenuItem.booth_id == belgium.booth_id)).all()
    }
    assert names == {"Belgian Waffle"}


def test_the_page_is_cached_so_a_second_run_reparses_nothing(db_session, belgium):
    _ingest(db_session)
    again = _ingest(db_session)
    assert again["pages_changed"] == 0
    pages = db_session.scalars(select(RawPage).where(RawPage.url == REVIEW_URL)).all()
    assert len(pages) == 1


def test_an_error_response_is_not_cached_as_content(db_session, belgium):
    """A themed 404 has a body, and that body is not content."""
    stats = _ingest(db_session, status=404, html="<html>Not found</html>")
    assert stats["pages_fetched"] == 0
    assert stats["errors"] == 1
    assert db_session.scalars(select(RawPage).where(RawPage.url == REVIEW_URL)).all() == []


def test_a_url_whose_kind_cannot_be_guessed_says_so(db_session):
    with pytest.raises(IngestError, match="--page-kind"):
        _ingest(db_session, url=f"{BASE_URL}/some-other-article/")


def test_the_page_kind_can_be_given_explicitly(db_session, belgium):
    stats = _ingest(
        db_session, url=f"{BASE_URL}/some-other-article/", page_kind="booth_review"
    )
    assert stats["page_kind"] == "booth_review"
    db_session.refresh(belgium)
    assert belgium.image_url == PHOTO
