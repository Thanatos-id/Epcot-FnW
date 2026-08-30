"""The curation studio - the page that replaced editor.html and map.html.

`render()` is pure, so everything except the browser and Leaflet behaviour is
testable here: which rows reach the page, what identifies them, and whether
the snapshot blob can be trusted once it is inside a <script> tag. Unlike
survey.html, this page legitimately needs the network at view time (Leaflet
and map tiles), so it is not held to that page's "no external resource" bar.
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools/data_ledger"))

import build_studio  # noqa: E402
import snapshot_rows  # noqa: E402


def _item(name, **kw):
    return {
        "name": name,
        "image_source": kw.get("image_source"),
        "public_id": kw.get("public_id", "11111111-1111-4111-8111-111111111111"),
        "origin": kw.get("origin", "crawled"),
        "description": kw.get("description"),
        "price": kw.get("price"),
        "category": kw.get("category", "food"),
        "tags": kw.get("tags", []),
        "image_url": kw.get("image_url"),
        "image_data_uri": kw.get("image_data_uri"),
    }


def _booth(name, items=None, **kw):
    return {"name": name, "public_id": kw.pop("public_id", "b0000000-0000-4000-8000-000000000000"),
            "items": items or [], **kw}


def _snapshot(*booths):
    return {"booths": list(booths)}


def _embedded(html):
    match = re.search(
        r'<script id="studio-data" type="application/json">(.*?)</script>', html, re.DOTALL
    )
    assert match, "the page must carry its rows"
    return json.loads(match.group(1).replace("<\\/", "</"))


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------


def test_items_are_flattened_out_of_their_booths_and_keep_the_booth():
    """A dish is identified by booth and name together - five booths sell
    something called "Beer Flight" - and that pair is what a curated record
    needs to find it again."""
    rows = snapshot_rows.studio_rows(
        _snapshot(
            _booth("Belgium", [_item("Beer Flight", price=12.75)]),
            _booth("Germany", [_item("Beer Flight", price=12.75)]),
        )
    )
    assert [(i["booth"], i["name"]) for i in rows["items"]] == [
        ("Belgium", "Beer Flight"),
        ("Germany", "Beer Flight"),
    ]


def test_public_ids_reach_the_page():
    """An attached photo is filed under the dish's public_id, so a row that
    arrives without one has nothing stable to name its file by."""
    rows = snapshot_rows.studio_rows(
        _snapshot(_booth("Italy", [_item("Tiramisu", public_id="dish-uuid")], public_id="booth-uuid"))
    )
    assert rows["items"][0]["public_id"] == "dish-uuid"
    assert rows["booths"][0]["public_id"] == "booth-uuid"


def test_a_row_with_no_origin_reads_as_crawled():
    """A snapshot exported before the column existed must not make every
    dish look hand-added, which is what would hide them all behind the
    "added by hand" filter."""
    booth = _booth("Spain", [_item("Paella")])
    del booth["items"][0]["origin"]
    rows = snapshot_rows.studio_rows(_snapshot(booth))
    assert rows["items"][0]["origin"] == "crawled"
    assert rows["booths"][0]["origin"] == "crawled"


def test_the_inlined_photo_reaches_the_page_as_image():
    rows = snapshot_rows.studio_rows(
        _snapshot(_booth("France", [_item("Escargot", image_data_uri="data:image/jpeg;base64,AAA")]))
    )
    assert rows["items"][0]["image"] == "data:image/jpeg;base64,AAA"


def test_a_dish_with_no_photo_carries_neither_url_nor_data():
    """Both halves have to be empty for the page to render its empty state -
    a failed fetch leaves image_url set and image_data_uri missing, and that
    is honestly the same thing: no picture to look at."""
    rows = snapshot_rows.studio_rows(_snapshot(_booth("Japan", [_item("Sushi")])))
    assert rows["items"][0]["image"] is None
    assert rows["items"][0]["image_url"] is None


def test_booths_carry_their_item_count_and_placement():
    rows = snapshot_rows.studio_rows(
        _snapshot(
            _booth(
                "Italy",
                [_item("Tiramisu"), _item("Peroni Pilsner")],
                latitude=28.3675,
                longitude=-81.5483,
                location_precision="anchored",
            )
        )
    )
    (booth,) = rows["booths"]
    assert booth["item_count"] == 2
    assert booth["location_precision"] == "anchored"


def test_rows_without_a_name_are_dropped():
    rows = snapshot_rows.studio_rows(
        _snapshot(_booth("", [_item("Orphan")]), _booth("Spain", [_item(""), _item("Paella")]))
    )
    assert [b["name"] for b in rows["booths"]] == ["Spain"]
    assert [i["name"] for i in rows["items"]] == ["Paella"]


def test_tags_arrive_sorted_so_a_reorder_is_not_mistaken_for_an_edit():
    """The page compares edited tags against these to decide what changed;
    unsorted originals would make every touched row look dirty."""
    rows = snapshot_rows.studio_rows(
        _snapshot(_booth("Greece", [_item("Gyro", tags=["spicy", "contains_nuts"])]))
    )
    assert rows["items"][0]["tags"] == ["contains_nuts", "spicy"]


def test_an_empty_snapshot_renders_rather_than_raising():
    assert snapshot_rows.studio_rows({}) == {"booths": [], "items": []}
    assert "Studio" in build_studio.render({})


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------


def test_the_vocabularies_the_page_edits_match_the_ones_the_pipeline_accepts():
    """The dropdown and the tag toggles are the only spellings a curated file
    will ever get from here, so they have to be the pipeline's own."""
    from epcot_fw.normalize.dietary_tags import _TAG_PATTERNS

    assert set(build_studio.TAGS) == set(_TAG_PATTERNS)
    assert set(build_studio.CATEGORIES) == {"food", "alcoholic_beverage", "non_alcoholic_beverage"}


@pytest.mark.parametrize(
    "hostile_name",
    ['</script><script>alert(1)</script>', '</SCRIPT ><b>', 'Beer </script> Flight'],
)
def test_a_dish_name_cannot_close_the_script_tag(hostile_name):
    html = build_studio.render(_snapshot(_booth("Japan", [_item(hostile_name)])))
    payload = re.search(
        r'<script id="studio-data" type="application/json">(.*?)</script>', html, re.DOTALL
    )
    assert payload, "the closing tag must still be the one the template wrote"
    assert hostile_name not in payload.group(1)
    assert _embedded(html)["items"][0]["name"] == hostile_name


def test_a_booth_name_cannot_close_the_script_tag():
    hostile = '</script><img src=x onerror=alert(1)>'
    html = build_studio.render(_snapshot(_booth(hostile)))
    assert _embedded(html)["booths"][0]["name"] == hostile


def test_the_aggregate_heading_is_named_so_the_page_can_refuse_to_place_it():
    """"Additional Festival Locations" is a heading covering dishes sold in
    several places at once, not somewhere a person can stand. Its dishes are
    still editable; only its pin is withheld."""
    html = build_studio.render(
        _snapshot(_booth(snapshot_rows.AGGREGATE_BOOTH_NAME, [_item("Cold Brew")]))
    )
    assert json.dumps(snapshot_rows.AGGREGATE_BOOTH_NAME) in html
    assert _embedded(html)["items"][0]["name"] == "Cold Brew"


def test_the_map_centers_on_world_showcase():
    html = build_studio.render(_snapshot(_booth("Spain")))
    assert json.dumps(build_studio.DEFAULT_CENTER) in html
    assert f"var ZOOM = {build_studio.DEFAULT_ZOOM};" in html


def test_leaflet_and_both_tile_providers_are_present():
    html = build_studio.render(_snapshot(_booth("Spain")))
    assert "leaflet@1.9.4/dist/leaflet.js" in html
    assert "leaflet@1.9.4/dist/leaflet.css" in html
    assert "arcgisonline.com" in html  # satellite tiles
    assert "tile.openstreetmap.org" in html  # street tiles


def test_dropped_pins_are_staged_as_mapped_precision():
    """Not "surveyed". A pin dropped by eye against satellite imagery is
    better than a pavilion-anchor stand-in and worse than a GPS fix taken at
    the booth, and the grade travels with the coordinate."""
    html = build_studio.render(_snapshot(_booth("Spain")))
    assert "entry.location_precision = 'mapped';" in html
    assert "precision: 'mapped'" in html


def test_the_page_is_self_contained_apart_from_leaflet():
    html = build_studio.render(_snapshot(_booth("France", [_item("Crème Brûlée")])))
    assert 'name="viewport"' in html
    external = re.findall(r'https?://[^"\s]+', html)
    allowed = ("unpkg.com/leaflet", "arcgisonline.com", "tile.openstreetmap.org", "www.w3.org")
    assert [u for u in external if not any(a in u for a in allowed)] == []


# ---------------------------------------------------------------------------
# master / detail
# ---------------------------------------------------------------------------


def test_the_booth_rail_is_the_width_it_was_asked_to_be():
    html = build_studio.render(_snapshot(_booth("Spain")))
    assert "grid-template-columns: 450px minmax(0, 1fr)" in html


def test_the_detail_pane_starts_empty_and_says_what_to_do():
    """Nothing is selected on first load, so the right-hand pane has to
    explain itself rather than reading as a page that failed to render."""
    html = build_studio.render(_snapshot(_booth("Spain", [_item("Paella")])))
    assert 'id="detail-empty"' in html
    assert "Select a booth" in html


def test_both_panes_are_present_for_a_snapshot_with_one_booth():
    html = build_studio.render(_snapshot(_booth("Spain", [_item("Paella")])))
    for element in ('id="booth-list"', 'id="dish-list"', 'id="booth-detail"'):
        assert element in html, element


def test_each_pane_scrolls_on_its_own():
    """Two lists of very different lengths share the screen. On one page
    scroll the rail runs out long before a long menu does, so working down
    the menu means losing the booth you are in."""
    html = build_studio.render(_snapshot(_booth("Spain", [_item("Paella")])))
    assert "@media (min-width: 901px)" in html
    assert ".booth-list, .rows {" in html
    assert "overflow-y: auto;" in html
    assert "overscroll-behavior: contain;" in html


def test_everything_that_must_clear_the_export_bar_is_sized_from_a_measurement():
    """The bar is fixed, so nothing in flow knows its height - and it is not
    one height: it wraps to two rows when the change count grows or the
    screen narrows, and gains the safe-area inset on a phone. 61px against
    109px is the difference between a clear last card and a covered one."""
    html = build_studio.render(_snapshot(_booth("Spain", [_item("Paella")])))
    assert "--bar-height" in html
    assert "syncBarHeight" in html
    # Both reserves derive from it rather than restating a number.
    assert "--shell-bottom: calc(var(--bar-height) + 24px)" in html
    assert "calc(var(--bar-height) + 32px)" in html


def test_a_pane_is_sized_from_where_it_actually_sits():
    """A sticky pane is only at --shell-top once the page has scrolled far
    enough to push it there. Sizing for the pinned case alone left the bottom
    of both lists behind the bar at every other scroll position."""
    html = build_studio.render(_snapshot(_booth("Spain", [_item("Paella")])))
    assert "--pane-max" in html
    assert "syncPaneHeight" in html
    # The layout holds the scroll range open, or the panes shrink, the page
    # shortens, the header never scrolls away and they never grow back.
    assert ".layout { min-height:" in html


def test_cards_do_not_shrink_inside_a_bounded_pane():
    """Both lists are flex columns, and a bounded flex column shrinks its
    items to fit rather than overflowing - every card a sliver, no
    scrollbar."""
    html = build_studio.render(_snapshot(_booth("Spain", [_item("Paella")])))
    assert html.count("flex: none;") >= 2


def test_the_two_search_boxes_are_scoped_to_their_own_pane():
    """One box over both lists reads as a single search and behaves as two."""
    html = build_studio.render(_snapshot(_booth("Spain")))
    assert 'id="booth-search"' in html and "Filter booths" in html
    assert 'id="dish-search"' in html and "Search this menu" in html


def test_the_page_no_longer_offers_a_flat_list_of_every_dish():
    """The tabbed all-dishes view is gone: a dish is only understood next to
    the others on the same menu, and 209 of them in one column was not that."""
    html = build_studio.render(_snapshot(_booth("Spain", [_item("Paella")])))
    assert 'id="tab-items"' not in html
    assert 'id="tab-booths"' not in html


# ---------------------------------------------------------------------------
# photo credit
# ---------------------------------------------------------------------------


def test_the_photo_source_reaches_the_page():
    """Every picture here was taken by somebody else, and another page reads
    the credit back out of this one."""
    source = {"credit": "Disney Food Blog", "site": "www.disneyfoodblog.com",
              "season": 2026, "page_url": "https://example.test/review/", "via": "disney_food_blog"}
    rows = snapshot_rows.studio_rows(
        _snapshot(_booth("Belgium", [_item("Belgian Waffle", image_source=source)]))
    )
    assert rows["items"][0]["image_source"] == source


def test_a_dish_with_no_recorded_source_carries_none_rather_than_a_gap():
    rows = snapshot_rows.studio_rows(_snapshot(_booth("Belgium", [_item("Belgian Waffle")])))
    assert rows["items"][0]["image_source"] is None


def test_the_credit_element_is_stable_enough_to_read_from_outside():
    """The class and the data-* attributes are the contract another page
    consumes, so they are worth a test that fails when they move."""
    html = build_studio.render(_snapshot(_booth("Belgium", [_item("Belgian Waffle")])))
    assert "photo-credit" in html
    for attribute in ("data-credit", "data-page-url", "data-season", "data-image-url",
                      "data-dish", "data-booth", "data-public-id", "data-via"):
        assert attribute in html, attribute


def test_the_page_names_the_command_that_applies_its_export():
    """The export is a downloaded file, not a paste block, so the page has to
    say what to do with it or the loop has no end."""
    html = build_studio.render(_snapshot(_booth("Spain")))
    assert "epcot-fw studio apply" in html
