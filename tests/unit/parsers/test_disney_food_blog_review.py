"""Dated review permalinks - how DFB publishes 2026's dish photos.

Through 2025 the photos lived in per-booth posts whose slug named the booth
and the year, and both discovery and booth attribution keyed off that slug.
For 2026 the same photos appear under dated review permalinks
(/2026/08/27/review-.../) that name no booth anywhere the old path could
look: the hub links none of them, and the <h1> is a newsletter signup.

The fixture is real captured HTML from the Belgium review, so what these
assert about filenames and captions is what DFB actually publishes rather
than what a synthetic page makes easy.
"""

from pathlib import Path

import pytest

from epcot_fw.sources.disney_food_blog import (
    _PERMALINK_YEAR_RE,
    BASE_URL,
    DisneyFoodBlogAdapter,
    _booth_from_filename,
    _booth_name_from_photos,
)

REVIEW_FIXTURE = (
    Path(__file__).parent.parent.parent
    / "fixtures/html_snapshots/disney_food_blog/booth_review_2026.html"
)
REVIEW_URL = (
    f"{BASE_URL}/2026/08/27/review-this-epcot-food-wine-festival-booth-"
    "proves-sometimes-keeping-it-simple-is-the-way-to-go/"
)


def _records():
    return DisneyFoodBlogAdapter().parse(REVIEW_FIXTURE.read_text(), REVIEW_URL, "booth_review")


# ---------------------------------------------------------------------------
# booth attribution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,expected",
    [
        # The two shapes DFB's photo desk produces.
        ("2026-Disney-World-WDW-EPCOT-Food-and-Wine-Festival-Belgium-Booth-Belgian-Waffle-700x525.jpg", "Belgium"),
        ("DFB-_-Beer-Flight_-Belgium-_-2026-EPCOT-Food-Wine-Festival-_-Disney-World-Photo.jpg", "Belgium"),
        # A multi-word booth: the walk back stops at "Festival", not mid-name.
        ("2026-Disney-World-WDW-EPCOT-Food-and-Wine-Festival-The-Alps-Booth-Raclette-700x525.jpg", "The Alps"),
        # Nothing to go on.
        ("DFB-Homepage-Button-07-20-25-1.png", None),
    ],
)
def test_a_booth_name_is_recovered_from_the_filename(filename, expected):
    assert _booth_from_filename(f"https://www.disneyfoodblog.com/wp-content/uploads/2026/08/{filename}") == expected


def test_the_majority_of_photos_decides_the_booth():
    """One oddly-named file must not decide the booth for a whole post."""
    base = "https://www.disneyfoodblog.com/wp-content/uploads/2026/08/"
    urls = [f"{base}2026-EPCOT-Food-and-Wine-Festival-Belgium-Booth-Waffle-{i}-700x525.jpg" for i in range(5)]
    urls.append(f"{base}DFB-Chilled-Belgian-Coffee-non-alcoholic-Belgium-Booth-EPCOT.jpg")
    assert _booth_name_from_photos(urls) == "Belgium"


def test_a_post_whose_photos_disagree_yields_no_booth():
    """A tie is not a majority. Attaching a photo to another booth's dish is
    worse than attaching none, because it looks like data."""
    base = "https://www.disneyfoodblog.com/wp-content/uploads/2026/08/"
    urls = [
        f"{base}2026-EPCOT-Food-and-Wine-Festival-Belgium-Booth-Waffle-700x525.jpg",
        f"{base}2026-EPCOT-Food-and-Wine-Festival-Germany-Booth-Torte-700x525.jpg",
    ]
    assert _booth_name_from_photos(urls) is None


def test_a_single_photo_is_not_enough_to_name_a_booth():
    base = "https://www.disneyfoodblog.com/wp-content/uploads/2026/08/"
    assert _booth_name_from_photos([f"{base}2026-Festival-Belgium-Booth-Waffle-700x525.jpg"]) is None


def test_photos_that_name_nothing_produce_no_booth():
    assert _booth_name_from_photos(["https://example.test/banner.png", "https://example.test/x.jpg"]) is None


# ---------------------------------------------------------------------------
# the real page
# ---------------------------------------------------------------------------


def test_the_belgium_review_resolves_to_belgium():
    records = _records()
    assert records, "the fixture should yield dish records"
    assert {r.payload["booth_name"] for r in records} == {"Belgium"}


def test_the_page_h1_is_not_used_as_the_booth():
    """The <h1> on these posts is "Get the DFB Newsletter". The per-booth path
    falls back to it when the slug carries no booth, which is exactly the
    wrong answer here - every record would match no booth and be dropped."""
    assert "Newsletter" not in {r.payload["booth_name"] for r in _records()}


def test_dish_captions_and_their_photos_come_through():
    by_name = {r.payload["name"]: r.payload["image_url"] for r in _records()}
    for dish in ("Belgian Waffle", "Beer-braised Beef", "Beer Flight"):
        assert dish in by_name, f"{dish} should be extracted"
        assert by_name[dish].startswith("https://"), f"{dish} needs a usable photo URL"


def test_records_are_menu_items_that_can_only_attach_never_create():
    """"Menu" and "Full Spread" are captions on the same markup as the
    dishes. They match nothing, which the matcher reads as a new dish unless
    the record forbids it."""
    for record in _records():
        assert record.entity_type == "menu_item"
        assert record.payload["attach_only"] is True
        assert set(record.payload) == {"booth_name", "name", "image_url", "attach_only"}


def test_a_review_with_no_usable_photos_yields_nothing_rather_than_guessing():
    html = "<html><body><article><h1>Get the DFB Newsletter</h1><p>No photos here.</p></article></body></html>"
    assert DisneyFoodBlogAdapter().parse(html, REVIEW_URL, "booth_review") == []


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,year",
    [("/2026/08/27/review-a-booth/", "2026"), ("/2025/09/01/review-a-booth/", "2025")],
)
def test_the_permalink_year_is_read_from_the_path(path, year):
    """These are dated permalinks - unlike the per-booth posts, the year is in
    the path rather than the slug, which is why _slug_year cannot see them."""
    assert _PERMALINK_YEAR_RE.match(path).group("year") == year


def test_a_per_booth_slug_is_not_mistaken_for_a_review_permalink():
    assert _PERMALINK_YEAR_RE.match("/the-alps-2025-epcot-food-and-wine-festival/") is None
