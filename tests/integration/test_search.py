import datetime

from fastapi.testclient import TestClient

from epcot_fw.api.deps import get_db
from epcot_fw.api.main import app
from epcot_fw.db.models import Booth, ConcertEvent, Festival, MenuItem, Seminar


def _client_for(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _seed(db_session):
    festival_id = db_session.info["festival_id"]

    booth = Booth(
        festival_id=festival_id, canonical_name="The Alps Chalet", slug="the-alps-chalet", category="global_marketplace"
    )
    other_booth = Booth(
        festival_id=festival_id, canonical_name="Refreshment Port", slug="refreshment-port", category="global_marketplace"
    )
    db_session.add_all([booth, other_booth])
    db_session.flush()

    menu_item = MenuItem(booth_id=booth.id, canonical_name="Alpine Cheese Plate", category="food", price_usd=9)
    other_item = MenuItem(booth_id=other_booth.id, canonical_name="Frozen Cocktail", category="beverage", price_usd=13)
    db_session.add_all([menu_item, other_item])

    event = ConcertEvent(
        festival_id=festival_id,
        artist_name="Alpine Trio",
        performance_date=datetime.date(2026, 9, 1),
    )
    db_session.add(event)

    seminar = Seminar(festival_id=festival_id, title="Alps of Wine", seminar_type="culinary_demo")
    db_session.add(seminar)

    db_session.flush()
    return festival_id


def test_search_matches_across_all_entity_types_by_default(db_session):
    _seed(db_session)
    client = _client_for(db_session)
    try:
        resp = client.get("/api/v1/search", params={"q": "Alp"})
        assert resp.status_code == 200
        body = resp.json()
        assert {b["name"] for b in body["booths"]} == {"The Alps Chalet"}
        assert {m["name"] for m in body["menu_items"]} == {"Alpine Cheese Plate"}
        assert {e["artist_name"] for e in body["events"]} == {"Alpine Trio"}
        assert {s["title"] for s in body["seminars"]} == {"Alps of Wine"}
    finally:
        app.dependency_overrides.clear()


def test_search_is_case_insensitive(db_session):
    _seed(db_session)
    client = _client_for(db_session)
    try:
        resp = client.get("/api/v1/search", params={"q": "ALPS"})
        assert resp.status_code == 200
        assert {b["name"] for b in resp.json()["booths"]} == {"The Alps Chalet"}
    finally:
        app.dependency_overrides.clear()


def test_search_types_param_restricts_result_keys(db_session):
    _seed(db_session)
    client = _client_for(db_session)
    try:
        resp = client.get("/api/v1/search", params={"q": "Alp", "types": "booth"})
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"booths"}

        resp = client.get("/api/v1/search", params={"q": "Alp", "types": "booth,seminar"})
        body = resp.json()
        assert set(body.keys()) == {"booths", "seminars"}
    finally:
        app.dependency_overrides.clear()


def test_search_festival_id_scopes_results(db_session):
    festival_id = _seed(db_session)
    other_festival = Festival(
        year=2025,
        name="Other Festival",
        slug="other-festival",
        status="past",
    )
    db_session.add(other_festival)
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get("/api/v1/search", params={"q": "Alp", "festival_id": other_festival.id})
        assert resp.status_code == 200
        body = resp.json()
        assert body["booths"] == []
        assert body["events"] == []
        assert body["seminars"] == []

        resp = client.get("/api/v1/search", params={"q": "Alp", "festival_id": festival_id})
        assert resp.json()["booths"] != []
    finally:
        app.dependency_overrides.clear()


def test_search_no_match_returns_empty_lists(db_session):
    _seed(db_session)
    client = _client_for(db_session)
    try:
        resp = client.get("/api/v1/search", params={"q": "zzz-nonexistent"})
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"booths": [], "menu_items": [], "events": [], "seminars": []}
    finally:
        app.dependency_overrides.clear()


def test_search_requires_nonempty_query(db_session):
    client = _client_for(db_session)
    try:
        resp = client.get("/api/v1/search", params={"q": ""})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()
