from pathlib import Path

from sqlalchemy import select

from epcot_fw.db.models import Booth, CanonicalLink, MenuItem
from epcot_fw.sources.allears import AllEarsAdapter
from epcot_fw.sources.disney_food_blog import DisneyFoodBlogAdapter

from ._helpers import ingest

FIXTURES = Path(__file__).parent.parent / "fixtures/html_snapshots"


def test_two_sources_dedup_into_shared_canonical_booths(db_session):
    festival_id = db_session.info["festival_id"]

    allears_html = (FIXTURES / "allears/booth_menus_hub.html").read_text()
    allears_dtos = AllEarsAdapter().parse(allears_html, "https://example.test/allears", "booth_list")

    dfb_html = (FIXTURES / "disney_food_blog/booth_menus_hub.html").read_text()
    dfb_dtos = DisneyFoodBlogAdapter().parse(dfb_html, "https://example.test/dfb", "booth_list")

    ingest(db_session, allears_dtos, "allears", festival_id, url="https://example.test/allears")
    ingest(db_session, dfb_dtos, "disney_food_blog", festival_id, url="https://example.test/dfb")

    allears_booth_count = len([d for d in allears_dtos if d.entity_type == "booth"])
    dfb_booth_count = len([d for d in dfb_dtos if d.entity_type == "booth"])
    canonical_booth_count = len(db_session.scalars(select(Booth)).all())

    # Real duplication across two independently-written sources: the merged
    # canonical count should be well below the naive sum of both sources'
    # booth listings, proving the matcher is actually collapsing duplicates
    # rather than just passing everything through.
    assert canonical_booth_count < (allears_booth_count + dfb_booth_count) * 0.7

    the_alps = db_session.scalars(select(Booth).where(Booth.canonical_name == "The Alps")).one()
    links = db_session.scalars(
        select(CanonicalLink).where(
            CanonicalLink.entity_type == "booth", CanonicalLink.canonical_id == the_alps.id
        )
    ).all()
    source_ids = {link.source_id for link in links}
    assert len(source_ids) == 2, "The Alps should be linked from both AllEars and Disney Food Blog"

    alps_items = db_session.scalars(select(MenuItem).where(MenuItem.booth_id == the_alps.id)).all()
    assert len(alps_items) > 0
    # DFB is the only one of these two sources that publishes prices - a
    # merged item that matched across both sources should have picked one up.
    assert any(item.price_usd is not None for item in alps_items)
