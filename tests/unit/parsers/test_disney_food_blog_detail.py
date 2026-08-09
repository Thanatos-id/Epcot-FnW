"""Per-booth "photos of menu items" posts - the only place any monitored
source publishes individual dish photos.

The hub-page fixture is real captured HTML; these detail-page tests use
synthetic markup built from the WordPress figure/figcaption pattern, because
the live detail pages were unreachable when this was written. The extractor is
deliberately structural rather than selector-specific (see parse/images.py) so
it does not depend on DFB's exact theme markup.
"""

from pathlib import Path

import pytest

from epcot_fw.sources.disney_food_blog import BASE_URL, DisneyFoodBlogAdapter

HUB_FIXTURE = (
    Path(__file__).parent.parent.parent
    / "fixtures/html_snapshots/disney_food_blog/booth_menus_hub.html"
)

DETAIL_URL = f"{BASE_URL}/the-alps-2025-epcot-food-and-wine-festival/"

DETAIL_HTML = """
<html><body><article>
  <h1>The Alps &#8212; 2025 EPCOT Food &amp; Wine Festival</h1>
  <figure><img src="https://www.disneyfoodblog.com/wp-content/uploads/2025/08/alps-booth.jpg" />
    <figcaption>The Alps Booth</figcaption></figure>
  <p>Here is everything we ate at The Alps this year.</p>
  <figure><img src="https://www.disneyfoodblog.com/wp-content/uploads/2025/08/raclette.jpg" />
    <figcaption>Warm Raclette Swiss Cheese</figcaption></figure>
  <figure><img src="https://www.disneyfoodblog.com/wp-content/uploads/2025/08/radler.jpg" />
    <figcaption>Stiegl Brewery Key Lime Radler</figcaption></figure>
  <figure><img src="https://forms.aweber.com/form/displays.htm?id=x" />
    <figcaption>Subscribe to our newsletter</figcaption></figure>
</article></body></html>
"""


def _detail_records():
    return DisneyFoodBlogAdapter().parse(DETAIL_HTML, DETAIL_URL, "booth_detail")


def test_each_captioned_photo_becomes_a_menu_item_carrying_its_image():
    records = _detail_records()
    assert all(r.entity_type == "menu_item" for r in records)
    by_name = {r.payload["name"]: r.payload for r in records}

    assert by_name["Warm Raclette Swiss Cheese"]["image_url"].endswith("raclette.jpg")
    assert by_name["Stiegl Brewery Key Lime Radler"]["image_url"].endswith("radler.jpg")


def test_booth_name_is_derived_from_the_slug_for_every_record():
    records = _detail_records()
    assert {r.payload["booth_name"] for r in records} == {"The Alps"}


def test_newsletter_widget_is_not_captured_as_a_dish():
    names = [r.payload["name"] for r in _detail_records()]
    assert "Subscribe to our newsletter" not in names


def test_natural_key_hint_is_normalized_so_the_resolver_can_match_it():
    records = _detail_records()
    hints = {r.natural_key_hint for r in records}
    assert "warm raclette swiss cheese" in hints


def test_detail_records_carry_no_price_or_category_to_overwrite_hub_data():
    """The hub page is the authority on price/category/description. A photo
    post knows only a caption and an image, so it must not emit empty values
    that would compete in field resolution."""
    for record in _detail_records():
        assert set(record.payload) == {"booth_name", "name", "image_url"}


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("the-alps-2025-epcot-food-and-wine-festival", "The Alps"),
        ("australia-2025-epcot-food-and-wine-festival-2", "Australia"),
        ("brew-wing-lab-2025-epcot-food-and-wine-festival", "Brew Wing Lab"),
        ("bramblewood-bites-2026-epcot-food-and-wine-festival", "Bramblewood Bites"),
    ],
)
def test_booth_name_parsed_from_real_world_slug_shapes(slug, expected):
    records = DisneyFoodBlogAdapter().parse(DETAIL_HTML, f"{BASE_URL}/{slug}/", "booth_detail")
    assert records[0].payload["booth_name"] == expected


def test_unrecognized_slug_falls_back_to_the_page_heading():
    records = DisneyFoodBlogAdapter().parse(
        "<article><h1>Mystery Booth</h1>"
        '<figure><img src="https://ex.test/d.jpg" /><figcaption>A Dish</figcaption></figure>'
        "</article>",
        f"{BASE_URL}/some-unexpected-slug/",
        "booth_detail",
    )
    assert records[0].payload["booth_name"] == "Mystery Booth"


def test_page_with_no_identifiable_booth_yields_nothing():
    records = DisneyFoodBlogAdapter().parse(
        '<article><figure><img src="https://ex.test/d.jpg" />'
        "<figcaption>A Dish</figcaption></figure></article>",
        f"{BASE_URL}/some-unexpected-slug/",
        "booth_detail",
    )
    assert records == []


def test_hub_page_still_parses_as_before_and_yields_no_images():
    """Regression guard: adding the booth_detail branch must not change how
    the hub page is parsed."""
    html = HUB_FIXTURE.read_text()
    records = DisneyFoodBlogAdapter().parse(html, f"{BASE_URL}/hub/", "booth_list")
    booths = [r for r in records if r.entity_type == "booth"]
    items = [r for r in records if r.entity_type == "menu_item"]

    assert len(booths) > 25
    assert len(items) > 50
    assert all("image_url" not in r.payload for r in items)


def test_detail_seeds_are_discovered_from_the_real_hub_fixture():
    # The captured hub links to the 2025 posts, so 2025 is the year that
    # actually has seeds in this fixture.
    seeds = DisneyFoodBlogAdapter()._detail_seeds(HUB_FIXTURE.read_text(), 2025)

    assert len(seeds) > 25
    assert all(s.page_kind == "booth_detail" for s in seeds)
    assert all(s.url.startswith("https://") for s in seeds)
    assert len({s.url for s in seeds}) == len(seeds), "seeds must be de-duplicated"
    assert any("the-alps" in s.url for s in seeds)


def test_discovered_seeds_round_trip_back_to_their_booth_names():
    """Every discovered URL must yield a booth name, otherwise its photos
    would be silently dropped by _parse_booth_detail."""
    adapter = DisneyFoodBlogAdapter()
    seeds = adapter._detail_seeds(HUB_FIXTURE.read_text(), 2025)

    unnamed = [
        s.url
        for s in seeds
        if not adapter.parse(DETAIL_HTML, s.url, "booth_detail")
    ]
    assert unnamed == []


def test_prior_years_photo_posts_are_not_discovered():
    """The undated hub keeps serving last season's line-up until the new one
    is published. Booth and dish names repeat year to year, so ingesting those
    posts would quietly attach last year's plates to this year's dishes and
    read as success rather than as no-data-yet."""
    seeds = DisneyFoodBlogAdapter()._detail_seeds(HUB_FIXTURE.read_text(), 2026)
    assert seeds == []


def test_only_the_requested_year_is_kept_when_years_are_mixed():
    html = (
        "<article>"
        '<p><a href="https://www.disneyfoodblog.com/the-alps-2025-epcot-food-and-wine-festival/">'
        "The Alps</a> <— CLICK TO SEE PHOTOS OF MENU ITEMS!</p>"
        '<p><a href="https://www.disneyfoodblog.com/belgium-2026-epcot-food-and-wine-festival/">'
        "Belgium</a> <— CLICK TO SEE PHOTOS OF MENU ITEMS!</p>"
        "</article>"
    )
    seeds = DisneyFoodBlogAdapter()._detail_seeds(html, 2026)
    assert [s.url for s in seeds] == [
        "https://www.disneyfoodblog.com/belgium-2026-epcot-food-and-wine-festival/"
    ]


def test_links_that_are_not_photo_posts_are_ignored():
    html = (
        "<article>"
        '<p><a href="https://www.disneyfoodblog.com/some-unrelated-post/">Thing</a>'
        " <— CLICK TO SEE PHOTOS OF MENU ITEMS!</p>"
        "</article>"
    )
    assert DisneyFoodBlogAdapter()._detail_seeds(html, 2026) == []
