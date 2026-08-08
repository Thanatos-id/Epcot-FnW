from fastapi.testclient import TestClient

from epcot_fw.api.deps import get_db
from epcot_fw.api.main import app
from epcot_fw.db.models import Booth, DietaryTag, MenuItem


def _client_for(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_festivals_and_booths_endpoints(db_session):
    festival_id = db_session.info["festival_id"]
    booth = Booth(
        festival_id=festival_id, canonical_name="Test Booth", slug="test-booth", category="global_marketplace"
    )
    db_session.add(booth)
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get("/api/v1/festivals")
        assert resp.status_code == 200
        assert resp.json()[0]["slug"] == "epcot-food-wine-2026"

        resp = client.get(f"/api/v1/festivals/{festival_id}/booths")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["canonical_name"] == "Test Booth"

        resp = client.get(f"/api/v1/booths/{booth.id}")
        assert resp.status_code == 200
        assert resp.json()["canonical_name"] == "Test Booth"

        resp = client.get("/api/v1/booths/999999")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_menu_items_dietary_tag_filter(db_session):
    festival_id = db_session.info["festival_id"]
    booth = Booth(festival_id=festival_id, canonical_name="Filter Booth", slug="filter-booth")
    db_session.add(booth)
    db_session.flush()

    vegan_tag = db_session.query(DietaryTag).filter_by(code="vegan").one()

    vegan_item = MenuItem(booth_id=booth.id, canonical_name="Vegan Thing", category="food", price_usd=5)
    vegan_item.dietary_tags = [vegan_tag]
    plain_item = MenuItem(booth_id=booth.id, canonical_name="Plain Thing", category="food", price_usd=6)
    db_session.add_all([vegan_item, plain_item])
    db_session.flush()

    client = _client_for(db_session)
    try:
        resp = client.get(f"/api/v1/festivals/{festival_id}/menu-items?dietary_tag=vegan")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["canonical_name"] == "Vegan Thing"

        resp = client.get(f"/api/v1/festivals/{festival_id}/menu-items")
        assert resp.json()["meta"]["total"] == 2
    finally:
        app.dependency_overrides.clear()


def test_health_and_sources(db_session):
    client = _client_for(db_session)
    try:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        sources = client.get("/api/v1/sources").json()
        assert any(s["key"] == "allears" for s in sources)
    finally:
        app.dependency_overrides.clear()
