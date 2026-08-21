import datetime

import pytest
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import sessionmaker

from epcot_fw.config import settings
from epcot_fw.db.base import Base
from epcot_fw.db.models import DietaryTag, Festival, Source

TEST_DB_URL = settings.test_database_url

SOURCE_ROWS = [
    dict(key="manual", display_name="Manual curation", base_url="manual://curated", priority_rank=0, enabled=True, crawl_delay_sec=0),
    dict(key="disney_official", display_name="Disney World Official Site", base_url="https://disneyworld.disney.go.com", priority_rank=1, enabled=True, crawl_delay_sec=8),
    dict(key="disney_parks_blog", display_name="Disney Parks Blog", base_url="https://disneyparksblog.com", priority_rank=2, enabled=False, crawl_delay_sec=8),
    dict(key="touring_plans", display_name="Touring Plans", base_url="https://touringplans.com", priority_rank=3, enabled=False, crawl_delay_sec=5),
    dict(key="allears", display_name="AllEars.net", base_url="https://allears.net", priority_rank=4, enabled=True, crawl_delay_sec=5),
    dict(key="wdwmagic", display_name="WDWMagic", base_url="https://www.wdwmagic.com", priority_rank=5, enabled=False, crawl_delay_sec=5),
    dict(key="disney_food_blog", display_name="Disney Food Blog", base_url="https://www.disneyfoodblog.com", priority_rank=6, enabled=True, crawl_delay_sec=5),
    dict(key="wdw_prep_school", display_name="WDW Prep School", base_url="https://wdwprepschool.com", priority_rank=7, enabled=False, crawl_delay_sec=5),
]

DIETARY_TAG_ROWS = [
    ("vegetarian", "Vegetarian"),
    ("vegan", "Vegan"),
    ("gluten_free", "Gluten-Free"),
    ("plant_based", "Plant-Based"),
    ("contains_alcohol", "Contains Alcohol"),
    ("spicy", "Spicy"),
    ("contains_nuts", "Contains Nuts"),
]


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL, future=True)
    _drop_everything(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _drop_everything(eng) -> None:
    """Drop what is actually in the test database, not what the models
    currently describe.

    `Base.metadata.drop_all` only knows today's tables, so a table removed
    from the models (`reviews`, when mined ratings were retired) survives in
    any test database created before the change - and then blocks the drop of
    everything it still has a foreign key into. Reflecting first means the
    schema is genuinely rebuilt from the models on every run, whatever it
    used to look like.
    """
    existing = MetaData()
    existing.reflect(bind=eng)
    existing.drop_all(bind=eng)


@pytest.fixture()
def db_session(engine):
    connection = engine.connect()
    trans = connection.begin()
    session_factory = sessionmaker(bind=connection, future=True, expire_on_commit=False)
    session = session_factory()

    for row in SOURCE_ROWS:
        session.add(Source(**row))
    for code, label in DIETARY_TAG_ROWS:
        session.add(DietaryTag(code=code, label=label))
    session.flush()

    festival = Festival(
        year=2026,
        name="EPCOT International Food & Wine Festival 2026",
        slug="epcot-food-wine-2026",
        start_date=datetime.date(2026, 8, 27),
        end_date=datetime.date(2026, 11, 21),
        status="upcoming",
    )
    session.add(festival)
    session.flush()

    session.info["festival_id"] = festival.id

    yield session

    session.close()
    trans.rollback()
    connection.close()
