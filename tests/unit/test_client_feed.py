"""The multi-festival client feed, as published.

Like test_client_snapshot.py, these guard the committed files rather than
the code that writes them: once a build that reads them is installed, their
shape cannot be taken back.
"""

import datetime
import json
import shutil
from pathlib import Path

import pytest

from epcot_fw import client_feed, festival_files
from epcot_fw.api.schemas import SnapshotOut

REPO = Path(__file__).parent.parent.parent
CLIENT_DIR = REPO / "docs/v1"
INDEX = CLIENT_DIR / "festivals.json"


@pytest.fixture(scope="module")
def index() -> dict:
    assert INDEX.exists(), "run `epcot-fw festival feed` and commit docs/v1/"
    return json.loads(INDEX.read_text())


@pytest.fixture(scope="module")
def snapshots(index) -> dict[str, dict]:
    return {
        entry["key"]: json.loads((CLIENT_DIR / entry["snapshot"]).read_text())
        for entry in index["festivals"]
    }


def test_the_index_lists_all_four_festivals_in_calendar_order(index):
    assert [f["key"] for f in index["festivals"]] == list(client_feed.FESTIVAL_ORDER)
    assert index["schema_version"] == client_feed.SCHEMA_VERSION
    assert "min_app_version" in index


def test_every_index_row_has_what_the_picker_shows(index):
    for entry in index["festivals"]:
        for field in ("short_name", "typical_dates", "start_date", "end_date", "menu_season", "year"):
            assert entry[field], (entry["key"], field)
        assert entry["status"] in {"upcoming", "running", "ended"}
        assert entry["menu_season"] <= entry["year"]


def test_every_snapshot_is_the_contract_the_single_feed_serves(snapshots):
    """One decoder reads all of them - the app does not have a second."""
    for key, payload in snapshots.items():
        SnapshotOut.model_validate(payload)
        assert payload["festival"]["key"] == key


def test_the_index_and_each_snapshot_agree(index, snapshots):
    for entry in index["festivals"]:
        festival = snapshots[entry["key"]]["festival"]
        assert snapshots[entry["key"]]["data_updated_at"] == entry["data_updated_at"]
        for field in ("name", "short_name", "start_date", "end_date", "menu_season", "typical_dates"):
            assert festival[field] == entry[field], (entry["key"], field)


def test_public_ids_are_present_and_unique_across_every_festival(snapshots):
    """A favourite is saved by public_id alone, with no festival beside it, so
    one id must never name a dish in two festivals."""
    ids = [
        row["public_id"]
        for payload in snapshots.values()
        for row in payload["booths"] + payload["menu_items"]
    ]
    assert all(ids)
    assert len(ids) == len(set(ids))


def test_every_item_belongs_to_a_booth_in_the_same_payload(snapshots):
    for key, payload in snapshots.items():
        booth_ids = {b["id"] for b in payload["booths"]}
        orphans = [i["canonical_name"] for i in payload["menu_items"] if i["booth_id"] not in booth_ids]
        assert orphans == [], key


def test_numbers_travel_as_strings_like_the_database_festival(snapshots):
    """The app decodes price and coordinates as strings; a bare float would
    fail the whole payload."""
    for payload in snapshots.values():
        for item in payload["menu_items"]:
            assert item["price_usd"] is None or isinstance(item["price_usd"], str)
        for booth in payload["booths"]:
            assert booth["latitude"] is None or isinstance(booth["latitude"], str)
            assert booth["longitude"] is None or isinstance(booth["longitude"], str)


def test_a_photo_always_has_a_credit_with_a_link(snapshots):
    for payload in snapshots.values():
        for item in payload["menu_items"]:
            if item["image_url"]:
                assert item["image_source"] and item["image_source"]["url"], item["canonical_name"]


def test_food_and_wine_is_the_published_snapshot_with_three_fields_added(snapshots):
    published = json.loads((CLIENT_DIR / "snapshot.json").read_text())
    tagged = snapshots[festival_files.DATABASE_FESTIVAL_KEY]
    assert tagged["booths"] == published["booths"]
    assert tagged["menu_items"] == published["menu_items"]
    assert tagged["data_updated_at"] == published["data_updated_at"]
    added = set(tagged["festival"]) - set(published["festival"])
    assert added == {"key", "short_name", "typical_dates", "menu_season"}


def test_the_published_files_are_what_the_builder_writes_today(tmp_path, snapshots):
    """An edit to data/festivals/ that was never republished fails here."""
    for key in festival_files.FILE_BACKED:
        built = client_feed.build_file_snapshot(key)
        published = dict(snapshots[key])
        published.pop("data_updated_at")
        # Status follows the calendar, so it may have moved since publishing.
        built["festival"].pop("status")
        published["festival"] = {k: v for k, v in published["festival"].items() if k != "status"}
        assert built == published, f"{key}: run `epcot-fw festival feed`"


def test_an_unchanged_festival_keeps_its_stamp_and_its_bytes(tmp_path):
    shutil.copy(CLIENT_DIR / "snapshot.json", tmp_path / "snapshot.json")
    first = datetime.datetime(2026, 11, 10, tzinfo=datetime.UTC)
    later = datetime.datetime(2026, 11, 12, tzinfo=datetime.UTC)

    client_feed.write_feed(tmp_path, now=first)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    client_feed.write_feed(tmp_path, now=later)

    assert {p: p.read_bytes() for p in tmp_path.rglob("*.json")} == before


def test_a_changed_festival_gets_a_new_stamp(tmp_path):
    root = tmp_path / "festivals"
    shutil.copytree(festival_files.FESTIVALS_DIR, root)
    out = tmp_path / "v1"
    out.mkdir()
    first = datetime.datetime(2026, 11, 10, tzinfo=datetime.UTC)
    later = datetime.datetime(2026, 11, 12, tzinfo=datetime.UTC)
    client_feed.write_feed(out, root=root, now=first)

    path = root / "festival-of-the-holidays" / "menu_items.json"
    data = json.loads(path.read_text())
    data["menu_items"][0]["price_usd"] = 99.0
    path.write_text(json.dumps(data))
    entries = {e["key"]: e for e in client_feed.write_feed(out, root=root, now=later)}

    assert entries["festival-of-the-holidays"]["data_updated_at"] == later.isoformat()
    assert entries["flower-and-garden"]["data_updated_at"] == first.isoformat()


def test_researched_festivals_slug_names_the_way_the_database_does(snapshots):
    """The app picks a booth's flag and icon by slug. The researched festivals
    use the database's own slugifier, quirks included ("Café" becomes "caf"),
    so the app has one spelling per venue to know about."""
    for key in festival_files.FILE_BACKED:
        slugs = {b["canonical_name"]: b["slug"] for b in snapshots[key]["booths"]}
        assert slugs["Tangierine Café: Flavors of the Medina"] == "tangierine-caf-flavors-of-the-medina"
        assert slugs["Swirled Showcase"] == "swirled-showcase"
