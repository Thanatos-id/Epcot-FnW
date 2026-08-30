"""The two things a client stores or caches: stable identifiers, and the
one-request offline bundle."""

import datetime
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from epcot_fw.api.deps import get_db
from epcot_fw.api.main import app
from epcot_fw.db.models import Booth, ConcertEvent, MenuItem, Seminar

SNAPSHOT = "/api/v1/snapshot"


def _client_for(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _seed(db_session):
    festival_id = db_session.info["festival_id"]
    booth = Booth(
        festival_id=festival_id,
        canonical_name="The Alps",
        slug="the-alps",
        category="global_marketplace",
        latitude=28.370536,
        longitude=-81.549472,
        location_description="World Showcase, near Germany",
    )
    booth.location_precision = "surveyed"
    other = Booth(festival_id=festival_id, canonical_name="Australia", slug="australia")
    db_session.add_all([booth, other])
    db_session.flush()

    db_session.add_all(
        [
            MenuItem(booth_id=booth.id, canonical_name="Kirschwasser Torte", category="food", price_usd=7),
            MenuItem(booth_id=other.id, canonical_name="Lamington", category="food", price_usd=6),
        ]
    )
    db_session.add(
        ConcertEvent(
            festival_id=festival_id, artist_name="Alpine Trio", performance_date=datetime.date(2026, 9, 1)
        )
    )
    db_session.add(Seminar(festival_id=festival_id, title="Wine 101", seminar_type="beverage_seminar"))
    db_session.flush()
    return booth, other


# ---------------------------------------------------------------------------
# public_id
# ---------------------------------------------------------------------------


def test_booths_and_items_get_a_public_id_automatically(db_session):
    booth, _ = _seed(db_session)
    item = db_session.scalars(select(MenuItem).where(MenuItem.booth_id == booth.id)).one()

    db_session.refresh(booth)
    db_session.refresh(item)
    assert isinstance(booth.public_id, uuid.UUID)
    assert isinstance(item.public_id, uuid.UUID)
    assert booth.public_id != item.public_id


def test_public_ids_are_unique_across_rows(db_session):
    booth, other = _seed(db_session)
    db_session.refresh(booth)
    db_session.refresh(other)
    items = db_session.scalars(select(MenuItem)).all()
    ids = {booth.public_id, other.public_id} | {i.public_id for i in items}
    assert len(ids) == 4


def test_public_id_survives_a_rename(db_session):
    """The whole point: a favourite must not break when a source revises the
    name it was saved under."""
    booth, _ = _seed(db_session)
    db_session.refresh(booth)
    before = booth.public_id

    booth.canonical_name = "The Alps Chalet"
    booth.slug = "the-alps-chalet"
    db_session.flush()
    db_session.refresh(booth)

    assert booth.public_id == before


def test_api_exposes_public_id_for_booths_and_items(db_session):
    festival_id = db_session.info["festival_id"]
    _seed(db_session)
    client = _client_for(db_session)
    try:
        booth_body = client.get(f"/api/v1/festivals/{festival_id}/booths").json()
        assert all(uuid.UUID(b["public_id"]) for b in booth_body["data"])

        item_body = client.get(f"/api/v1/festivals/{festival_id}/menu-items").json()
        assert all(uuid.UUID(i["public_id"]) for i in item_body["data"])
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# origin
# ---------------------------------------------------------------------------


def test_rows_are_crawled_unless_something_says_otherwise(db_session):
    booth, _ = _seed(db_session)
    assert booth.origin == "crawled"
    item = db_session.scalars(select(MenuItem).where(MenuItem.booth_id == booth.id)).first()
    assert item.origin == "crawled"


def test_the_snapshot_says_where_each_row_came_from(db_session):
    """A client that wants to badge or filter hand-added rows needs to be
    able to tell them apart; one that doesn't can ignore the field."""
    booth, other = _seed(db_session)
    other.origin = "curated"
    curated = db_session.scalars(select(MenuItem).where(MenuItem.booth_id == other.id)).one()
    curated.origin = "curated"
    db_session.flush()

    client = _client_for(db_session)
    try:
        body = client.get(SNAPSHOT).json()
        assert {b["canonical_name"]: b["origin"] for b in body["booths"]} == {
            "The Alps": "crawled", "Australia": "curated",
        }
        assert {i["canonical_name"]: i["origin"] for i in body["menu_items"]} == {
            "Kirschwasser Torte": "crawled", "Lamington": "curated",
        }
    finally:
        app.dependency_overrides.clear()


def test_adding_origin_did_not_break_the_contract(db_session):
    """It is an added field with a default, so a client built before it
    existed still decodes the payload - which is why v1 stays v1."""
    _seed(db_session)
    client = _client_for(db_session)
    try:
        body = client.get(SNAPSHOT).json()
        assert body["schema_version"] == 1
        assert body["min_app_version"] is None
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------


def test_snapshot_returns_the_whole_festival_in_one_response(db_session):
    _seed(db_session)
    client = _client_for(db_session)
    try:
        resp = client.get(SNAPSHOT)
        assert resp.status_code == 200
        body = resp.json()

        assert body["festival"]["slug"] == "epcot-food-wine-2026"
        assert {b["canonical_name"] for b in body["booths"]} == {"The Alps", "Australia"}
        assert {i["canonical_name"] for i in body["menu_items"]} == {
            "Kirschwasser Torte",
            "Lamington",
        }
        assert [e["artist_name"] for e in body["events"]] == ["Alpine Trio"]
        assert [s["title"] for s in body["seminars"]] == ["Wine 101"]
    finally:
        app.dependency_overrides.clear()


def test_snapshot_carries_coordinates_for_the_map_and_the_nearest_sort(db_session):
    """A client sorts by distance from the guest, so the snapshot has to be
    enough on its own - no second call to find out where a booth is."""
    _seed(db_session)
    client = _client_for(db_session)
    try:
        body = client.get(SNAPSHOT).json()
        alps = next(b for b in body["booths"] if b["canonical_name"] == "The Alps")

        assert float(alps["latitude"]) == 28.370536
        assert float(alps["longitude"]) == -81.549472
        assert alps["location_description"] == "World Showcase, near Germany"

        assert alps["location_precision"] == "surveyed"

        australia = next(b for b in body["booths"] if b["canonical_name"] == "Australia")
        assert australia["latitude"] is None
        assert australia["longitude"] is None
        # No coordinate means no grade to report - not a default of "surveyed".
        assert australia["location_precision"] is None
    finally:
        app.dependency_overrides.clear()


def test_menu_items_are_flat_and_keyed_back_to_their_booth(db_session):
    booth, other = _seed(db_session)
    client = _client_for(db_session)
    try:
        body = client.get(SNAPSHOT).json()
        by_name = {i["canonical_name"]: i for i in body["menu_items"]}
        assert by_name["Kirschwasser Torte"]["booth_id"] == booth.id
        assert by_name["Lamington"]["booth_id"] == other.id
    finally:
        app.dependency_overrides.clear()


def test_snapshot_sets_caching_headers(db_session):
    _seed(db_session)
    client = _client_for(db_session)
    try:
        resp = client.get(SNAPSHOT)
        assert resp.headers["ETag"].startswith('"')
        assert "max-age" in resp.headers["Cache-Control"]
    finally:
        app.dependency_overrides.clear()


def test_unchanged_data_returns_304_with_no_body(db_session):
    _seed(db_session)
    client = _client_for(db_session)
    try:
        first = client.get(SNAPSHOT)
        etag = first.headers["ETag"]

        second = client.get(SNAPSHOT, headers={"If-None-Match": etag})
        assert second.status_code == 304
        assert second.content == b""
        assert second.headers["ETag"] == etag
    finally:
        app.dependency_overrides.clear()


def test_etag_changes_when_the_data_changes(db_session):
    booth, _ = _seed(db_session)
    client = _client_for(db_session)
    try:
        etag = client.get(SNAPSHOT).headers["ETag"]

        db_session.add(
            MenuItem(booth_id=booth.id, canonical_name="Raclette", category="food", price_usd=9)
        )
        db_session.flush()

        resp = client.get(SNAPSHOT, headers={"If-None-Match": etag})
        assert resp.status_code == 200
        assert resp.headers["ETag"] != etag
    finally:
        app.dependency_overrides.clear()


def test_etag_is_stable_across_identical_requests(db_session):
    _seed(db_session)
    client = _client_for(db_session)
    try:
        assert client.get(SNAPSHOT).headers["ETag"] == client.get(SNAPSHOT).headers["ETag"]
    finally:
        app.dependency_overrides.clear()


def test_snapshot_defaults_to_the_newest_festival(db_session):
    from epcot_fw.db.models import Festival

    _seed(db_session)
    db_session.add(Festival(year=2019, name="Old", slug="old-2019", status="past"))
    db_session.flush()

    client = _client_for(db_session)
    try:
        assert client.get(SNAPSHOT).json()["festival"]["year"] == 2026
    finally:
        app.dependency_overrides.clear()


def test_snapshot_can_be_asked_for_a_specific_festival(db_session):
    from epcot_fw.db.models import Festival

    _seed(db_session)
    old = Festival(year=2019, name="Old", slug="old-2019", status="past")
    db_session.add(old)
    db_session.flush()

    client = _client_for(db_session)
    try:
        body = client.get(SNAPSHOT, params={"festival_id": old.id}).json()
        assert body["festival"]["year"] == 2019
        assert body["booths"] == []
        assert body["menu_items"] == []
    finally:
        app.dependency_overrides.clear()


def test_unknown_festival_is_404(db_session):
    client = _client_for(db_session)
    try:
        assert client.get(SNAPSHOT, params={"festival_id": 999999}).status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# the client envelope
# ---------------------------------------------------------------------------


def test_the_snapshot_says_which_contract_it_is(db_session):
    _seed(db_session)
    client = _client_for(db_session)
    try:
        body = client.get(SNAPSHOT).json()
        assert body["schema_version"] == 1
        assert body["min_app_version"] is None
    finally:
        app.dependency_overrides.clear()


def test_data_updated_at_comes_from_the_rows_not_the_clock(db_session):
    """If it were a build timestamp, every response would be a different
    payload and the ETag would never match twice - which would cost a
    returning client the entire snapshot on every launch, the exact thing
    this endpoint exists to avoid."""
    booth, _ = _seed(db_session)
    client = _client_for(db_session)
    try:
        first = client.get(SNAPSHOT)
        second = client.get(SNAPSHOT)
        assert first.json()["data_updated_at"] == second.json()["data_updated_at"]
        assert first.headers["ETag"] == second.headers["ETag"]

        # ...and it does move when the data does.
        booth.canonical_name = "The Alps (revised)"
        db_session.flush()
        third = client.get(SNAPSHOT)
        assert third.json()["data_updated_at"] >= first.json()["data_updated_at"]
        assert third.headers["ETag"] != first.headers["ETag"]
    finally:
        app.dependency_overrides.clear()


def test_an_empty_festival_still_produces_a_readable_snapshot(db_session):
    """Pre-season, before any crawl. A client must get a valid payload it can
    decode and show an empty state for, not a 500."""
    client = _client_for(db_session)
    try:
        body = client.get(SNAPSHOT).json()
        assert body["schema_version"] == 1
        assert body["data_updated_at"] is None
        assert body["booths"] == []
    finally:
        app.dependency_overrides.clear()
