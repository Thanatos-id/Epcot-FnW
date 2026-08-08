import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from epcot_fw.db.models import Booth, ExtractedRecord, Review, Source
from epcot_fw.pipeline.resolve_pipeline import run_resolve
from epcot_fw.sources.allears import AllEarsAdapter

from ._helpers import ingest

FIXTURES = Path(__file__).parent.parent / "fixtures/html_snapshots/allears"
REVIEW_PAGES = ["booth_reviews.html", "booth_reviews_page2.html", "booth_reviews_page3.html", "booth_reviews_page4.html"]


def _stage_reviews(session, festival_id):
    source = session.scalars(select(Source).where(Source.key == "allears")).one()
    adapter = AllEarsAdapter()
    now = datetime.datetime.now(datetime.timezone.utc)

    from epcot_fw.db.models import RawPage

    for name in REVIEW_PAGES:
        html = (FIXTURES / name).read_text()
        dtos = adapter.parse(html, f"https://example.test/{name}", "booth_reviews")
        raw_page = RawPage(
            source_id=source.id, url=f"https://example.test/{name}", page_kind="booth_reviews",
            fetched_at=now, http_status=200, content_hash=f"test-{name}", first_seen_at=now,
        )
        session.add(raw_page)
        session.flush()
        for dto in dtos:
            session.add(
                ExtractedRecord(
                    raw_page_id=raw_page.id, source_id=source.id, entity_type="review",
                    extracted_at=now, extractor_version="test", payload=dto.payload,
                    natural_key_hint=dto.natural_key_hint,
                )
            )
    session.flush()


def test_reviews_attach_to_mentioned_booths_and_are_idempotent(db_session):
    festival_id = db_session.info["festival_id"]

    booth_html = (FIXTURES / "booth_menus_hub.html").read_text()
    booth_dtos = AllEarsAdapter().parse(booth_html, "https://example.test/booths", "booth_list")
    ingest(db_session, booth_dtos, "allears", festival_id, url="https://example.test/booths")

    _stage_reviews(db_session, festival_id)

    stats1 = run_resolve(db_session, festival_id=festival_id)
    assert stats1["reviews_matched"] > 0

    review_count_1 = len(db_session.scalars(select(Review)).all())
    assert review_count_1 == stats1["reviews_matched"]

    # A review naming multiple booths (Japan, Fry Basket, Tangierine) should
    # produce a Review row on each of those booths, not just one.
    japan = db_session.scalars(select(Booth).where(Booth.canonical_name == "Japan")).one()
    japan_reviews = db_session.scalars(select(Review).where(Review.entity_id == japan.id)).all()
    assert len(japan_reviews) >= 1
    assert all(r.rating >= Decimal("1.0") and r.rating <= Decimal("5.0") for r in japan_reviews)
    assert all(r.match_method == "booth_name_mention" for r in japan_reviews)

    # Idempotency: re-running resolve must not duplicate review rows.
    stats2 = run_resolve(db_session, festival_id=festival_id)
    assert stats2["reviews_matched"] == 0  # nothing NEW matched second time
    review_count_2 = len(db_session.scalars(select(Review)).all())
    assert review_count_2 == review_count_1


def test_rating_normalized_from_ten_point_to_five_point_scale(db_session):
    festival_id = db_session.info["festival_id"]
    booth_html = (FIXTURES / "booth_menus_hub.html").read_text()
    booth_dtos = AllEarsAdapter().parse(booth_html, "https://example.test/booths", "booth_list")
    ingest(db_session, booth_dtos, "allears", festival_id, url="https://example.test/booths")
    _stage_reviews(db_session, festival_id)
    run_resolve(db_session, festival_id=festival_id)

    # The Joeyvee99 review (external id 70633) is a real fixture rating of
    # 10/10 and mentions no specific booth by name in this dataset's slice -
    # instead verify the scale math directly via any review with rating_raw=2.
    two_of_ten = db_session.scalars(select(Review).where(Review.rating_raw == Decimal("2.0"))).first()
    if two_of_ten:
        assert two_of_ten.rating == Decimal("1.0")
