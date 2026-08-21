import datetime

from fastapi.testclient import TestClient

from epcot_fw.api.deps import get_db
from epcot_fw.api.main import app
from epcot_fw.db.models import (
    Booth,
    ConcertEvent,
    ConcertShowtime,
    EntityFieldProvenance,
    MenuItem,
    Seminar,
    Source,
)


def _client_for(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# booths.py
# ---------------------------------------------------------------------------


def test_list_booths_with_no_matches_returns_empty_and_does_not_error(db_session):
    festival_id = db_session.info["festival_id"]
    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/festivals/{festival_id}/booths")
        assert resp.status_code == 200
        assert resp.json() == {"data": [], "meta": {"total": 0, "page": 1, "page_size": 50}}
    finally:
        app.dependency_overrides.clear()


def test_list_booths_filters_by_category(db_session):
    festival_id = db_session.info["festival_id"]
    db_session.add_all(
        [
            Booth(festival_id=festival_id, canonical_name="Booth A", slug="booth-a", category="global_marketplace"),
            Booth(festival_id=festival_id, canonical_name="Booth B", slug="booth-b", category="outdoor_kitchen"),
        ]
    )
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/festivals/{festival_id}/booths", params={"category": "outdoor_kitchen"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["canonical_name"] == "Booth B"
    finally:
        app.dependency_overrides.clear()


def test_list_booths_filters_by_search(db_session):
    festival_id = db_session.info["festival_id"]
    db_session.add_all(
        [
            Booth(festival_id=festival_id, canonical_name="The Alps Chalet", slug="alps-chalet"),
            Booth(festival_id=festival_id, canonical_name="Refreshment Port", slug="refreshment-port"),
        ]
    )
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/festivals/{festival_id}/booths", params={"search": "alps"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["canonical_name"] == "The Alps Chalet"
    finally:
        app.dependency_overrides.clear()


def test_get_booth_with_include_menu_items(db_session):
    festival_id = db_session.info["festival_id"]
    booth = Booth(festival_id=festival_id, canonical_name="Booth With Items", slug="booth-with-items")
    db_session.add(booth)
    db_session.flush()
    db_session.add(MenuItem(booth_id=booth.id, canonical_name="Snack", category="food", price_usd=5))
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/booths/{booth.id}", params={"include": "menu_items"})
        assert resp.status_code == 200
        assert len(resp.json()["menu_items"]) == 1

        resp = client.get(f"/api/v1/booths/{booth.id}")
        assert resp.json()["menu_items"] == []
    finally:
        app.dependency_overrides.clear()


def test_the_review_routes_are_gone(db_session):
    """Mined ratings were retired - see migration c3e6a91b8d52. A client that
    still calls these should get a clean 404 rather than an empty list it
    would render as "no reviews yet"."""
    festival_id = db_session.info["festival_id"]
    booth = Booth(festival_id=festival_id, canonical_name="Norway", slug="norway")
    db_session.add(booth)
    db_session.flush()

    client = _client_for(db_session)
    try:
        assert client.get(f"/api/v1/booths/{booth.id}/reviews").status_code == 404
        assert client.post(f"/api/v1/booths/{booth.id}/reviews", json={"rating": 4}).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_booth_payloads_no_longer_carry_rating_fields(db_session):
    festival_id = db_session.info["festival_id"]
    booth = Booth(festival_id=festival_id, canonical_name="Hops & Barley", slug="hops-barley")
    db_session.add(booth)
    db_session.flush()

    client = _client_for(db_session)
    try:
        listed = client.get(f"/api/v1/festivals/{festival_id}/booths").json()["data"][0]
        detail = client.get(f"/api/v1/booths/{booth.id}").json()
        for payload in (listed, detail):
            assert "average_rating" not in payload
            assert "review_count" not in payload
    finally:
        app.dependency_overrides.clear()


def test_get_booth_provenance_returns_field_history(db_session):
    festival_id = db_session.info["festival_id"]
    booth = Booth(festival_id=festival_id, canonical_name="Provenance Booth", slug="provenance-booth")
    db_session.add(booth)
    db_session.flush()

    source = db_session.query(Source).filter_by(key="allears").one()
    from epcot_fw.db.models import ExtractedRecord, RawPage

    now = datetime.datetime.now(datetime.UTC)
    raw_page = RawPage(
        source_id=source.id,
        url="https://example.test/prov",
        page_kind="booth_list",
        fetched_at=now,
        http_status=200,
        content_hash="prov-hash",
        first_seen_at=now,
    )
    db_session.add(raw_page)
    db_session.flush()
    record = ExtractedRecord(
        raw_page_id=raw_page.id,
        source_id=source.id,
        entity_type="booth",
        extracted_at=now,
        extractor_version="test",
        payload={},
    )
    db_session.add(record)
    db_session.flush()
    db_session.add(
        EntityFieldProvenance(
            entity_type="booth",
            canonical_id=booth.id,
            field_name="category",
            source_id=source.id,
            extracted_record_id=record.id,
            value="food",
            observed_at=now,
            is_selected=True,
        )
    )
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/booths/{booth.id}/provenance")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["field_name"] == "category"
        assert body[0]["source_key"] == "allears"
        assert body[0]["is_selected"] is True
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# events.py
# ---------------------------------------------------------------------------


def test_list_events_filters_by_artist_and_date(db_session):
    festival_id = db_session.info["festival_id"]
    e1 = ConcertEvent(festival_id=festival_id, artist_name="Boyz II Men", performance_date=datetime.date(2026, 9, 1))
    e2 = ConcertEvent(festival_id=festival_id, artist_name="Sister Hazel", performance_date=datetime.date(2026, 9, 8))
    db_session.add_all([e1, e2])
    db_session.flush()
    db_session.add(ConcertShowtime(concert_event_id=e1.id, start_time=datetime.time(19, 30)))
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/festivals/{festival_id}/events", params={"artist": "boyz"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["artist_name"] == "Boyz II Men"
        assert len(body[0]["showtimes"]) == 1

        resp = client.get(f"/api/v1/festivals/{festival_id}/events", params={"date": "2026-09-08"})
        body = resp.json()
        assert len(body) == 1
        assert body[0]["artist_name"] == "Sister Hazel"
    finally:
        app.dependency_overrides.clear()


def test_get_event_success_and_404(db_session):
    festival_id = db_session.info["festival_id"]
    event = ConcertEvent(festival_id=festival_id, artist_name="Solo Act", performance_date=datetime.date(2026, 9, 15))
    db_session.add(event)
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/events/{event.id}")
        assert resp.status_code == 200
        assert resp.json()["artist_name"] == "Solo Act"

        resp = client.get("/api/v1/events/999999")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# seminars.py
# ---------------------------------------------------------------------------


def test_list_seminars_filters_by_type_and_date(db_session):
    festival_id = db_session.info["festival_id"]
    s1 = Seminar(
        festival_id=festival_id,
        title="Wine 101",
        seminar_type="beverage_seminar",
        event_date=datetime.date(2026, 9, 5),
    )
    s2 = Seminar(
        festival_id=festival_id,
        title="Chef Demo",
        seminar_type="culinary_demo",
        event_date=datetime.date(2026, 9, 12),
    )
    db_session.add_all([s1, s2])
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/festivals/{festival_id}/seminars", params={"type": "culinary_demo"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["title"] == "Chef Demo"

        resp = client.get(f"/api/v1/festivals/{festival_id}/seminars", params={"date": "2026-09-05"})
        body = resp.json()
        assert len(body) == 1
        assert body[0]["title"] == "Wine 101"
    finally:
        app.dependency_overrides.clear()


def test_get_seminar_success_and_404(db_session):
    festival_id = db_session.info["festival_id"]
    seminar = Seminar(festival_id=festival_id, title="Cheese Pairing", seminar_type="culinary_demo")
    db_session.add(seminar)
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/seminars/{seminar.id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Cheese Pairing"

        resp = client.get("/api/v1/seminars/999999")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# menu_items.py
# ---------------------------------------------------------------------------


def test_list_menu_items_filters_by_category_booth_and_price_range(db_session):
    festival_id = db_session.info["festival_id"]
    booth_a = Booth(festival_id=festival_id, canonical_name="Booth A", slug="menu-booth-a")
    booth_b = Booth(festival_id=festival_id, canonical_name="Booth B", slug="menu-booth-b")
    db_session.add_all([booth_a, booth_b])
    db_session.flush()
    db_session.add_all(
        [
            MenuItem(booth_id=booth_a.id, canonical_name="Cheap Snack", category="food", price_usd=4),
            MenuItem(booth_id=booth_a.id, canonical_name="Fancy Wine", category="alcoholic_beverage", price_usd=15),
            MenuItem(booth_id=booth_b.id, canonical_name="Other Booth Item", category="food", price_usd=8),
        ]
    )
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/festivals/{festival_id}/menu-items", params={"category": "food"})
        assert {r["canonical_name"] for r in resp.json()["data"]} == {"Cheap Snack", "Other Booth Item"}

        resp = client.get(f"/api/v1/festivals/{festival_id}/menu-items", params={"booth_id": booth_a.id})
        assert {r["canonical_name"] for r in resp.json()["data"]} == {"Cheap Snack", "Fancy Wine"}

        resp = client.get(f"/api/v1/festivals/{festival_id}/menu-items", params={"min_price": "10"})
        assert {r["canonical_name"] for r in resp.json()["data"]} == {"Fancy Wine"}

        resp = client.get(f"/api/v1/festivals/{festival_id}/menu-items", params={"max_price": "5"})
        assert {r["canonical_name"] for r in resp.json()["data"]} == {"Cheap Snack"}
    finally:
        app.dependency_overrides.clear()


def test_get_menu_item_success_and_404(db_session):
    festival_id = db_session.info["festival_id"]
    booth = Booth(festival_id=festival_id, canonical_name="Menu Item Booth", slug="menu-item-booth")
    db_session.add(booth)
    db_session.flush()
    item = MenuItem(booth_id=booth.id, canonical_name="Solo Item", category="food", price_usd=6)
    db_session.add(item)
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/menu-items/{item.id}")
        assert resp.status_code == 200
        assert resp.json()["canonical_name"] == "Solo Item"

        resp = client.get("/api/v1/menu-items/999999")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_list_dietary_tags_returns_seeded_tags(db_session):
    client = _client_for(db_session)
    try:
        resp = client.get("/api/v1/dietary-tags")
        assert resp.status_code == 200
        codes = {row["code"] for row in resp.json()}
        assert "vegan" in codes
        assert "gluten_free" in codes
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# festivals.py / meta.py
# ---------------------------------------------------------------------------


def test_get_festival_success_and_404(db_session):
    festival_id = db_session.info["festival_id"]
    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/festivals/{festival_id}")
        assert resp.status_code == 200
        assert resp.json()["slug"] == "epcot-food-wine-2026"

        resp = client.get("/api/v1/festivals/999999")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_crawl_status_returns_recent_runs_respecting_limit(db_session):
    from epcot_fw.db.models import CrawlRun

    now = datetime.datetime.now(datetime.UTC)
    for i in range(3):
        db_session.add(
            CrawlRun(
                run_type="full",
                triggered_by="test",
                started_at=now - datetime.timedelta(hours=i),
                status="success",
            )
        )
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get("/api/v1/meta/crawl-status", params={"limit": 2})
        assert resp.status_code == 200
        assert len(resp.json()) == 2
    finally:
        app.dependency_overrides.clear()
