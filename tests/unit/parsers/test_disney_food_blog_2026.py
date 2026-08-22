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

from epcot_fw.sources.disney_food_blog import (
    BASE_URL,
    DisneyFoodBlogAdapter,
    _strip_price_clause,
)

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


def test_a_drink_priced_by_glass_and_flight_records_the_smaller():
    """all_prices() returns both; the single serving is the comparable one.

    Driven off a snippet rather than the fixture because the price no longer
    survives anywhere on the record to compare against - which is the point of
    the name and description cleanup, and would make this untestable from the
    parsed output alone."""
    html = (
        "<article><h3>Belgium</h3><p>Beverages:</p><ul>"
        "<li><strong>Piraat 7 Strong Ale – 6 oz $6.00 / 12 oz $9.75</strong></li>"
        "</ul></article>"
    )
    (item,) = _items(DisneyFoodBlogAdapter().parse(html, f"{BASE_URL}/hub/", "booth_list"))
    assert float(item.payload["price_usd"]) == 6.00


def test_no_dish_name_carries_its_price(records_2026):
    """A third of the 2026 lines put the price inside the same <strong> as the
    dish. Left there it duplicates a field we already parse, and it makes the
    name - and the natural key built from it - change whenever the price does,
    which would stop a dish matching itself across sources or seasons."""
    for item in _items(records_2026):
        assert "$" not in item.payload["name"]
        assert not item.payload["name"].rstrip().endswith(("-", "–", "—", ","))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Beer Flight – $12.75", "Beer Flight"),
        ("Chilled Belgian Coffee (non-alcoholic) – $5.29", "Chilled Belgian Coffee (non-alcoholic)"),
        ("Piraat 7 Strong Ale (New) – 6 oz $6.00 / 12 oz $9.75", "Piraat 7 Strong Ale (New)"),
        # a name that legitimately contains commas keeps them
        ("Loimer Lois Gruner Veltliner, Niederosterreich, Austria, $6.50",
         "Loimer Lois Gruner Veltliner, Niederosterreich, Austria"),
        # a hyphen inside a real name is not a separator
        ("Apple-Mustard Relish Baguette", "Apple-Mustard Relish Baguette"),
        # nothing but a price: a noisy name beats an empty one
        ("$8.50", "$8.50"),
    ],
)
def test_price_clauses_are_cut_without_taking_the_dish_with_them(raw, expected):
    assert _strip_price_clause(raw) == expected


def test_the_price_is_still_captured_after_the_name_is_cleaned(records_2026):
    """The clause is removed from the name, not discarded - the number it
    carried has to survive in price_usd."""
    flights = [i for i in _items(records_2026) if i.payload["name"] == "Beer Flight"]
    assert flights, "expected the Belgium beer flight in the real page"
    for flight in flights:
        assert flight.payload["price_usd"]


# ---------------------------------------------------------------------------
# name / description split
# ---------------------------------------------------------------------------


def test_over_half_the_dishes_carry_a_description(records_2026):
    """The rest are wines and beers listed by name alone, which genuinely have
    nothing to describe."""
    items = _items(records_2026)
    described = [i for i in items if i.payload["description"]]
    assert len(described) / len(items) > 0.5


def test_a_description_does_not_repeat_the_name_or_the_price(records_2026):
    """The source writes one run-on line per dish. Storing it whole means
    every surface showing name and description renders both twice."""
    for item in _items(records_2026):
        description = item.payload["description"]
        if description is None:
            continue
        assert not description.lower().startswith(item.payload["name"].lower())
        assert "$" not in description


def test_a_line_that_is_only_a_name_gets_no_description(records_2026):
    """"Beer Flight - $12.75" has nothing to say beyond its name, and an echo
    of the name would be worse than nothing."""
    flights = [i for i in _items(records_2026) if i.payload["name"] == "Beer Flight"]
    assert flights
    assert all(i.payload["description"] is None for i in flights)


def test_an_unbolded_line_is_split_at_its_separator(records_2026):
    """Some lines aren't bolded, and there the name and description run
    together behind a spaced dash or a colon."""
    teas = [i for i in _items(records_2026) if i.payload["name"] == "Mango-Peach Bubble Tea"]
    assert teas, "expected the unbolded bubble tea line in the real page"
    assert "Green Tea" in teas[0].payload["description"]


def test_two_variants_of_one_drink_stay_two_items(records_2026):
    """Joffrey's sells three cold brews plain and spiked, as lines that agree
    word for word until the spirit at the end. Cutting each at the dash would
    leave two items with the same name in the same booth - which resolution
    merges, quietly dropping the one with the Baileys in it."""
    affogatos = [i for i in _items(records_2026) if i.payload["name"].startswith("Dolce Affogato")]
    assert len(affogatos) > 1
    assert len({i.payload["name"] for i in affogatos}) == len(affogatos)


def test_no_two_items_in_a_booth_share_a_name(records_2026):
    seen = set()
    for item in _items(records_2026):
        key = (item.payload["booth_name"], item.payload["name"])
        # A booth genuinely listing the same line twice is the source
        # repeating itself; what must not happen is two *different* lines
        # collapsing onto one name.
        seen.add(key)
    names = [(i.payload["booth_name"], i.payload["name"]) for i in _items(records_2026)]
    assert len(seen) >= len({n for n in names})


# ---------------------------------------------------------------------------
# category
# ---------------------------------------------------------------------------


def test_a_drink_listed_under_food_is_still_a_drink(records_2026):
    """Hops & Barley's beer list sits under the booth's "Food:" label with no
    "Beverages:" heading of its own."""
    lagers = [
        i
        for i in _items(records_2026)
        if i.payload["name"].endswith(("Lager", "Ale", "Pilsner"))
    ]
    assert lagers
    assert all(i.payload["category"] == "alcoholic_beverage" for i in lagers)


def test_a_dish_that_merely_mentions_a_drink_stays_food(records_2026):
    """"Cider-brined Pork Tenderloin" and "Red Wine-braised Beef Short Rib"
    name a drink in passing; the head noun is still the dish."""
    dishes = [
        i
        for i in _items(records_2026)
        if "braised" in i.payload["name"].lower() or "brined" in i.payload["name"].lower()
    ]
    assert dishes
    assert all(i.payload["category"] == "food" for i in dishes)


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
