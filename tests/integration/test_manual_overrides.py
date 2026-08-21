"""Hand-curated booth facts have to reach the canonical row, beat whatever a
crawl said, and survive the next crawl saying it again."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from epcot_fw.db.models import Booth, EntityFieldProvenance, ExtractedRecord, Source
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.pipeline.manual import load_booth_overrides, stage_manual_overrides
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


def test_every_shipped_anchor_is_a_complete_and_labelled_coordinate():
    entries = load_booth_overrides(SHIPPED)
    assert entries, "the pavilion anchors should ship with the repo"
    for entry in entries:
        assert entry["latitude"] is not None and entry["longitude"] is not None
        assert entry["location_precision"] == "anchored", (
            f"{entry['name']}: a shipped coordinate is a pavilion stand-in, not a survey"
        )


def test_no_shipped_anchor_has_landed_outside_the_park():
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


def test_curated_coordinates_land_on_the_matching_booth(db_session, overrides_file):
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id)
    assert booth.latitude is None

    path = overrides_file(
        [{"name": "The Alps", "latitude": ALPS_LAT, "longitude": ALPS_LON,
          "location_description": "World Showcase, near Germany"}]
    )
    assert stage_manual_overrides(db_session, path=path) == 1
    run_resolve(db_session, festival_id=festival_id)

    refreshed = db_session.get(Booth, booth.id)
    assert refreshed.latitude == pytest.approx(Decimal(str(ALPS_LAT)))
    assert refreshed.longitude == pytest.approx(Decimal(str(ALPS_LON)))
    assert refreshed.location_description == "World Showcase, near Germany"


def test_precision_travels_with_the_coordinate(db_session, overrides_file):
    """A coordinate without its grade is worse than useless: the client can't
    tell a metre-accurate survey from a pavilion standing in for a kiosk 40 m
    away, so it either overstates every distance or distrusts all of them."""
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id)

    path = overrides_file(
        [{"name": "The Alps", "latitude": ALPS_LAT, "longitude": ALPS_LON,
          "location_precision": "anchored"}]
    )
    stage_manual_overrides(db_session, path=path)
    run_resolve(db_session, festival_id=festival_id)
    assert db_session.get(Booth, booth.id).location_precision == "anchored"


def test_a_survey_supersedes_the_anchor_it_replaces(db_session, overrides_file):
    """The anchors ship as a floor. Walking up to the booth has to be able to
    overwrite one, precision included, or the survey is pointless."""
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id)

    anchored = overrides_file(
        [{"name": "The Alps", "latitude": 28.368060, "longitude": -81.546940,
          "location_precision": "anchored"}]
    )
    stage_manual_overrides(db_session, path=anchored)
    run_resolve(db_session, festival_id=festival_id)

    surveyed = overrides_file(
        [{"name": "The Alps", "latitude": ALPS_LAT, "longitude": ALPS_LON,
          "location_precision": "surveyed"}]
    )
    stage_manual_overrides(db_session, path=surveyed)
    run_resolve(db_session, festival_id=festival_id)

    refreshed = db_session.get(Booth, booth.id)
    assert refreshed.location_precision == "surveyed"
    assert refreshed.latitude == pytest.approx(Decimal(str(ALPS_LAT)))


def test_a_name_that_is_close_but_not_exact_still_matches(db_session, overrides_file):
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id, name="Refreshment Port")

    path = overrides_file([{"name": "Refreshment Port (NEW)", "latitude": ALPS_LAT}])
    stage_manual_overrides(db_session, path=path)
    run_resolve(db_session, festival_id=festival_id)

    assert db_session.get(Booth, booth.id).latitude is not None


def test_curated_value_outranks_a_crawled_one(db_session, overrides_file):
    """A crawled source supplying the same field must not win against
    curation, whichever order they arrive in."""
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id)

    path = overrides_file([{"name": "The Alps", "location_description": "Curated position"}])
    stage_manual_overrides(db_session, path=path)
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


def test_curation_is_recorded_as_provenance(db_session, overrides_file):
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id)
    path = overrides_file([{"name": "The Alps", "latitude": ALPS_LAT}])
    stage_manual_overrides(db_session, path=path)
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


def test_restaging_an_unchanged_file_is_a_no_op(db_session, overrides_file):
    festival_id = db_session.info["festival_id"]
    _seed_booth(db_session, festival_id)
    path = overrides_file([{"name": "The Alps", "latitude": ALPS_LAT}])

    assert stage_manual_overrides(db_session, path=path) == 1
    assert stage_manual_overrides(db_session, path=path) == 0
    assert stage_manual_overrides(db_session, path=path) == 0

    staged = db_session.scalars(
        select(ExtractedRecord).where(ExtractedRecord.extractor_version == "manual-1")
    ).all()
    assert len(staged) == 1

    run_resolve(db_session, festival_id=festival_id)


def test_editing_the_file_stages_the_correction(db_session, overrides_file):
    festival_id = db_session.info["festival_id"]
    booth = _seed_booth(db_session, festival_id)

    stage_manual_overrides(db_session, path=overrides_file([{"name": "The Alps", "latitude": 1.0}]))
    run_resolve(db_session, festival_id=festival_id)
    assert db_session.get(Booth, booth.id).latitude == pytest.approx(Decimal("1.0"))

    assert stage_manual_overrides(
        db_session, path=overrides_file([{"name": "The Alps", "latitude": 2.0}])
    ) == 1
    run_resolve(db_session, festival_id=festival_id)
    assert db_session.get(Booth, booth.id).latitude == pytest.approx(Decimal("2.0"))


def test_an_empty_file_stages_nothing(db_session, overrides_file):
    assert stage_manual_overrides(db_session, path=overrides_file([])) == 0
