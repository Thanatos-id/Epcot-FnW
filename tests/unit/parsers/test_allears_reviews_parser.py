from pathlib import Path

from epcot_fw.sources.allears import AllEarsAdapter

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures/html_snapshots/allears"
PAGES = [
    "booth_reviews.html",
    "booth_reviews_page2.html",
    "booth_reviews_page3.html",
    "booth_reviews_page4.html",
]


def _parse_all():
    adapter = AllEarsAdapter()
    records = []
    for name in PAGES:
        html = (FIXTURE_DIR / name).read_text()
        records.extend(adapter.parse(html, "https://example.test", "booth_reviews"))
    return records


def test_extracts_all_reviews_across_pages_with_no_duplicates():
    records = _parse_all()
    assert len(records) == 37
    ids = {r.payload["external_review_id"] for r in records}
    assert len(ids) == 37  # every id unique - would only fail on a pagination bug


def test_known_review_fields_are_correct():
    records = _parse_all()
    heidi = next(r for r in records if r.payload["external_review_id"] == "1279744")
    assert heidi.payload["reviewer_name"] == "HeidiZ"
    assert heidi.payload["reviewed_at"] == "2023-09-14"
    assert heidi.payload["rating_raw"] == 2
    assert heidi.payload["rating_scale"] == 10
    assert heidi.payload["recommended"] is False
    assert "Fry Basket" not in heidi.payload["review_text"]  # sanity: real body text, not garbage

    positive = next(r for r in records if r.payload["external_review_id"] == "70633")
    assert positive.payload["rating_raw"] == 10
    assert positive.payload["recommended"] is True
