"""db/seed.py's seed() opens its own SessionLocal() bound to the real
production engine, same as cli/main.py - see test_cli.py's module docstring
for why these tests monkeypatch SessionLocal to a savepoint-joined
sessionmaker instead of using the shared db_session fixture.
"""

import datetime

import pytest
from sqlalchemy.orm import sessionmaker

import epcot_fw.db.seed as seed_module
from epcot_fw.db.models import DietaryTag, Festival, Source


@pytest.fixture()
def seed_session_factory(engine, monkeypatch):
    connection = engine.connect()
    trans = connection.begin()
    session_factory = sessionmaker(
        bind=connection, future=True, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr(seed_module, "SessionLocal", session_factory)

    yield session_factory

    trans.rollback()
    connection.close()


def _freeze_today(monkeypatch, year: int, month: int, day: int) -> None:
    class _FixedDate(datetime.date):
        @classmethod
        def today(cls):
            return datetime.date(year, month, day)

    monkeypatch.setattr(datetime, "date", _FixedDate)


def test_seed_creates_all_sources_disabled_by_default(seed_session_factory):
    seed_module.seed()

    session = seed_session_factory()
    sources = session.query(Source).order_by(Source.priority_rank).all()
    assert [s.key for s in sources] == [row["key"] for row in seed_module.SOURCES]
    assert all(s.enabled is False for s in sources)


def test_seed_creates_all_dietary_tags(seed_session_factory):
    seed_module.seed()

    session = seed_session_factory()
    codes = {t.code for t in session.query(DietaryTag).all()}
    assert codes == {code for code, _ in seed_module.DIETARY_TAGS}


def test_seed_creates_exactly_one_festival_row(seed_session_factory):
    seed_module.seed()

    session = seed_session_factory()
    festivals = session.query(Festival).all()
    assert len(festivals) == 1


def test_seed_is_idempotent(seed_session_factory):
    seed_module.seed()
    seed_module.seed()

    session = seed_session_factory()
    assert session.query(Source).count() == len(seed_module.SOURCES)
    assert session.query(DietaryTag).count() == len(seed_module.DIETARY_TAGS)
    assert session.query(Festival).count() == 1


def test_seed_reruns_do_not_re_enable_a_manually_enabled_source(seed_session_factory):
    seed_module.seed()

    session = seed_session_factory()
    row = session.query(Source).filter_by(key="allears").one()
    row.enabled = True
    session.commit()

    seed_module.seed()

    session2 = seed_session_factory()
    row2 = session2.query(Source).filter_by(key="allears").one()
    assert row2.enabled is True


def test_seed_uses_the_current_year_before_october(seed_session_factory, monkeypatch):
    _freeze_today(monkeypatch, 2026, 8, 15)
    seed_module.seed()

    session = seed_session_factory()
    festival = session.query(Festival).one()
    assert festival.year == 2026
    assert festival.slug == "epcot-food-wine-2026"


def test_seed_rolls_over_to_next_year_starting_in_october(seed_session_factory, monkeypatch):
    _freeze_today(monkeypatch, 2026, 10, 5)
    seed_module.seed()

    session = seed_session_factory()
    festival = session.query(Festival).one()
    assert festival.year == 2027
    assert festival.slug == "epcot-food-wine-2027"
