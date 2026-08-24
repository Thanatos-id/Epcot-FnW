"""Attaching a historical dish photo to this year's menu.

_historical_dish_photos() (the network-fetching half) is monkeypatched out
in every test here - these exercise the matching and write-out logic, which
is where the actual safety rules live: only a confident, currently-active
match gets a photo, a booth photo is never possible because Booth has no
field to write one into here, and nothing already pictured gets clobbered.
"""

import json

import pytest
from sqlalchemy import select

from epcot_fw.db.models import Booth, MenuItem
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.pipeline import image_backfill as backfill_mod
from epcot_fw.pipeline.image_backfill import backfill_dish_images
from epcot_fw.pipeline.manual import stage_manual_overrides
from epcot_fw.pipeline.resolve_pipeline import run_resolve

from ._helpers import ingest


def _photo(booth_name: str, caption: str, url: str = "https://cdn.test/img.jpg") -> ExtractedRecordDTO:
    return ExtractedRecordDTO(
        entity_type="menu_item",
        natural_key_hint=caption.lower(),
        payload={"booth_name": booth_name, "name": caption, "image_url": url},
    )


def _stub_photos(monkeypatch, dated_records, *, fetched=1):
    """Replace the network-fetching half with canned (year, DTO) pairs."""

    def _fake(adapter, years):
        return list(dated_records), fetched

    monkeypatch.setattr(backfill_mod, "_historical_dish_photos", _fake)


def _seed_menu(db_session, festival_id, booth="Germany", dish="Kirschwasser Torte"):
    ingest(
        db_session,
        [
            ExtractedRecordDTO(
                entity_type="booth",
                natural_key_hint=booth.lower(),
                payload={"name": booth, "category": "global_marketplace"},
            ),
            ExtractedRecordDTO(
                entity_type="menu_item",
                natural_key_hint=dish.lower(),
                payload={"booth_name": booth, "name": dish, "category": "food"},
            ),
        ],
        "disney_food_blog",
        festival_id,
        url="https://example.test/hub-2026",
    )
    item = db_session.scalars(select(MenuItem).where(MenuItem.canonical_name == dish)).one()
    return item


def test_a_dish_still_on_the_menu_gets_its_historical_photo(db_session, tmp_path, monkeypatch):
    festival_id = db_session.info["festival_id"]
    _seed_menu(db_session, festival_id)
    _stub_photos(monkeypatch, [(2025, _photo("Germany", "Kirschwasser Torte"))])

    path = tmp_path / "menu_items.json"
    report = backfill_dish_images(db_session, years=5, path=path)

    assert len(report.matched) == 1
    match = report.matched[0]
    assert match.booth_name == "Germany"
    assert match.item_name == "Kirschwasser Torte"
    assert match.source_year == 2025

    written = json.loads(path.read_text())
    assert written["menu_items"] == [
        {"booth_name": "Germany", "name": "Kirschwasser Torte", "image_url": "https://cdn.test/img.jpg"}
    ]


def test_a_dish_that_did_not_return_this_year_is_reported_not_invented(db_session, tmp_path, monkeypatch):
    festival_id = db_session.info["festival_id"]
    _seed_menu(db_session, festival_id, dish="Kirschwasser Torte")
    _stub_photos(
        monkeypatch,
        [(2023, _photo("Germany", "Bratwurst Platter with Sauerkraut and Warm Pretzel"))],
    )

    path = tmp_path / "menu_items.json"
    report = backfill_dish_images(db_session, years=5, path=path)

    assert report.matched == []
    assert len(report.skipped_no_item_match) == 1
    assert report.skipped_no_item_match[0].caption.startswith("Bratwurst")
    assert not path.exists(), "nothing to write means the file must not be created empty"
    assert db_session.scalars(select(MenuItem)).all()[0].image_url is None


def test_a_booth_not_on_this_years_menu_is_reported_not_invented(db_session, tmp_path, monkeypatch):
    festival_id = db_session.info["festival_id"]
    _seed_menu(db_session, festival_id, booth="Germany")
    _stub_photos(monkeypatch, [(2022, _photo("Norway", "Kringle"))])

    report = backfill_dish_images(db_session, years=5, path=tmp_path / "menu_items.json")

    assert report.matched == []
    assert len(report.skipped_no_booth_match) == 1
    assert report.skipped_no_booth_match[0].booth_name == "Norway"


def test_a_retired_booth_does_not_receive_a_photo(db_session, tmp_path, monkeypatch):
    """is_active gating: a booth that stopped running is not "this year's
    menu" just because the row still exists."""
    festival_id = db_session.info["festival_id"]
    _seed_menu(db_session, festival_id, booth="Discontinued Kiosk", dish="Old Special")
    db_session.execute(
        Booth.__table__.update().where(Booth.canonical_name == "Discontinued Kiosk").values(is_active=False)
    )
    db_session.flush()
    _stub_photos(monkeypatch, [(2024, _photo("Discontinued Kiosk", "Old Special"))])

    report = backfill_dish_images(db_session, years=5, path=tmp_path / "menu_items.json")

    assert report.matched == []
    assert len(report.skipped_no_booth_match) == 1


def test_the_most_recent_seasons_photo_wins(db_session, tmp_path, monkeypatch):
    festival_id = db_session.info["festival_id"]
    _seed_menu(db_session, festival_id)
    _stub_photos(
        monkeypatch,
        [
            (2021, _photo("Germany", "Kirschwasser Torte", url="https://cdn.test/2021.jpg")),
            (2024, _photo("Germany", "Kirschwasser Torte", url="https://cdn.test/2024.jpg")),
            (2022, _photo("Germany", "Kirschwasser Torte", url="https://cdn.test/2022.jpg")),
        ],
    )

    report = backfill_dish_images(db_session, years=5, path=tmp_path / "menu_items.json")

    assert len(report.matched) == 1
    assert report.matched[0].source_year == 2024
    assert report.matched[0].image_url == "https://cdn.test/2024.jpg"


def test_a_dish_already_pictured_in_the_database_is_left_alone(db_session, tmp_path, monkeypatch):
    festival_id = db_session.info["festival_id"]
    item = _seed_menu(db_session, festival_id)
    item.image_url = "https://cdn.test/already-there.jpg"
    db_session.flush()
    _stub_photos(monkeypatch, [(2023, _photo("Germany", "Kirschwasser Torte"))])

    report = backfill_dish_images(db_session, years=5, path=tmp_path / "menu_items.json")

    assert report.matched == []
    assert len(report.skipped_already_pictured) == 1
    assert db_session.get(MenuItem, item.id).image_url == "https://cdn.test/already-there.jpg"


def test_a_value_already_pending_in_the_curated_file_is_not_overwritten(db_session, tmp_path, monkeypatch):
    festival_id = db_session.info["festival_id"]
    _seed_menu(db_session, festival_id)
    path = tmp_path / "menu_items.json"
    path.write_text(
        json.dumps(
            {
                "_README": ["kept"],
                "menu_items": [
                    {
                        "booth_name": "Germany",
                        "name": "Kirschwasser Torte",
                        "image_url": "https://cdn.test/hand-picked.jpg",
                    }
                ],
            }
        )
    )
    _stub_photos(monkeypatch, [(2024, _photo("Germany", "Kirschwasser Torte", url="https://cdn.test/backfill.jpg"))])

    report = backfill_dish_images(db_session, years=5, path=path)

    assert len(report.matched) == 1, "still counted as a match for reporting purposes"
    written = json.loads(path.read_text())
    assert written["_README"] == ["kept"]
    assert written["menu_items"][0]["image_url"] == "https://cdn.test/hand-picked.jpg"


def test_dry_run_reports_without_writing_anything(db_session, tmp_path, monkeypatch):
    festival_id = db_session.info["festival_id"]
    _seed_menu(db_session, festival_id)
    _stub_photos(monkeypatch, [(2025, _photo("Germany", "Kirschwasser Torte"))])
    path = tmp_path / "menu_items.json"

    report = backfill_dish_images(db_session, years=5, path=path, dry_run=True)

    assert len(report.matched) == 1
    assert not path.exists()


def test_booth_image_url_is_never_touched(db_session, tmp_path, monkeypatch):
    """The one hard requirement: this tool photographs dishes, not booths."""
    festival_id = db_session.info["festival_id"]
    _seed_menu(db_session, festival_id)
    _stub_photos(monkeypatch, [(2025, _photo("Germany", "Kirschwasser Torte"))])

    backfill_dish_images(db_session, years=5, path=tmp_path / "menu_items.json")

    booth = db_session.scalars(select(Booth).where(Booth.canonical_name == "Germany")).one()
    assert booth.image_url is None


def test_a_close_but_not_exact_caption_still_matches(db_session, tmp_path, monkeypatch):
    """The matcher's ordinary auto-merge band, same as everywhere else in
    the pipeline - not a bespoke threshold for this tool."""
    festival_id = db_session.info["festival_id"]
    _seed_menu(db_session, festival_id, dish="Kirschwasser Torte")
    _stub_photos(monkeypatch, [(2023, _photo("Germany", "Kirschwasser  Torte"))])  # double space

    report = backfill_dish_images(db_session, years=5, path=tmp_path / "menu_items.json")

    assert len(report.matched) == 1


def test_a_full_run_applies_cleanly_through_manual(db_session, tmp_path, monkeypatch):
    """End to end: what the backfill writes is exactly what `epcot-fw manual`
    already knows how to stage and resolve."""
    festival_id = db_session.info["festival_id"]
    item = _seed_menu(db_session, festival_id)
    assert item.image_url is None
    _stub_photos(monkeypatch, [(2025, _photo("Germany", "Kirschwasser Torte"))])
    path = tmp_path / "menu_items.json"

    backfill_dish_images(db_session, years=5, path=path)
    staged = stage_manual_overrides(db_session, path=tmp_path / "no_booths.json", items_path=path)
    run_resolve(db_session, festival_id=festival_id)

    assert staged == 1
    assert db_session.get(MenuItem, item.id).image_url == "https://cdn.test/img.jpg"


# ---------------------------------------------------------------------------
# end to end: real fetch + parse path, only the network is mocked
# ---------------------------------------------------------------------------


HISTORICAL_HUB_HTML = """
<article>
<p><strong><a href="https://www.disneyfoodblog.com/the-alps-2025-epcot-food-and-wine-festival/">The Alps</a>
&lt;&#8211; CLICK TO SEE PHOTOS OF MENU ITEMS!</strong></p>
</article>
"""

HISTORICAL_DETAIL_HTML = """
<html><body><article>
  <h1>The Alps &#8212; 2025 EPCOT Food &amp; Wine Festival</h1>
  <figure><img src="https://www.disneyfoodblog.com/wp-content/uploads/2025/08/alps-booth.jpg" />
    <figcaption>The Alps Booth</figcaption></figure>
  <figure><img src="https://www.disneyfoodblog.com/wp-content/uploads/2025/08/raclette.jpg" />
    <figcaption>Warm Raclette Swiss Cheese</figcaption></figure>
</article></body></html>
"""


def test_a_real_fetch_and_parse_run_only_photographs_the_real_dish(db_session, tmp_path, monkeypatch):
    """Nothing is stubbed here except the network layer (via respx) - this
    drives historical_detail_seeds(), the real fetch, and the real
    _parse_booth_detail() captioned-image extractor.

    The detail page also carries a caption for the booth photo itself ("The
    Alps Booth") - proving the safety net holds even though the extractor
    can't tell a booth photo from a dish photo on its own: nothing is named
    that, so it lands below auto-merge confidence and is skipped, while the
    real dish still matches.
    """
    import httpx
    import respx

    from epcot_fw.fetch import rate_limiter
    from epcot_fw.sources.disney_food_blog import BASE_URL

    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)

    festival_id = db_session.info["festival_id"]
    item = _seed_menu(db_session, festival_id, booth="The Alps", dish="Warm Raclette Swiss Cheese")

    dated_hub = f"{BASE_URL}/2025-epcot-food-and-wine-festival-booths-menus-and-food-photos/"
    detail_url = f"{BASE_URL}/the-alps-2025-epcot-food-and-wine-festival/"

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(dated_hub).mock(return_value=httpx.Response(200, text=HISTORICAL_HUB_HTML))
        mock.get(detail_url).mock(return_value=httpx.Response(200, text=HISTORICAL_DETAIL_HTML))

        path = tmp_path / "menu_items.json"
        report = backfill_dish_images(db_session, years=1, path=path)

    assert report.photo_posts_fetched == 1
    assert report.captions_found == 2  # the booth photo counts as a caption found...

    assert len(report.matched) == 1  # ...but only the real dish confidently matches
    assert report.matched[0].item_name == "Warm Raclette Swiss Cheese"
    assert report.matched[0].image_url.endswith("raclette.jpg")

    assert any(s.caption == "The Alps Booth" for s in report.skipped_no_item_match)

    assert db_session.get(MenuItem, item.id).image_url is None  # not applied until `epcot-fw manual`
    written = json.loads(path.read_text())
    assert written["menu_items"][0]["image_url"].endswith("raclette.jpg")

    booth = db_session.scalars(select(Booth).where(Booth.canonical_name == "The Alps")).one()
    assert booth.image_url is None


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------


def test_a_caption_with_no_image_is_skipped(db_session, tmp_path, monkeypatch):
    """extract_captioned_images() never emits an uncaptioned image, but a
    caption with an empty/missing image_url is still worth guarding: there is
    nothing to attach."""
    festival_id = db_session.info["festival_id"]
    _seed_menu(db_session, festival_id)
    record = ExtractedRecordDTO(
        entity_type="menu_item",
        natural_key_hint="kirschwasser torte",
        payload={"booth_name": "Germany", "name": "Kirschwasser Torte", "image_url": None},
    )
    _stub_photos(monkeypatch, [(2025, record)])

    report = backfill_dish_images(db_session, years=5, path=tmp_path / "menu_items.json")

    assert report.matched == []


def test_raises_without_a_seeded_festival(db_session, tmp_path):
    from epcot_fw.db.models import Festival

    db_session.execute(Festival.__table__.delete())
    db_session.flush()

    with pytest.raises(RuntimeError, match="db seed"):
        backfill_dish_images(db_session, years=5, path=tmp_path / "menu_items.json")


def test_raises_without_the_disney_food_blog_source_row(db_session, tmp_path):
    from epcot_fw.db.models import Source

    db_session.execute(Source.__table__.delete().where(Source.key == "disney_food_blog"))
    db_session.flush()

    with pytest.raises(RuntimeError, match="disney_food_blog"):
        backfill_dish_images(db_session, years=5, path=tmp_path / "menu_items.json")


def test_a_year_whose_hub_errors_is_skipped_and_the_run_continues(monkeypatch):
    """historical_detail_seeds() itself already turns a 404 into [] - this
    covers the belt-and-suspenders case where discovery raises outright
    (a network hiccup, a robots.txt fetch failure) rather than returning
    cleanly, which must not take the whole multi-year run down with it."""
    from epcot_fw.pipeline.image_backfill import _historical_dish_photos
    from epcot_fw.sources.disney_food_blog import DisneyFoodBlogAdapter

    adapter = DisneyFoodBlogAdapter()

    def _boom(year):
        raise RuntimeError("network is down")

    monkeypatch.setattr(adapter, "historical_detail_seeds", _boom)

    records, fetched = _historical_dish_photos(adapter, [2025, 2024])

    assert records == []
    assert fetched == 0


def test_a_detail_page_that_fails_to_fetch_or_parse_is_skipped(monkeypatch):
    """Both defensive branches inside the per-seed loop: a fetch that raises,
    and a fetch that succeeds but yields a page adapter.parse() chokes on -
    neither should drop the other seeds in the same run."""
    import httpx
    import respx

    from epcot_fw.fetch import rate_limiter
    from epcot_fw.pipeline.image_backfill import _historical_dish_photos
    from epcot_fw.sources.base import SeedUrl
    from epcot_fw.sources.disney_food_blog import BASE_URL, DisneyFoodBlogAdapter

    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)

    adapter = DisneyFoodBlogAdapter()
    seeds = [
        SeedUrl(url=f"{BASE_URL}/unreachable-booth/", page_kind="booth_detail"),
        SeedUrl(url=f"{BASE_URL}/not-found-booth/", page_kind="booth_detail"),
        SeedUrl(url=f"{BASE_URL}/unparseable-booth/", page_kind="booth_detail"),
        SeedUrl(url=f"{BASE_URL}/good-booth/", page_kind="booth_detail"),
    ]
    monkeypatch.setattr(adapter, "historical_detail_seeds", lambda year: seeds)

    real_parse = adapter.parse

    def _flaky_parse(html, url, page_kind):
        if "unparseable" in url:
            raise ValueError("malformed page")
        return real_parse(html, url, page_kind)

    monkeypatch.setattr(adapter, "parse", _flaky_parse)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(f"{BASE_URL}/unreachable-booth/").mock(side_effect=httpx.ConnectError("refused"))
        mock.get(f"{BASE_URL}/not-found-booth/").mock(return_value=httpx.Response(404, text="nope"))
        mock.get(f"{BASE_URL}/unparseable-booth/").mock(return_value=httpx.Response(200, text="<html></html>"))
        mock.get(f"{BASE_URL}/good-booth/").mock(return_value=httpx.Response(200, text=HISTORICAL_DETAIL_HTML))

        records, fetched = _historical_dish_photos(adapter, [2025])

    # "fetched" counts a page that came back with a 2xx body, whether or not
    # it went on to parse cleanly - the unparseable page still counts here,
    # same as pipeline/crawl.py counts a page it fetched but failed to parse.
    # The unreachable page (connection error) and the 404 do not. None of
    # the three failures stop the run from reaching the good page.
    assert fetched == 2
    assert any(r.payload["name"] == "Warm Raclette Swiss Cheese" for _, r in records)
