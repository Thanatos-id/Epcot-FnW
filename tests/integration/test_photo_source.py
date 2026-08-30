"""Where each dish photo came from.

Every photo on these pages was taken by somebody else, and nothing recorded
that next to the picture until now. The chain exists in the database: a
photo arrives as an extracted_record on a raw_page, and both survive as
provenance.
"""

import datetime

import pytest
from sqlalchemy import select

from epcot_fw.db.models import (
    Booth,
    EntityFieldProvenance,
    ExtractedRecord,
    MenuItem,
    RawPage,
    Source,
)
from epcot_fw.pipeline.photo_source import (
    OWN_CREDIT,
    image_sources,
    is_hand_published,
    photo_credit,
    photo_season,
)

DFB = "https://www.disneyfoodblog.com/wp-content/uploads"
PAGES = "https://thanatos-id.github.io/Epcot-FnW/dish-photos"
POST = "https://www.disneyfoodblog.com/2026/08/27/review-a-booth/"


@pytest.fixture()
def dish(db_session):
    festival_id = db_session.info["festival_id"]
    booth = Booth(festival_id=festival_id, canonical_name="Belgium", slug="belgium")
    db_session.add(booth)
    db_session.flush()
    item = MenuItem(booth_id=booth.id, canonical_name="Belgian Waffle", category="food")
    db_session.add(item)
    db_session.flush()
    return item


def _offer(db_session, item, source_key, value, *, page_url, selected=False):
    source = db_session.scalars(select(Source).where(Source.key == source_key)).one()
    now = datetime.datetime.now(datetime.UTC)
    page = RawPage(
        source_id=source.id, url=page_url, page_kind="booth_review", fetched_at=now,
        http_status=200, content_hash=str(abs(hash(value))), raw_html="<html></html>",
        first_seen_at=now,
    )
    db_session.add(page)
    db_session.flush()
    record = ExtractedRecord(
        raw_page_id=page.id, source_id=source.id, entity_type="menu_item",
        extracted_at=now, extractor_version="test", payload={"image_url": value},
    )
    db_session.add(record)
    db_session.flush()
    db_session.add(EntityFieldProvenance(
        entity_type="menu_item", canonical_id=item.id, field_name="image_url",
        source_id=source.id, extracted_record_id=record.id, value=value,
        observed_at=now, is_selected=selected,
    ))
    db_session.flush()


# ---------------------------------------------------------------------------
# reading a URL
# ---------------------------------------------------------------------------


def test_the_publisher_comes_from_the_host_serving_the_image():
    assert photo_credit(f"{DFB}/2026/08/plate.jpg") == "Disney Food Blog"
    assert photo_credit("https://allears.net/wp-content/uploads/2025/08/x.jpg") == "AllEars.Net"


def test_a_photo_we_published_credits_us_not_a_publisher():
    assert photo_credit(f"{PAGES}/abc.jpg") == OWN_CREDIT
    assert is_hand_published(f"{PAGES}/abc.jpg")


def test_an_unknown_host_is_credited_honestly_rather_than_guessed_at():
    assert photo_credit("https://someblog.example/img/plate.jpg") == "someblog.example"


def test_no_photo_means_no_credit():
    assert photo_credit(None) is None
    assert photo_season(None) is None


# ---------------------------------------------------------------------------
# attribution
# ---------------------------------------------------------------------------


def test_a_crawled_photo_traces_back_to_the_post_it_ran_in(db_session, dish):
    url = f"{DFB}/2026/08/waffle.jpg"
    dish.image_url = url
    db_session.flush()
    _offer(db_session, dish, "disney_food_blog", url, page_url=POST, selected=True)

    src = image_sources(db_session, [dish.id])[dish.id]
    assert src["credit"] == "Disney Food Blog"
    assert src["season"] == 2026
    assert src["page_url"] == POST
    assert src["via"] == "disney_food_blog"


def test_a_curated_photo_carries_a_credit_but_no_post(db_session, dish):
    """backfill-images records the image and not the article it was on, so
    those keep a publisher and a season and have nothing to link to."""
    url = f"{DFB}/2025/08/waffle.jpg"
    dish.image_url = url
    db_session.flush()
    _offer(db_session, dish, "manual", url, page_url="manual://menu-items", selected=True)

    src = image_sources(db_session, [dish.id])[dish.id]
    assert src["credit"] == "Disney Food Blog"
    assert src["season"] == 2025
    assert src["page_url"] is None
    assert src["via"] == "manual"


def test_the_candidate_holding_the_served_url_wins_the_attribution(db_session, dish):
    """Not the one flagged is_selected. That flag is unreliable - most dishes
    in the real database carry a row holding exactly the served URL and still
    flagged unselected - and crediting the wrong post is worse than none."""
    served = f"{DFB}/2026/08/waffle.jpg"
    dish.image_url = served
    db_session.flush()
    _offer(db_session, dish, "manual", f"{DFB}/2025/08/old.jpg", page_url="manual://menu-items", selected=True)
    _offer(db_session, dish, "disney_food_blog", served, page_url=POST, selected=False)

    src = image_sources(db_session, [dish.id])[dish.id]
    assert src["via"] == "disney_food_blog"
    assert src["page_url"] == POST
    assert src["season"] == 2026


def test_a_dish_with_no_photo_is_not_in_the_result(db_session, dish):
    assert image_sources(db_session, [dish.id]) == {}


def test_a_photo_with_no_provenance_still_gets_a_credit(db_session, dish):
    """The URL alone names a publisher and a season; only the link is lost."""
    dish.image_url = f"{DFB}/2025/08/waffle.jpg"
    db_session.flush()

    src = image_sources(db_session, [dish.id])[dish.id]
    assert src["credit"] == "Disney Food Blog"
    assert src["season"] == 2025
    assert src["via"] is None


def test_asking_about_nothing_costs_no_query(db_session):
    assert image_sources(db_session, []) == {}
