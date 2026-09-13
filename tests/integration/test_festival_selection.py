"""Which festival every pipeline and the API call "now".

The conftest fixture supplies the 2026 festival with real dates; each test
adds whatever other rows it needs around it. The case that matters is a row
for next year existing while this year's festival is still serving - which
is normal, not exotic: next year's has to be crawlable before it opens.
"""

import datetime

from epcot_fw.db.models import Festival
from epcot_fw.festival import current_festival

RUN_2026 = (datetime.date(2026, 8, 27), datetime.date(2026, 11, 21))


def _add(session, year: int, start=None, end=None) -> Festival:
    festival = Festival(
        year=year,
        name=f"Festival {year}",
        slug=f"epcot-food-wine-{year}",
        start_date=start,
        end_date=end,
        status="upcoming",
    )
    session.add(festival)
    session.flush()
    return festival


def _freeze_today(monkeypatch, year: int, month: int, day: int) -> None:
    import epcot_fw.festival as festival_module

    class _FixedDate(datetime.date):
        @classmethod
        def today(cls):
            return datetime.date(year, month, day)

    monkeypatch.setattr(festival_module.datetime, "date", _FixedDate)


def test_a_running_festival_wins_over_a_newer_row(db_session, monkeypatch):
    """The October break: seeding used to create next year's row mid-festival,
    and `ORDER BY year DESC` then handed every pipeline an empty 2027."""
    _add(db_session, 2027)  # no dates yet, as a freshly seeded row has none
    _freeze_today(monkeypatch, 2026, 10, 5)

    assert current_festival(db_session).year == 2026


def test_a_running_festival_wins_even_when_the_newer_row_is_dated(db_session, monkeypatch):
    _add(db_session, 2027, datetime.date(2027, 8, 26), datetime.date(2027, 11, 20))
    _freeze_today(monkeypatch, 2026, 10, 5)

    assert current_festival(db_session).year == 2026


def test_before_any_festival_opens_the_soonest_is_current(db_session, monkeypatch):
    """Late winter: 2026 has not opened. It is the one to be crawling toward,
    not the 2019 row that happens to be lying around."""
    _add(db_session, 2019, datetime.date(2019, 8, 29), datetime.date(2019, 11, 23))
    _freeze_today(monkeypatch, 2026, 2, 1)

    assert current_festival(db_session).year == 2026


def test_once_a_festival_ends_the_next_one_becomes_current(db_session, monkeypatch):
    _add(db_session, 2027, datetime.date(2027, 8, 26), datetime.date(2027, 11, 20))
    _freeze_today(monkeypatch, 2026, 12, 1)

    assert current_festival(db_session).year == 2027


def test_a_row_with_no_dates_is_still_found(db_session, monkeypatch):
    """Between seeding and the first crawl nothing has dates, and the newest
    row is the only answer available."""
    for row in db_session.query(Festival).all():
        row.start_date = row.end_date = None
    db_session.flush()
    _freeze_today(monkeypatch, 2026, 10, 5)

    assert current_festival(db_session).year == 2026


def test_no_festival_rows_at_all_is_none(db_session, monkeypatch):
    db_session.query(Festival).delete()
    db_session.flush()
    _freeze_today(monkeypatch, 2026, 10, 5)

    assert current_festival(db_session) is None


def test_the_last_finished_festival_stands_when_there_is_no_successor(db_session, monkeypatch):
    """After the run ends and before next year's row exists, the pipelines
    still need something to point at rather than an exception."""
    _freeze_today(monkeypatch, 2026, 12, 1)

    assert current_festival(db_session).year == 2026


def test_opening_and_closing_days_count_as_running(db_session, monkeypatch):
    _add(db_session, 2027)
    for month, day in ((8, 27), (11, 21)):
        _freeze_today(monkeypatch, 2026, month, day)
        assert current_festival(db_session).year == 2026, f"2026-{month}-{day}"


# ---------------------------------------------------------------------------
# what the API hands a client
# ---------------------------------------------------------------------------


def _client_for(db_session):
    from fastapi.testclient import TestClient

    from epcot_fw.api.deps import get_db
    from epcot_fw.api.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _clear_overrides():
    from epcot_fw.api.main import app

    app.dependency_overrides.clear()


def test_the_snapshot_reports_a_running_festival_as_running(db_session):
    """The published feed said `upcoming` for eighteen days of a festival that
    was open. The row still says `upcoming`; the payload must not.
    """
    festival = db_session.query(Festival).one()
    today = datetime.date.today()
    festival.start_date = today - datetime.timedelta(days=10)
    festival.end_date = today + datetime.timedelta(days=10)
    festival.status = "upcoming"
    db_session.flush()

    client = _client_for(db_session)
    try:
        assert client.get("/api/v1/snapshot").json()["festival"]["status"] == "running"
    finally:
        _clear_overrides()


def test_the_snapshot_defaults_to_the_running_festival_not_the_newest_row(db_session, monkeypatch):
    _add(db_session, 2027)
    _freeze_today(monkeypatch, 2026, 10, 5)

    client = _client_for(db_session)
    try:
        assert client.get("/api/v1/snapshot").json()["festival"]["year"] == 2026
    finally:
        _clear_overrides()


def test_a_specific_festival_can_still_be_asked_for_by_id(db_session, monkeypatch):
    future = _add(db_session, 2027)
    _freeze_today(monkeypatch, 2026, 10, 5)

    client = _client_for(db_session)
    try:
        body = client.get("/api/v1/snapshot", params={"festival_id": future.id}).json()
        assert body["festival"]["year"] == 2027
    finally:
        _clear_overrides()
