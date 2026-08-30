"""Letting this season's photo beat last season's stand-in.

backfill-images stages historical photos into the curated file at
priority_rank 0, which outranks every later observation permanently. Free
while the current season has no photos of its own; the moment it does, a
dish shows a 2025 plate with an actual 2026 photo selected against
underneath it.
"""

import datetime
import json

import pytest
from sqlalchemy import select

from epcot_fw.db.models import (
    Booth,
    EntityFieldProvenance,
    ExtractedRecord,
    Festival,
    MenuItem,
    RawPage,
    Source,
)
from epcot_fw.pipeline.photo_promotion import (
    is_hand_published,
    photo_season,
    promote_current_season_photos,
)

DFB = "https://www.disneyfoodblog.com/wp-content/uploads"
PAGES = "https://thanatos-id.github.io/Epcot-FnW/dish-photos"


@pytest.fixture()
def dish(db_session):
    festival_id = db_session.info["festival_id"]
    booth = Booth(festival_id=festival_id, canonical_name="Shimmering Sips", slug="shimmering-sips")
    db_session.add(booth)
    db_session.flush()
    item = MenuItem(booth_id=booth.id, canonical_name="Berry Mimosa", category="alcoholic_beverage")
    db_session.add(item)
    db_session.flush()
    return item


def _candidate(db_session, item, source_key, value, *, selected):
    """One source's offered photo for this dish, with the raw_page and
    extracted_record the real pipeline would have put behind it."""
    source = db_session.scalars(select(Source).where(Source.key == source_key)).one()
    now = datetime.datetime.now(datetime.UTC)
    page = RawPage(
        source_id=source.id,
        url=f"https://example.test/{source_key}/{item.id}/{abs(hash(value))}",
        page_kind="booth_detail",
        fetched_at=now,
        http_status=200,
        content_hash=str(abs(hash(value))),
        raw_html="<html></html>",
        first_seen_at=now,
    )
    db_session.add(page)
    db_session.flush()
    record = ExtractedRecord(
        raw_page_id=page.id,
        source_id=source.id,
        entity_type="menu_item",
        extracted_at=now,
        extractor_version="test",
        payload={"name": item.canonical_name, "image_url": value},
    )
    db_session.add(record)
    db_session.flush()
    row = EntityFieldProvenance(
        entity_type="menu_item",
        canonical_id=item.id,
        field_name="image_url",
        source_id=source.id,
        extracted_record_id=record.id,
        value=value,
        observed_at=now,
        is_selected=selected,
    )
    db_session.add(row)
    db_session.flush()
    if selected:
        item.image_url = value
        db_session.flush()
    return row


def _year(db_session) -> int:
    return db_session.scalars(select(Festival).order_by(Festival.year.desc())).first().year


def _curated(tmp_path, entries):
    path = tmp_path / "menu_items.json"
    path.write_text(json.dumps({"_README": ["keep me"], "menu_items": entries}))
    return path


# ---------------------------------------------------------------------------
# reading a photo URL
# ---------------------------------------------------------------------------


def test_a_wordpress_upload_path_dates_the_photo():
    assert photo_season(f"{DFB}/2025/08/plate.jpg") == 2025
    assert photo_season(f"{DFB}/2026/08/plate.jpg") == 2026


def test_an_undated_url_is_not_read_as_current():
    """The point is to promote a photo known to be from this year, not to
    demote everything that cannot be read."""
    assert photo_season("https://example.test/plate.jpg") is None
    assert photo_season(None) is None


def test_photos_this_project_published_are_recognised():
    assert is_hand_published(f"{PAGES}/abc.jpg")
    assert not is_hand_published(f"{DFB}/2025/08/plate.jpg")


# ---------------------------------------------------------------------------
# promotion
# ---------------------------------------------------------------------------


def test_a_current_season_crawl_photo_supersedes_a_curated_historical_one(db_session, dish, tmp_path):
    year = _year(db_session)
    _candidate(db_session, dish, "manual", f"{DFB}/2025/08/last-year.jpg", selected=True)
    _candidate(db_session, dish, "disney_food_blog", f"{DFB}/{year}/08/this-year.jpg", selected=False)

    path = _curated(tmp_path, [
        {"booth_name": "Shimmering Sips", "name": "Berry Mimosa", "image_url": f"{DFB}/2025/08/last-year.jpg"},
    ])
    report = promote_current_season_photos(db_session, path=path)

    assert report.total == 1
    db_session.refresh(dish)
    assert dish.image_url == f"{DFB}/{year}/08/this-year.jpg"
    # Both halves have to move: the file alone leaves the row still winning,
    # the row alone lets the next `epcot-fw manual` restage it.
    assert json.loads(path.read_text())["menu_items"] == []


def test_a_hand_attached_photo_is_never_promoted_away(db_session, dish, tmp_path):
    """A photo somebody published from the studio is an answer, not a
    stand-in, and outranks whatever the crawl turns up."""
    year = _year(db_session)
    _candidate(db_session, dish, "manual", f"{PAGES}/mine.jpg", selected=True)
    _candidate(db_session, dish, "disney_food_blog", f"{DFB}/{year}/08/this-year.jpg", selected=False)

    path = _curated(tmp_path, [
        {"booth_name": "Shimmering Sips", "name": "Berry Mimosa", "image_url": f"{PAGES}/mine.jpg"},
    ])
    report = promote_current_season_photos(db_session, path=path)

    assert report.total == 0
    assert report.kept_hand_attached == ["Berry Mimosa"]
    db_session.refresh(dish)
    assert dish.image_url == f"{PAGES}/mine.jpg"
    assert json.loads(path.read_text())["menu_items"][0]["image_url"] == f"{PAGES}/mine.jpg"


def test_nothing_moves_without_a_current_season_replacement(db_session, dish, tmp_path):
    _candidate(db_session, dish, "manual", f"{DFB}/2025/08/last-year.jpg", selected=True)
    _candidate(db_session, dish, "disney_food_blog", f"{DFB}/2024/08/older-still.jpg", selected=False)

    path = _curated(tmp_path, [
        {"booth_name": "Shimmering Sips", "name": "Berry Mimosa", "image_url": f"{DFB}/2025/08/last-year.jpg"},
    ])
    assert promote_current_season_photos(db_session, path=path).total == 0
    db_session.refresh(dish)
    assert dish.image_url == f"{DFB}/2025/08/last-year.jpg"


def test_a_curated_photo_already_from_this_season_is_left_alone(db_session, dish, tmp_path):
    year = _year(db_session)
    _candidate(db_session, dish, "manual", f"{DFB}/{year}/08/curated-current.jpg", selected=True)
    _candidate(db_session, dish, "disney_food_blog", f"{DFB}/{year}/08/crawled.jpg", selected=False)

    path = _curated(tmp_path, [
        {"booth_name": "Shimmering Sips", "name": "Berry Mimosa", "image_url": f"{DFB}/{year}/08/curated-current.jpg"},
    ])
    assert promote_current_season_photos(db_session, path=path).total == 0


def test_a_dry_run_reports_without_touching_anything(db_session, dish, tmp_path):
    year = _year(db_session)
    _candidate(db_session, dish, "manual", f"{DFB}/2025/08/last-year.jpg", selected=True)
    _candidate(db_session, dish, "disney_food_blog", f"{DFB}/{year}/08/this-year.jpg", selected=False)

    path = _curated(tmp_path, [
        {"booth_name": "Shimmering Sips", "name": "Berry Mimosa", "image_url": f"{DFB}/2025/08/last-year.jpg"},
    ])
    before = path.read_text()
    report = promote_current_season_photos(db_session, path=path, dry_run=True)

    assert report.total == 1
    assert path.read_text() == before
    db_session.refresh(dish)
    assert dish.image_url == f"{DFB}/2025/08/last-year.jpg"


def test_other_curated_fields_and_the_readme_survive(db_session, dish, tmp_path):
    """Clearing a photo must not take a price correction with it."""
    year = _year(db_session)
    _candidate(db_session, dish, "manual", f"{DFB}/2025/08/last-year.jpg", selected=True)
    _candidate(db_session, dish, "disney_food_blog", f"{DFB}/{year}/08/this-year.jpg", selected=False)

    path = _curated(tmp_path, [
        {"booth_name": "Shimmering Sips", "name": "Berry Mimosa",
         "image_url": f"{DFB}/2025/08/last-year.jpg", "price_usd": 9.5},
        {"booth_name": "Italy", "name": "Tiramisu", "image_url": f"{DFB}/2025/08/tiramisu.jpg"},
    ])
    promote_current_season_photos(db_session, path=path)

    payload = json.loads(path.read_text())
    assert payload["_README"] == ["keep me"]
    entries = {(e["booth_name"], e["name"]): e for e in payload["menu_items"]}
    assert entries[("Shimmering Sips", "Berry Mimosa")]["price_usd"] == 9.5
    assert "image_url" not in entries[("Shimmering Sips", "Berry Mimosa")]
    # An untouched dish keeps its staged photo.
    assert entries[("Italy", "Tiramisu")]["image_url"] == f"{DFB}/2025/08/tiramisu.jpg"


def test_every_staging_of_the_same_old_photo_goes_in_one_pass(db_session, dish, tmp_path):
    """The curated file is restaged whenever it changes and each staging
    leaves its own provenance row - most dishes here carry three. Clearing
    only the selected one promotes the next identical row into its place, so
    the same dish reappears as a promotion run after run."""
    year = _year(db_session)
    for _ in range(3):
        _candidate(db_session, dish, "manual", f"{DFB}/2025/08/last-year.jpg", selected=False)
    db_session.scalars(
        select(EntityFieldProvenance).where(EntityFieldProvenance.canonical_id == dish.id)
    ).first().is_selected = True
    dish.image_url = f"{DFB}/2025/08/last-year.jpg"
    db_session.flush()
    _candidate(db_session, dish, "disney_food_blog", f"{DFB}/{year}/08/this-year.jpg", selected=False)

    path = _curated(tmp_path, [
        {"booth_name": "Shimmering Sips", "name": "Berry Mimosa", "image_url": f"{DFB}/2025/08/last-year.jpg"},
    ])
    assert promote_current_season_photos(db_session, path=path).total == 1
    db_session.refresh(dish)
    assert dish.image_url == f"{DFB}/{year}/08/this-year.jpg"

    # Nothing left to do: a second run is a no-op, not a repeat.
    assert promote_current_season_photos(db_session, path=path).total == 0
    db_session.refresh(dish)
    assert dish.image_url == f"{DFB}/{year}/08/this-year.jpg"


def test_an_unflagged_candidate_is_still_recognised_as_the_one_winning(db_session, dish, tmp_path):
    """is_selected is not reliable - most dishes in the real database carry a
    row holding exactly the served URL and still flagged unselected. Trusting
    it meant skipping those dishes forever."""
    year = _year(db_session)
    stale = _candidate(db_session, dish, "manual", f"{DFB}/2025/08/last-year.jpg", selected=False)
    _candidate(db_session, dish, "disney_food_blog", f"{DFB}/{year}/08/this-year.jpg", selected=False)
    # The dish is serving the curated photo; nothing is flagged.
    dish.image_url = f"{DFB}/2025/08/last-year.jpg"
    db_session.flush()
    assert not stale.is_selected

    path = _curated(tmp_path, [
        {"booth_name": "Shimmering Sips", "name": "Berry Mimosa", "image_url": f"{DFB}/2025/08/last-year.jpg"},
    ])
    assert promote_current_season_photos(db_session, path=path).total == 1
    db_session.refresh(dish)
    assert dish.image_url == f"{DFB}/{year}/08/this-year.jpg"


def test_an_inactive_dish_is_not_touched(db_session, dish, tmp_path):
    year = _year(db_session)
    dish.is_active = False
    db_session.flush()
    _candidate(db_session, dish, "manual", f"{DFB}/2025/08/last-year.jpg", selected=True)
    _candidate(db_session, dish, "disney_food_blog", f"{DFB}/{year}/08/this-year.jpg", selected=False)

    path = _curated(tmp_path, [
        {"booth_name": "Shimmering Sips", "name": "Berry Mimosa", "image_url": f"{DFB}/2025/08/last-year.jpg"},
    ])
    assert promote_current_season_photos(db_session, path=path).total == 0
