import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from epcot_fw.db.base import SessionLocal
from epcot_fw.db.models import DietaryTag, Festival, Source

SOURCES = [
    dict(
        key="disney_official",
        display_name="Disney World Official Site",
        base_url="https://disneyworld.disney.go.com",
        priority_rank=1,
        crawl_delay_sec=8,
    ),
    dict(
        key="disney_parks_blog",
        display_name="Disney Parks Blog",
        base_url="https://disneyparksblog.com",
        priority_rank=2,
        crawl_delay_sec=8,
    ),
    dict(
        key="touring_plans",
        display_name="Touring Plans",
        base_url="https://touringplans.com",
        priority_rank=3,
        crawl_delay_sec=5,
    ),
    dict(
        key="allears",
        display_name="AllEars.net",
        base_url="https://allears.net",
        priority_rank=4,
        crawl_delay_sec=5,
    ),
    dict(
        key="wdwmagic",
        display_name="WDWMagic",
        base_url="https://www.wdwmagic.com",
        priority_rank=5,
        crawl_delay_sec=5,
    ),
    dict(
        key="disney_food_blog",
        display_name="Disney Food Blog",
        base_url="https://www.disneyfoodblog.com",
        priority_rank=6,
        crawl_delay_sec=5,
    ),
    dict(
        key="wdw_prep_school",
        display_name="WDW Prep School",
        base_url="https://wdwprepschool.com",
        priority_rank=7,
        crawl_delay_sec=5,
    ),
]

DIETARY_TAGS = [
    ("vegetarian", "Vegetarian"),
    ("vegan", "Vegan"),
    ("gluten_free", "Gluten-Free"),
    ("plant_based", "Plant-Based"),
    ("contains_alcohol", "Contains Alcohol"),
    ("spicy", "Spicy"),
    ("contains_nuts", "Contains Nuts"),
]


def seed() -> None:
    with SessionLocal() as session:
        for row in SOURCES:
            stmt = (
                pg_insert(Source)
                .values(**row, enabled=False)
                .on_conflict_do_nothing(index_elements=["key"])
            )
            session.execute(stmt)

        for code, label in DIETARY_TAGS:
            stmt = (
                pg_insert(DietaryTag)
                .values(code=code, label=label)
                .on_conflict_do_nothing(index_elements=["code"])
            )
            session.execute(stmt)

        year = datetime.date.today().year
        if datetime.date.today().month >= 10:
            year += 1
        stmt = (
            pg_insert(Festival)
            .values(
                year=year,
                name=f"Epcot International Food & Wine Festival {year}",
                slug=f"epcot-food-wine-{year}",
                status="upcoming",
                official_url="https://disneyworld.disney.go.com/events-tours/epcot/epcot-food-wine-festival/",
            )
            .on_conflict_do_nothing(index_elements=["slug"])
        )
        session.execute(stmt)

        session.commit()


if __name__ == "__main__":
    seed()
    print("Seed complete.")
