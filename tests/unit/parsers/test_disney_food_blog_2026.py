"""The 2026 hub layout.

DFB rebuilt this page for 2026: booths moved from linked photo-post
paragraphs to <h3> headings, and the menus came onto the hub itself. The
first 2026 crawl fetched it successfully and extracted nothing, which is the
regression these tests exist to stop repeating.

Both fixtures are real captured pages.
"""

import re
from pathlib import Path

import pytest

from epcot_fw.sources.disney_food_blog import BASE_URL, DisneyFoodBlogAdapter

FIXTURES = Path(__file__).parent.parent.parent / "fixtures/html_snapshots/disney_food_blog"
HUB_2026 = FIXTURES / "booth_menus_hub_2026.html"
HUB_2025 = FIXTURES / "booth_menus_hub.html"

_PRICE_RE = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?)")


@pytest.fixture(scope="module")
def records_2026():
    return DisneyFoodBlogAdapter().parse(HUB_2026.read_text(), f"{BASE_URL}/hub/", "booth_list")


def _booths(records):
    return [r for r in records if r.entity_type == "booth"]


def _items(records):
    return [r for r in records if r.entity_type == "menu_item"]


def test_the_2026_hub_yields_the_full_lineup(records_2026):
    assert len(_booths(records_2026)) > 30
    assert len(_items(records_2026)) > 200


def test_menus_now_carry_prices(records_2026):
    """The whole point of the menu drop - the 2025 hub gave us none."""
    items = _items(records_2026)
    priced = [i for i in items if i.payload["price_usd"]]
    assert len(priced) / len(items) > 0.9


def test_known_booths_are_present_under_their_real_names(records_2026):
    names = {b.payload["name"] for b in _booths(records_2026)}
    assert {"The Alps", "Australia", "Belgium", "Brew-Wing Lab", "Gyozas of the Galaxy"} <= names


@pytest.mark.parametrize(
    "heading_fragment",
    ["Opening October", "Opens October", "Opens September", "Open September"],
)
def test_no_booth_name_keeps_its_opening_date(records_2026, heading_fragment):
    """A run-date clause is scheduling, not identity - left in, the booth
    stops matching the same booth as named by any other source."""
    names = [b.payload["name"] for b in _booths(records_2026)]
    assert not any(heading_fragment.lower() in n.lower() for n in names)


def test_a_hyphen_inside_a_real_name_survives(records_2026):
    names = {b.payload["name"] for b in _booths(records_2026)}
    assert "Brew-Wing Lab" in names


def test_non_booth_headings_are_not_treated_as_booths(records_2026):
    """Excluded structurally - a heading is only a booth if its section
    carries a Food:/Beverages: label - rather than by a blocklist."""
    names = {b.payload["name"] for b in _booths(records_2026)}
    assert not any("click here" in n.lower() for n in names)


def test_every_item_is_attributed_to_a_booth_that_exists(records_2026):
    booth_names = {b.payload["name"] for b in _booths(records_2026)}
    orphans = {
        i.payload["booth_name"]
        for i in _items(records_2026)
        if i.payload["booth_name"] not in booth_names
    }
    assert orphans == set()


def test_beverages_are_split_into_alcoholic_and_not(records_2026):
    categories = {i.payload["category"] for i in _items(records_2026)}
    assert {"food", "alcoholic_beverage", "non_alcoholic_beverage"} <= categories


def test_a_drink_priced_by_glass_and_flight_records_the_smaller(records_2026):
    """all_prices() returns both; the single serving is the comparable one."""
    multi = [
        i
        for i in _items(records_2026)
        if i.payload["price_usd"] and i.payload["description"].count("$") > 1
    ]
    assert multi, "expected at least one multi-priced line in the real page"
    for item in multi:
        prices = [float(p) for p in _PRICE_RE.findall(item.payload["description"])]
        assert float(item.payload["price_usd"]) == min(prices)


def test_natural_keys_are_normalized_so_the_resolver_can_match(records_2026):
    for record in _booths(records_2026):
        assert record.natural_key_hint == record.natural_key_hint.lower().strip()
        assert "  " not in record.natural_key_hint


# ---------------------------------------------------------------------------
# the older layout must keep working
# ---------------------------------------------------------------------------


def test_the_2025_layout_still_parses():
    """Kept because the page shape is the only way to tell the layouts apart,
    and an archive or a mid-season revert should parse rather than silently
    yield nothing."""
    records = DisneyFoodBlogAdapter().parse(HUB_2025.read_text(), f"{BASE_URL}/hub/", "booth_list")
    assert len(_booths(records)) > 25
    assert len(_items(records)) > 50


def test_the_two_layouts_agree_on_the_returning_booths():
    old = DisneyFoodBlogAdapter().parse(HUB_2025.read_text(), f"{BASE_URL}/hub/", "booth_list")
    new = DisneyFoodBlogAdapter().parse(HUB_2026.read_text(), f"{BASE_URL}/hub/", "booth_list")
    shared = {b.payload["name"] for b in _booths(old)} & {b.payload["name"] for b in _booths(new)}
    assert len(shared) > 15, "most pavilions return year to year; a tiny overlap means a parse bug"


def test_an_unrecognised_page_yields_nothing_rather_than_guessing():
    records = DisneyFoodBlogAdapter().parse(
        "<html><body><article><h3>Some Heading</h3><p>Prose, no menu.</p></article></body></html>",
        f"{BASE_URL}/hub/",
        "booth_list",
    )
    assert records == []
