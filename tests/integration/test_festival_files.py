"""Festivals researched into data/festivals/ rather than crawled.

Two promises are tested here. A changeset from one of these festivals goes
back into that festival's own files and never into data/manual/ - which is
where it would put Holidays dishes into Food & Wine. And the research files
that ship in the repo are clean enough for the Studio and, later, the app to
read without surprises.
"""

import base64
import json
import uuid

import pytest

from epcot_fw import festival_files
from epcot_fw.normalize.alcohol_kind import KINDS
from epcot_fw.pipeline.studio import ChangesetError, apply_changeset

KEY = "festival-of-the-holidays"
BASE_URL = "https://example.test/Epcot-FnW"
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n-bytes").decode()


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "festivals"
    directory = root / KEY
    directory.mkdir(parents=True)
    (directory / "festival.json").write_text(json.dumps({
        "key": KEY, "name": "Festival of the Holidays 2026", "start": "2026-11-27",
        "end": "2026-12-30", "summary": "First pass.", "stroll_label": "Cookie Stroll",
    }))
    (directory / "booths.json").write_text(json.dumps({"booths": [
        {"name": "Yukon Holiday Kitchen", "public_id": "b-yukon", "category": "holiday_kitchen",
         "location_description": "Canada pavilion", "latitude": 28.37, "longitude": -81.55,
         "location_precision": "anchored", "pinned_from": "Food & Wine 2026: Canada"},
        {"name": "Gone Kitchen", "public_id": "b-gone", "is_active": False},
    ]}))
    (directory / "menu_items.json").write_text(json.dumps({"menu_items": [
        {"booth_name": "Yukon Holiday Kitchen", "name": "Beef Bourguignon", "public_id": "i-beef",
         "description": "With crushed potatoes", "price_usd": 7.25, "category": "food",
         "dietary_tags": [], "flavor_tags": ["savory"], "alcohol_kind": None,
         "status": "2025-menu", "stroll": False},
        {"booth_name": "Yukon Holiday Kitchen", "name": "Maple Leaf Shortbread Cookie",
         "public_id": "i-cookie", "category": "food", "status": "confirmed-2026", "stroll": True},
        {"booth_name": "Yukon Holiday Kitchen", "name": "Retired Dish", "public_id": "i-old",
         "category": "food", "is_active": False},
        {"booth_name": "Gone Kitchen", "name": "Orphan", "public_id": "i-orphan", "category": "food"},
    ]}))
    manual = tmp_path / "manual"
    manual.mkdir()
    (manual / "menu_items.json").write_text(json.dumps({"menu_items": []}))
    (manual / "booth_locations.json").write_text(json.dumps({"booths": []}))
    return {"root": root, "dir": directory, "manual": manual, "tmp": tmp_path}


def _apply(ws, payload, **kw):
    path = ws["tmp"] / "changeset.json"
    path.write_text(json.dumps({"version": 1, **payload}))
    return apply_changeset(
        path,
        publish_dir=ws["tmp"] / "docs" / "dish-photos",
        base_url=BASE_URL,
        items_path=ws["manual"] / "menu_items.json",
        booths_path=ws["manual"] / "booth_locations.json",
        festivals_root=ws["root"],
        **kw,
    )


def _items(ws):
    return json.loads((ws["dir"] / "menu_items.json").read_text())["menu_items"]


def _booths(ws):
    return json.loads((ws["dir"] / "booths.json").read_text())["booths"]


def _manual_untouched(ws):
    assert json.loads((ws["manual"] / "menu_items.json").read_text()) == {"menu_items": []}
    assert json.loads((ws["manual"] / "booth_locations.json").read_text()) == {"booths": []}


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------


def test_the_files_read_as_a_snapshot_the_studio_already_understands(workspace):
    snap = festival_files.build_snapshot(KEY, workspace["root"])
    assert snap["festival"]["name"] == "Festival of the Holidays 2026"
    assert [b["name"] for b in snap["booths"]] == ["Yukon Holiday Kitchen"]
    booth = snap["booths"][0]
    assert booth["origin"] == "researched"
    assert booth["location_precision"] == "anchored"
    beef, cookie = booth["items"]
    assert beef["price"] == 7.25 and beef["flavor_tags"] == ["savory"]
    assert beef["badges"] == ["2025 menu"]
    assert cookie["badges"] == ["Confirmed 2026", "Cookie Stroll"]


def test_retired_rows_are_left_out_and_a_retired_booth_takes_its_dishes(workspace):
    snap = festival_files.build_snapshot(KEY, workspace["root"])
    names = [i["name"] for b in snap["booths"] for i in b["items"]]
    assert "Retired Dish" not in names
    assert "Orphan" not in names


def test_status_labels_read_for_any_year():
    assert festival_files.status_label("2026-menu") == "2026 menu"
    assert festival_files.status_label("likely-2027") == "Likely 2027"
    assert festival_files.status_label("confirmed-2026") == "Confirmed 2026"
    assert festival_files.status_label("someday") is None


def test_an_unknown_festival_key_is_refused():
    with pytest.raises(festival_files.FestivalDataError):
        festival_files.festival_dir("../manual")


# ---------------------------------------------------------------------------
# applying a changeset
# ---------------------------------------------------------------------------


def test_a_festival_changeset_edits_its_own_files_and_never_data_manual(workspace):
    report = _apply(workspace, {"festival": KEY, "menu_items": [
        {"booth_name": "Yukon Holiday Kitchen", "name": "Beef Bourguignon", "price_usd": 7.75},
    ]})
    assert report.festival == KEY
    assert _items(workspace)[0]["price_usd"] == 7.75
    _manual_untouched(workspace)


def test_a_rename_renames_the_row_in_place(workspace):
    _apply(workspace, {"festival": KEY, "menu_items": [
        {"booth_name": "Yukon Holiday Kitchen", "name": "Beef Bourguignon",
         "rename_to": "Bœuf Bourguignon"},
    ]})
    beef = next(i for i in _items(workspace) if i["public_id"] == "i-beef")
    assert beef["name"] == "Bœuf Bourguignon"
    assert "rename_to" not in beef


def test_added_rows_get_their_own_ids_and_a_curated_origin(workspace):
    _apply(workspace, {"festival": KEY,
        "booths": [{"name": "New Kitchen", "new": True, "location_description": "Japan"}],
        "menu_items": [{"booth_name": "New Kitchen", "name": "Mochi", "new": True,
                        "category": "food", "price_usd": 5}],
    })
    kitchen = next(b for b in _booths(workspace) if b["name"] == "New Kitchen")
    mochi = next(i for i in _items(workspace) if i["name"] == "Mochi")
    assert kitchen["origin"] == mochi["origin"] == "curated"
    uuid.UUID(kitchen["public_id"])
    uuid.UUID(mochi["public_id"])


def test_a_delete_retires_the_row_without_erasing_it(workspace):
    _apply(workspace, {"festival": KEY, "menu_items": [
        {"booth_name": "Yukon Holiday Kitchen", "name": "Beef Bourguignon", "is_active": False},
    ]})
    beef = next(i for i in _items(workspace) if i["public_id"] == "i-beef")
    assert beef["is_active"] is False
    names = [i["name"] for b in festival_files.build_snapshot(KEY, workspace["root"])["booths"]
             for i in b["items"]]
    assert "Beef Bourguignon" not in names


def test_a_dropped_pin_replaces_the_borrowed_one_and_its_note(workspace):
    _apply(workspace, {"festival": KEY, "booths": [
        {"name": "Yukon Holiday Kitchen", "latitude": 28.3717, "longitude": -81.5507,
         "location_precision": "mapped"},
    ]})
    yukon = _booths(workspace)[0]
    assert (yukon["latitude"], yukon["location_precision"]) == (28.3717, "mapped")
    assert "pinned_from" not in yukon


def test_a_photo_is_published_and_points_the_dish_at_it(workspace):
    report = _apply(workspace, {"festival": KEY, "menu_items": [
        {"booth_name": "Yukon Holiday Kitchen", "name": "Beef Bourguignon",
         "photo": {"id": "i-beef", "mime": "image/png", "data_base64": PNG}},
    ]})
    assert report.photos == ["i-beef.png"]
    assert (workspace["tmp"] / "docs" / "dish-photos" / "i-beef.png").exists()
    assert _items(workspace)[0]["image_url"] == f"{BASE_URL}/dish-photos/i-beef.png"


def test_what_cannot_be_matched_is_reported_not_invented(workspace):
    report = _apply(workspace, {"festival": KEY, "menu_items": [
        {"booth_name": "Yukon Holiday Kitchen", "name": "Never Heard Of It", "price_usd": 1},
        {"booth_name": "Nowhere", "name": "Ghost", "new": True, "category": "food"},
        {"booth_name": "Yukon Holiday Kitchen", "name": "Beef Bourguignon",
         "rename_to": "Maple Leaf Shortbread Cookie"},
    ]})
    assert len(report.skipped) == 3
    assert {i["name"] for i in _items(workspace)} >= {"Beef Bourguignon", "Maple Leaf Shortbread Cookie"}
    assert "Ghost" not in {i["name"] for i in _items(workspace)}


def test_a_dry_run_writes_nothing(workspace):
    before = (workspace["dir"] / "menu_items.json").read_text()
    _apply(workspace, {"festival": KEY, "menu_items": [
        {"booth_name": "Yukon Holiday Kitchen", "name": "Beef Bourguignon", "price_usd": 99},
    ]}, dry_run=True)
    assert (workspace["dir"] / "menu_items.json").read_text() == before


def test_a_festival_this_build_does_not_know_is_refused(workspace):
    with pytest.raises(ChangesetError, match="epcot-candlelight"):
        _apply(workspace, {"festival": "epcot-candlelight", "menu_items": []})


def test_a_changeset_naming_the_database_festival_takes_the_ordinary_path(workspace):
    report = _apply(workspace, {"festival": "food-and-wine", "menu_items": [
        {"booth_name": "Canada", "name": "Poutine", "price_usd": 9},
    ]})
    assert report.festival is None
    assert json.loads((workspace["manual"] / "menu_items.json").read_text())["menu_items"]


# ---------------------------------------------------------------------------
# the research that ships in the repo
# ---------------------------------------------------------------------------

EPCOT_BOX = (28.364, 28.377, -81.556, -81.543)
SHIPPED_KEYS = festival_files.available()


def _shipped(name, key, festival=KEY):
    return json.loads((festival_files.festival_dir(festival) / name).read_text())[key]


def test_every_file_backed_festival_ships_research():
    assert set(SHIPPED_KEYS) == set(festival_files.FILE_BACKED)


@pytest.mark.parametrize("festival", SHIPPED_KEYS)
def test_the_shipped_research_is_internally_consistent(festival):
    booths = _shipped("booths.json", "booths", festival)
    items = _shipped("menu_items.json", "menu_items", festival)
    meta = festival_files.load_meta(festival)
    sources = meta["sources"]
    assert meta.get("start") and meta.get("end") and meta.get("summary") and meta.get("stroll_label")
    booth_names = [b["name"] for b in booths]
    assert len(booth_names) == len(set(booth_names))
    ids = [r["public_id"] for r in booths + items]
    assert len(ids) == len(set(ids))
    pairs = [(i["booth_name"], i["name"]) for i in items]
    assert len(pairs) == len(set(pairs))
    for item in items:
        label = f"{item['booth_name']} / {item['name']}"
        assert item["booth_name"] in booth_names, label
        assert item["category"] in festival_files.MENU_ITEM_CATEGORIES, label
        # A dish added by hand in the Studio has no research status: a person
        # typed it in from the menu. One that has a status must be readable.
        if item.get("status") is not None:
            assert festival_files.status_label(item["status"]), label
        assert set(item.get("sources") or []) <= set(sources), label
        if item["category"] == "alcoholic_beverage":
            assert "contains_alcohol" in (item.get("dietary_tags") or []), label
            assert item["alcohol_kind"] in KINDS | {None}, label
        else:
            assert item["alcohol_kind"] is None, label
            assert "contains_alcohol" not in (item.get("dietary_tags") or []), label
    for booth in booths:
        if booth.get("latitude") is not None:
            lo_lat, hi_lat, lo_lon, hi_lon = EPCOT_BOX
            assert lo_lat < booth["latitude"] < hi_lat and lo_lon < booth["longitude"] < hi_lon, booth["name"]
            assert booth["location_precision"] in {"anchored", "mapped", "surveyed"}, booth["name"]


@pytest.mark.parametrize("festival", SHIPPED_KEYS)
def test_nothing_in_the_research_claims_to_be_new_this_year_yet(festival):
    """Last edition's "(New)" marks say nothing about the next, and the app
    filters on this. Only a festival whose menu is its own year's official one
    (menu_season == year) may carry them."""
    meta = festival_files.load_meta(festival)
    claimed = [i for i in _shipped("menu_items.json", "menu_items", festival) if i.get("is_new_this_year")]
    if meta.get("menu_season") == meta.get("year"):
        return
    assert not claimed


@pytest.mark.parametrize("festival", SHIPPED_KEYS)
def test_every_shipped_photo_says_where_it_came_from(festival):
    for item in _shipped("menu_items.json", "menu_items", festival):
        if item.get("image_url"):
            source = item.get("image_source") or {}
            assert source.get("credit") and source.get("page_url") and source.get("season"), item["name"]


def test_a_dish_with_no_price_says_why_until_it_has_one(workspace):
    items_path = workspace["dir"] / "menu_items.json"
    payload = json.loads(items_path.read_text())
    payload["menu_items"][0].update({"price_usd": None, "price_note": "Coming soon"})
    items_path.write_text(json.dumps(payload))
    beef = next(i for b in festival_files.build_snapshot(KEY, workspace["root"])["booths"] for i in b["items"]
                if i["name"] == "Beef Bourguignon")
    assert beef["price"] is None and beef["price_note"] == "Coming soon"
    # Once a price is entered the note says nothing more.
    _apply(workspace, {"festival": KEY, "menu_items": [
        {"booth_name": "Yukon Holiday Kitchen", "name": "Beef Bourguignon", "price_usd": 7.5}]})
    beef = next(i for b in festival_files.build_snapshot(KEY, workspace["root"])["booths"] for i in b["items"]
                if i["name"] == "Beef Bourguignon")
    assert beef["price"] == 7.5 and "price_note" not in beef


def test_the_feed_carries_price_note_only_where_it_applies(workspace):
    from epcot_fw import client_feed
    items_path = workspace["dir"] / "menu_items.json"
    payload = json.loads(items_path.read_text())
    payload["menu_items"][0].update({"price_usd": None, "price_note": "Coming soon"})
    items_path.write_text(json.dumps(payload))
    feed = client_feed.build_file_snapshot(KEY, workspace["root"])
    by_name = {i["canonical_name"]: i for i in feed["menu_items"]}
    assert by_name["Beef Bourguignon"]["price_usd"] is None
    assert by_name["Beef Bourguignon"]["price_note"] == "Coming soon"
    assert "price_note" not in by_name["Maple Leaf Shortbread Cookie"]


def test_every_shipped_dish_without_a_price_says_coming_soon_or_nothing():
    for festival in SHIPPED_KEYS:
        for item in _shipped("menu_items.json", "menu_items", festival):
            if item.get("price_note"):
                assert item.get("price_usd") is None, (festival, item["name"])


def test_a_price_entered_in_the_studio_clears_coming_soon_in_the_file(workspace):
    items_path = workspace["dir"] / "menu_items.json"
    payload = json.loads(items_path.read_text())
    payload["menu_items"][0].update({"price_usd": None, "price_note": "Coming soon"})
    items_path.write_text(json.dumps(payload))
    name, booth = payload["menu_items"][0]["name"], payload["menu_items"][0]["booth_name"]
    _apply(workspace, {"festival": KEY, "menu_items": [{"booth_name": booth, "name": name, "price_usd": 6.29}]})
    row = next(i for i in json.loads(items_path.read_text())["menu_items"] if i["name"] == name)
    assert row["price_usd"] == 6.29 and "price_note" not in row


def test_a_dish_added_in_the_studio_has_the_shape_of_a_researched_one(workspace):
    """A new wine from the Studio carries only a name, a category and a
    price; it is filed with every key a researched dish has, and with the
    alcohol tag the app's drink filter reads."""
    booth = json.loads((workspace["dir"] / "booths.json").read_text())["booths"][0]["name"]
    _apply(workspace, {"festival": KEY, "menu_items": [
        {"booth_name": booth, "name": "Seasonal Red Wine", "new": True, "category": "alcoholic_beverage", "price_usd": 6.5}]})
    row = next(i for i in json.loads((workspace["dir"] / "menu_items.json").read_text())["menu_items"]
               if i["name"] == "Seasonal Red Wine")
    assert row["origin"] == "curated" and "status" not in row
    assert row["dietary_tags"] == ["contains_alcohol"] and row["alcohol_kind"] is None
    assert row["is_new_this_year"] is False and row["sources"] == [] and row["flavor_tags"] == []
    # Marked non-alcoholic later, the tag and the kind go with it.
    _apply(workspace, {"festival": KEY, "menu_items": [
        {"booth_name": booth, "name": "Seasonal Red Wine", "category": "non_alcoholic_beverage"}]})
    row = next(i for i in json.loads((workspace["dir"] / "menu_items.json").read_text())["menu_items"]
               if i["name"] == "Seasonal Red Wine")
    assert row["dietary_tags"] == [] and row["alcohol_kind"] is None
