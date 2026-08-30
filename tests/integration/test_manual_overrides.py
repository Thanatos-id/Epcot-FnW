"""Hand-curated booth facts have to reach the canonical row, beat whatever a
crawl said, and survive the next crawl saying it again."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from epcot_fw.db.models import (
    Booth,
    EntityFieldProvenance,
    ExtractedRecord,
    MenuItem,
    Source,
)
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.pipeline.manual import (
    load_booth_overrides,
    load_menu_item_overrides,
    stage_manual_overrides,
)
from epcot_fw.pipeline.resolve_pipeline import run_resolve

from ._helpers import ingest

ALPS_LAT, ALPS_LON = 28.370536, -81.549472


@pytest.fixture()
def overrides_file(tmp_path):
    def _write(booths):
        path = tmp_path / "booth_locations.json"
        path.write_text(json.dumps({"booths": booths}))
        return path

    return _write


@pytest.fixture()
def no_curated_items(tmp_path):
    """A menu-item overrides path that doesn't exist, so stage_manual_overrides
    stages nothing from it - these tests exercise the *booth* file only, and
    without this they'd fall through to DEFAULT_ITEMS_PATH, i.e. the repo's
    real data/manual/menu_items.json, which has real curated entries of its
    own that have nothing to do with what any given test here is asserting."""
    return tmp_path / "no-menu-items.json"


def _seed_booth(db_session, festival_id, name="The Alps"):
    ingest(
        db_session,
        [
            ExtractedRecordDTO(
                entity_type="booth",
                natural_key_hint=name.lower(),
                payload={"name": name, "category": "global_marketplace"},
            )
        ],
        "allears",
        festival_id,
        url="https://example.test/hub",
    )
    return db_session.scalars(select(Booth).where(Booth.canonical_name == name)).one()


# ---------------------------------------------------------------------------
# file parsing
# ---------------------------------------------------------------------------


SHIPPED = Path(__file__).parent.parent.parent / "data/manual/booth_locations.json"

# World Showcase, generously. Anything outside this is a transposed pair or a
# dropped minus sign - the classic coordinate bug, and one that looks entirely
# plausible in a diff.
EPCOT_BOX = {"lat": (28.36, 28.38), "lon": (-81.56, -81.54)}


def test_readme_block_in_the_shipped_file_is_not_mistaken_for_data():
    payload = json.loads(SHIPPED.read_text())
    assert "_README" in payload, "keep the in-file usage notes"
    assert all(entry["name"] != "_README" for entry in load_booth_overrides(SHIPPED))


# What a coordinate can honestly claim without anyone having stood at the
# booth: a pavilion stand-in, or a pin dropped by eye on satellite imagery.
# `surveyed` is a GPS fix taken in the park and cannot be produced at a desk,
# so nothing arrives in this file carrying it - and a value that overclaims
# its own precision is worse than no value, because a client is expected to
# stop qualifying the distance it shows.
DESK_GRADES = {"anchored", "mapped"}


def test_every_shipped_coordinate_is_complete_and_honestly_graded():
    entries = load_booth_overrides(SHIPPED)
    assert entries, "the curated coordinates should ship with the repo"
    for entry in entries:
        assert entry["latitude"] is not None and entry["longitude"] is not None
        assert entry["location_precision"] in DESK_GRADES, (
            f"{entry['name']}: {entry['location_precision']!r} is not a grade anyone "
            f"can produce without walking the park"
        )


def test_no_shipped_coordinate_has_landed_outside_the_park():
    for entry in load_booth_overrides(SHIPPED):
        low, high = EPCOT_BOX["lat"]
        assert low < entry["latitude"] < high, f"{entry['name']} latitude"
        low, high = EPCOT_BOX["lon"]
        assert low < entry["longitude"] < high, f"{entry['name']} longitude"


def test_entries_without_a_name_are_skipped(overrides_file):
    path = overrides_file([{"latitude": 1.0}, {"name": "  ", "latitude": 2.0}, {"name": "Ok"}])
    assert [e["name"] for e in load_booth_overrides(path)] == ["Ok"]


def test_only_known_fields_are_carried_through(overrides_file):
    path = overrides_file([{"name": "A", "latitude": 1.0, "nonsense": "x"}])
    assert load_booth_overrides(path) == [{"name": "A", "latitude": 1.0}]


def test_absent_fields_are_omitted_rather_than_nulled(overrides_file):
    """A null would still be a candidate value; omitting keeps the field open
    for a crawled source to fill later."""
    path = overrides_file([{"name": "A", "latitude": None, "longitude": 2.0}])
    assert load_booth_overrides(path) == [{"name": "A", "longitude": 2.0}]


def test_zero_is_kept_because_it_is_a_real_coordinate(overrides_file):
    path = overrides_file([{"name": "Null Island", "latitude": 0.0, "longitude": 0.0}])
    assert load_booth_overrides(path) == [
        {"name": "Null Island", "latitude": 0.0, "longitude": 0.0}
    ]


def test_missing_file_is_not_an_error(tmp_path):
    assert load_booth_overrides(tmp_path / "nope.json") == []


# ---------------------------------------------------------------------------
# staging + resolution
# ---------------------------------------------------------------------------


def test_curated_coordinates_land_on_the_matching_booth(db_session, overrides_file, no_curated_items):
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id)
    assert booth.latitude is None

    path = overrides_file(
        [{"name": "The Alps", "latitude": ALPS_LAT, "longitude": ALPS_LON,
          "location_description": "World Showcase, near Germany"}]
    )
    assert stage_manual_overrides(db_session, path=path, items_path=no_curated_items) == 1
    run_resolve(db_session, festival_id=festival_id)

    refreshed = db_session.get(Booth, booth.id)
    assert refreshed.latitude == pytest.approx(Decimal(str(ALPS_LAT)))
    assert refreshed.longitude == pytest.approx(Decimal(str(ALPS_LON)))
    assert refreshed.location_description == "World Showcase, near Germany"


def test_precision_travels_with_the_coordinate(db_session, overrides_file, no_curated_items):
    """A coordinate without its grade is worse than useless: the client can't
    tell a metre-accurate survey from a pavilion standing in for a kiosk 40 m
    away, so it either overstates every distance or distrusts all of them."""
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id)

    path = overrides_file(
        [{"name": "The Alps", "latitude": ALPS_LAT, "longitude": ALPS_LON,
          "location_precision": "anchored"}]
    )
    stage_manual_overrides(db_session, path=path, items_path=no_curated_items)
    run_resolve(db_session, festival_id=festival_id)
    assert db_session.get(Booth, booth.id).location_precision == "anchored"


def test_a_survey_supersedes_the_anchor_it_replaces(db_session, overrides_file, no_curated_items):
    """The anchors ship as a floor. Walking up to the booth has to be able to
    overwrite one, precision included, or the survey is pointless."""
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id)

    anchored = overrides_file(
        [{"name": "The Alps", "latitude": 28.368060, "longitude": -81.546940,
          "location_precision": "anchored"}]
    )
    stage_manual_overrides(db_session, path=anchored, items_path=no_curated_items)
    run_resolve(db_session, festival_id=festival_id)

    surveyed = overrides_file(
        [{"name": "The Alps", "latitude": ALPS_LAT, "longitude": ALPS_LON,
          "location_precision": "surveyed"}]
    )
    stage_manual_overrides(db_session, path=surveyed, items_path=no_curated_items)
    run_resolve(db_session, festival_id=festival_id)

    refreshed = db_session.get(Booth, booth.id)
    assert refreshed.location_precision == "surveyed"
    assert refreshed.latitude == pytest.approx(Decimal(str(ALPS_LAT)))


def test_a_name_that_is_close_but_not_exact_still_matches(db_session, overrides_file, no_curated_items):
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id, name="Refreshment Port")

    path = overrides_file([{"name": "Refreshment Port (NEW)", "latitude": ALPS_LAT}])
    stage_manual_overrides(db_session, path=path, items_path=no_curated_items)
    run_resolve(db_session, festival_id=festival_id)

    assert db_session.get(Booth, booth.id).latitude is not None


def test_curated_value_outranks_a_crawled_one(db_session, overrides_file, no_curated_items):
    """A crawled source supplying the same field must not win against
    curation, whichever order they arrive in."""
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id)

    path = overrides_file([{"name": "The Alps", "location_description": "Curated position"}])
    stage_manual_overrides(db_session, path=path, items_path=no_curated_items)
    run_resolve(db_session, festival_id=festival_id)
    assert db_session.get(Booth, booth.id).location_description == "Curated position"

    ingest(
        db_session,
        [
            ExtractedRecordDTO(
                entity_type="booth",
                natural_key_hint="the alps",
                payload={"name": "The Alps", "location_description": "Blog guess"},
            )
        ],
        "disney_food_blog",
        festival_id,
        url="https://example.test/later",
    )

    assert db_session.get(Booth, booth.id).location_description == "Curated position"


def test_curation_is_recorded_as_provenance(db_session, overrides_file, no_curated_items):
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id)
    path = overrides_file([{"name": "The Alps", "latitude": ALPS_LAT}])
    stage_manual_overrides(db_session, path=path, items_path=no_curated_items)
    run_resolve(db_session, festival_id=festival_id)

    manual_source = db_session.scalars(select(Source).where(Source.key == "manual")).one()
    rows = db_session.scalars(
        select(EntityFieldProvenance).where(
            EntityFieldProvenance.entity_type == "booth",
            EntityFieldProvenance.canonical_id == booth.id,
            EntityFieldProvenance.field_name == "latitude",
        )
    ).all()
    assert [r.source_id for r in rows] == [manual_source.id]
    assert rows[0].is_selected is True


def test_restaging_an_unchanged_file_is_a_no_op(db_session, overrides_file, no_curated_items):
    festival_id = db_session.info["festival_id"]
    _seed_booth(db_session, festival_id)
    path = overrides_file([{"name": "The Alps", "latitude": ALPS_LAT}])

    assert stage_manual_overrides(db_session, path=path, items_path=no_curated_items) == 1
    assert stage_manual_overrides(db_session, path=path, items_path=no_curated_items) == 0
    assert stage_manual_overrides(db_session, path=path, items_path=no_curated_items) == 0

    staged = db_session.scalars(
        select(ExtractedRecord).where(ExtractedRecord.extractor_version == "manual-1")
    ).all()
    assert len(staged) == 1

    run_resolve(db_session, festival_id=festival_id)


def test_editing_the_file_stages_the_correction(db_session, overrides_file, no_curated_items):
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id)

    stage_manual_overrides(
        db_session, path=overrides_file([{"name": "The Alps", "latitude": 1.0}]), items_path=no_curated_items
    )
    run_resolve(db_session, festival_id=festival_id)
    assert db_session.get(Booth, booth.id).latitude == pytest.approx(Decimal("1.0"))

    assert stage_manual_overrides(
        db_session, path=overrides_file([{"name": "The Alps", "latitude": 2.0}]), items_path=no_curated_items
    ) == 1
    run_resolve(db_session, festival_id=festival_id)
    assert db_session.get(Booth, booth.id).latitude == pytest.approx(Decimal("2.0"))


def test_an_empty_file_stages_nothing(db_session, overrides_file, no_curated_items):
    assert stage_manual_overrides(db_session, path=overrides_file([]), items_path=no_curated_items) == 0


# ---------------------------------------------------------------------------
# menu items
# ---------------------------------------------------------------------------


@pytest.fixture()
def items_file(tmp_path):
    def _write(menu_items):
        path = tmp_path / "menu_items.json"
        path.write_text(json.dumps({"menu_items": menu_items}))
        return path

    return _write


@pytest.fixture()
def empty_booths(tmp_path):
    """A booth file with nothing in it, so an item test stages only items."""
    path = tmp_path / "no_booths.json"
    path.write_text(json.dumps({"booths": []}))
    return path


def _seed_dish(db_session, festival_id, booth="Italy", dish="Peroni Pilsner", tags=None):
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
                payload={
                    "booth_name": booth,
                    "name": dish,
                    "category": "non_alcoholic_beverage",
                    "price_usd": "6.00",
                    "dietary_tags": tags if tags is not None else [],
                },
            ),
        ],
        "disney_food_blog",
        festival_id,
        url="https://example.test/hub",
    )
    return db_session.scalars(select(MenuItem).where(MenuItem.canonical_name == dish)).one()


def test_an_item_needs_a_booth_to_be_found_inside(items_file):
    """Dishes are matched within a booth, so a dish name on its own cannot be
    resolved - and guessing which booth was meant is worse than skipping it."""
    path = items_file(
        [
            {"name": "Orphan Dish", "description": "x"},
            {"booth_name": "Italy", "description": "no name either"},
            {"booth_name": "Italy", "name": "Peroni Pilsner", "description": "ok"},
        ]
    )
    assert [e["name"] for e in load_menu_item_overrides(path)] == ["Peroni Pilsner"]


def test_an_empty_tag_list_is_kept_because_it_is_how_a_tag_comes_off(items_file):
    path = items_file([{"booth_name": "Italy", "name": "Peroni Pilsner", "dietary_tags": []}])
    assert load_menu_item_overrides(path)[0]["dietary_tags"] == []


def test_a_curated_correction_reaches_the_dish(db_session, empty_booths, items_file):
    festival_id = db_session.info["festival_id"]
    dish = _seed_dish(db_session, festival_id)
    assert dish.category == "non_alcoholic_beverage"

    path = items_file(
        [
            {
                "booth_name": "Italy",
                "name": "Peroni Pilsner",
                "description": "Italian lager",
                "price_usd": "7.25",
                "category": "alcoholic_beverage",
            }
        ]
    )
    assert stage_manual_overrides(db_session, path=empty_booths, items_path=path) == 1
    run_resolve(db_session, festival_id=festival_id)

    refreshed = db_session.get(MenuItem, dish.id)
    assert refreshed.description == "Italian lager"
    assert refreshed.category == "alcoholic_beverage"
    assert refreshed.price_usd == pytest.approx(Decimal("7.25"))


def test_a_wrong_photo_can_be_cleared(db_session, empty_booths, items_file):
    """The studio's Clear button, end to end.

    A null is normally dropped so a missing field stays open for a source to
    fill later. For a photo that reading is wrong: somebody looked at the
    wrong plate and said to take it off, and dropping the null is what made
    the old editor's Clear silently do nothing."""
    festival_id = db_session.info["festival_id"]
    dish = _seed_dish(db_session, festival_id)

    path = items_file(
        [{"booth_name": "Italy", "name": "Peroni Pilsner",
          "image_url": "https://example.test/wrong-plate.jpg"}]
    )
    stage_manual_overrides(db_session, path=empty_booths, items_path=path)
    run_resolve(db_session, festival_id=festival_id)
    assert db_session.get(MenuItem, dish.id).image_url == "https://example.test/wrong-plate.jpg"

    path = items_file([{"booth_name": "Italy", "name": "Peroni Pilsner", "image_url": None}])
    stage_manual_overrides(db_session, path=empty_booths, items_path=path)
    run_resolve(db_session, festival_id=festival_id)

    assert db_session.get(MenuItem, dish.id).image_url is None


def test_a_crawled_null_still_does_not_erase_anything(db_session, empty_booths, items_file):
    """The other half of the rule. A parser that found no description is not
    asserting there is none, so it must not beat a source that found one."""
    festival_id = db_session.info["festival_id"]
    dish = _seed_dish(db_session, festival_id)

    path = items_file(
        [{"booth_name": "Italy", "name": "Peroni Pilsner", "description": "Italian lager"}]
    )
    stage_manual_overrides(db_session, path=empty_booths, items_path=path)
    run_resolve(db_session, festival_id=festival_id)
    assert db_session.get(MenuItem, dish.id).description == "Italian lager"

    ingest(
        db_session,
        [
            ExtractedRecordDTO(
                entity_type="menu_item",
                natural_key_hint="peroni pilsner",
                payload={"booth_name": "Italy", "name": "Peroni Pilsner", "description": None},
            )
        ],
        "allears",
        festival_id,
        url="https://example.test/allears",
    )
    run_resolve(db_session, festival_id=festival_id)

    assert db_session.get(MenuItem, dish.id).description == "Italian lager"


def test_a_field_simply_absent_is_still_left_alone(db_session, empty_booths, items_file):
    """Only an explicit null erases. Omitting a field is how a correction to
    one thing avoids freezing everything else about the dish."""
    festival_id = db_session.info["festival_id"]
    dish = _seed_dish(db_session, festival_id)
    dish.image_url = "https://example.test/plate.jpg"
    db_session.flush()

    path = items_file([{"booth_name": "Italy", "name": "Peroni Pilsner", "price_usd": "7.25"}])
    stage_manual_overrides(db_session, path=empty_booths, items_path=path)
    run_resolve(db_session, festival_id=festival_id)

    assert db_session.get(MenuItem, dish.id).image_url == "https://example.test/plate.jpg"


def test_a_rename_finds_the_dish_by_its_old_name(db_session, empty_booths, items_file):
    """`name` is the match key and `rename_to` the new value. A record whose
    name is already the new one would match nothing and create a duplicate."""
    festival_id = db_session.info["festival_id"]
    dish = _seed_dish(db_session, festival_id)

    path = items_file(
        [
            {
                "booth_name": "Italy",
                "name": "Peroni Pilsner",
                "rename_to": "Peroni Nastro Azzurro",
            }
        ]
    )
    stage_manual_overrides(db_session, path=empty_booths, items_path=path)
    run_resolve(db_session, festival_id=festival_id)

    assert db_session.get(MenuItem, dish.id).canonical_name == "Peroni Nastro Azzurro"
    assert len(db_session.scalars(select(MenuItem)).all()) == 1, "a rename must not fork the dish"


def test_a_wrong_tag_can_be_taken_off(db_session, empty_booths, items_file):
    """The whole point of curating tags. Crawled sources union theirs
    together, so without a curated list replacing that union outright there
    is no way to remove one."""
    festival_id = db_session.info["festival_id"]
    dish = _seed_dish(db_session, festival_id, tags=["contains_alcohol", "contains_nuts"])
    assert {t.code for t in dish.dietary_tags} == {"contains_alcohol", "contains_nuts"}

    path = items_file(
        [{"booth_name": "Italy", "name": "Peroni Pilsner", "dietary_tags": ["contains_alcohol"]}]
    )
    stage_manual_overrides(db_session, path=empty_booths, items_path=path)
    run_resolve(db_session, festival_id=festival_id)

    assert {t.code for t in db_session.get(MenuItem, dish.id).dietary_tags} == {"contains_alcohol"}


def test_every_tag_can_be_cleared(db_session, empty_booths, items_file):
    festival_id = db_session.info["festival_id"]
    dish = _seed_dish(db_session, festival_id, tags=["contains_alcohol"])

    path = items_file([{"booth_name": "Italy", "name": "Peroni Pilsner", "dietary_tags": []}])
    stage_manual_overrides(db_session, path=empty_booths, items_path=path)
    run_resolve(db_session, festival_id=festival_id)

    assert db_session.get(MenuItem, dish.id).dietary_tags == []


def test_editing_dishes_does_not_restage_the_booth_file(db_session, overrides_file, items_file):
    """Two files, two raw_pages. A dish correction must not look like a
    change to every booth coordinate."""
    festival_id = db_session.info["festival_id"]
    _seed_dish(db_session, festival_id)

    booths = overrides_file([{"name": "Italy", "latitude": ALPS_LAT, "longitude": ALPS_LON}])
    items = items_file([{"booth_name": "Italy", "name": "Peroni Pilsner", "description": "one"}])
    assert stage_manual_overrides(db_session, path=booths, items_path=items) == 2

    items = items_file([{"booth_name": "Italy", "name": "Peroni Pilsner", "description": "two"}])
    assert stage_manual_overrides(db_session, path=booths, items_path=items) == 1


def test_restaging_unchanged_files_stages_nothing(db_session, overrides_file, items_file):
    festival_id = db_session.info["festival_id"]
    _seed_dish(db_session, festival_id)
    booths = overrides_file([{"name": "Italy", "latitude": ALPS_LAT}])
    items = items_file([{"booth_name": "Italy", "name": "Peroni Pilsner", "description": "one"}])

    assert stage_manual_overrides(db_session, path=booths, items_path=items) == 2
    assert stage_manual_overrides(db_session, path=booths, items_path=items) == 0
