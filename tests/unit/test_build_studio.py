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


def test_a_booths_opening_date_reaches_the_page():
    rows = snapshot_rows.studio_rows(_snapshot(_booth("The Wedge", opens_at="2026-09-18")))
    assert rows["booths"][0]["opens_at"] == "2026-09-18"


def test_a_booth_with_no_opening_date_reads_as_open_now():
    """Absent on the snapshot - true of every booth before this field
    existed - has to render the same as an explicit null: open now."""
    rows = snapshot_rows.studio_rows(_snapshot(_booth("Italy")))
    assert rows["booths"][0]["opens_at"] is None


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


def test_the_page_is_self_contained_apart_from_leaflet_and_its_typeface():
    """Inter comes from Google Fonts with a system-font fallback, so the page
    still reads cleanly offline - it just reads in San Francisco."""
    html = build_studio.render(_snapshot(_booth("France", [_item("Crème Brûlée")])))
    assert 'name="viewport"' in html
    external = re.findall(r'https?://[^"\s]+', html)
    allowed = ("unpkg.com/leaflet", "arcgisonline.com", "tile.openstreetmap.org", "www.w3.org",
               "fonts.googleapis.com", "fonts.gstatic.com")
    assert [u for u in external if not any(a in u for a in allowed)] == []


# ---------------------------------------------------------------------------
# master / detail
# ---------------------------------------------------------------------------


def test_the_shell_is_one_viewport_with_two_scrollers():
    """The bar is a grid row and each pane scrolls on its own, so nothing has
    to be measured at runtime to keep the last dish clear of anything - the
    old page did, and was wrong on some device every time it wrapped."""
    html = build_studio.render(_snapshot(_booth("Spain", [_item("Paella")])))
    assert "height: 100dvh" in html
    assert ".booth-list, .detail {" in html
    assert "overscroll-behavior: contain" in html
    for gone in ("syncBarHeight", "syncPaneHeight", "--bar-height", "--pane-max"):
        assert gone not in html, gone


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


def test_the_map_is_a_drawer_that_saves_only_on_save():
    """A pin is a draft until Save location; Close, Cancel and Esc leave the
    staged placements exactly as they were."""
    html = build_studio.render(_snapshot(_booth("Spain", [_item("Paella")])))
    assert 'id="map-drawer"' in html
    assert 'id="drawer-save"' in html and "Save location" in html
    assert "state.drawer.draft" in html
    # The only write to placements from the map is the save.
    assert html.count("state.placements[d.booth] = {") == 1


def test_all_four_festivals_reach_the_page_and_only_the_crawled_one_is_editable():
    snapshot = _snapshot(_booth("Spain", [_item("Paella")]))
    snapshot["festival"] = {"name": "EPCOT International Food & Wine Festival"}
    catalog = build_studio.festival_catalog(snapshot)
    assert [f["key"] for f in catalog] == [
        "festival-of-the-arts", "flower-and-garden", "food-and-wine", "festival-of-the-holidays",
    ]
    assert [f["key"] for f in catalog if f["has_data"]] == ["food-and-wine"]
    html = build_studio.render(snapshot)
    for f in catalog:
        assert f["key"] in html
    assert "function festivalEditable()" in html


def test_a_snapshot_from_no_known_festival_makes_nothing_editable():
    """Edits typed under the wrong festival would export into this one, so an
    unrecognised name refuses edits everywhere rather than guessing."""
    catalog = build_studio.festival_catalog({"festival": {"name": "Something Else"}})
    assert not any(f["has_data"] for f in catalog)
    assert not any(f["has_data"] for f in build_studio.festival_catalog({}))


def test_the_redesign_keeps_reading_the_same_saved_edits():
    """Unexported work lives in this browser under these names. A rename here
    would silently strand every edit nobody has exported yet."""
    html = build_studio.render(_snapshot(_booth("Spain")))
    # The database festival's scope is empty, so its keys are exactly these.
    assert "var SCOPE = RESEARCH ? ':' + LOADED.key : '';" in html
    assert "var STORE_KEY = 'epcot-studio-v1' + SCOPE;" in html
    assert "var DB_NAME = 'epcot-studio' + SCOPE;" in html
    # And a researched festival is never the one loaded unless asked for.
    assert "})[0] || PRIMARY;" in html


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


def test_the_opening_date_control_is_in_the_rendered_page():
    """The rest of this page's editable fields are only exercised through the
    browser (see docs/WORKFLOW.md), so this is a lighter guard: catches the
    field being dropped from the template outright, not a JS behaviour bug."""
    html = build_studio.render(_snapshot(_booth("The Wedge")))
    assert "opens_at" in html
    assert "opens-later" in html


def test_every_dish_can_be_deleted_not_just_the_hand_added_ones():
    """The button used to be gated behind `isAdded(row)`, which left no way to
    remove a duplicate or a mangled row the crawl produced - the case it is
    most often needed for. Same lighter guard as the test above: catches the
    gate coming back, not a JS behaviour bug."""
    html = build_studio.render(_snapshot(_booth("Belgium", [_item("Belgian Waffle")])))
    assert "deleteDish" in html
    assert "pill deleted" in html


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


def test_edits_already_applied_are_settled_on_load():
    """Stored edits never learned they had shipped, so after an apply and a
    rebuild every one of them went on counting as a change and riding along
    in the next export. Same lighter guard as above - the behaviour itself
    was checked in the browser against a real 72-row backlog."""
    html = build_studio.render(_snapshot(_booth("Belgium", [_item("Belgian Waffle")])))
    assert "loadPhotos().then(settle)" in html
    assert 'id="settled-note"' in html


def test_the_studio_installs_as_its_own_app():
    """Its own manifest, so Chrome installs "Epcot Studio" opening on the
    studio rather than the ledger; and a service worker, which Chrome wants
    before it offers Install at all."""
    html = build_studio.render(_snapshot(_booth("Spain")))
    assert '<link rel="manifest" href="studio.webmanifest" />' in html
    assert "navigator.serviceWorker.register('studio-sw.js', { scope: './studio' })" in html
    assert 'id="install-btn"' in html
    assert 'id="update-line"' in html

    assets = Path(build_studio.__file__).parent / "assets"
    manifest = json.loads((assets / "studio.webmanifest").read_text())
    assert manifest["start_url"] == "studio.html"
    assert manifest["display"] == "standalone"
    # The start page has to sit inside both the app's scope and the worker's.
    assert manifest["start_url"].startswith(manifest["scope"])


def test_the_app_always_opens_on_the_latest_build():
    """Network first: a rebuild, or a merge to main for the Pages copy, is what
    the app shows next time it opens. The cache only answers when the server
    cannot."""
    worker = (Path(build_studio.__file__).parent / "assets" / "studio-sw.js").read_text()
    assert "fetch(request, { cache: 'no-cache' })" in worker
    assert ".catch(() => caches.match(request" in worker


# ---------------------------------------------------------------------------
# festivals researched into data/festivals/
# ---------------------------------------------------------------------------


def _research():
    return {"festival-of-the-holidays": {
        "festival": {"name": "Festival of the Holidays 2026"},
        "meta": {"name": "Festival of the Holidays 2026", "summary": "First pass from research."},
        "booths": [_booth("Refreshment Outpost", [{**_item("Turkey Poutine"), "badges": ["2025 menu"]}],
                          origin="researched")],
    }}


def _embedded_festivals(html):
    match = re.search(
        r'<script id="studio-festivals" type="application/json">(.*?)</script>', html, re.DOTALL
    )
    return json.loads(match.group(1))


def test_a_researched_festival_is_editable_and_says_where_its_rows_came_from():
    snapshot = _snapshot(_booth("Spain", [_item("Paella")]))
    snapshot["festival"] = {"name": "EPCOT International Food & Wine Festival"}
    catalog = {f["key"]: f for f in build_studio.festival_catalog(snapshot, _research())}
    assert catalog["food-and-wine"]["source"] == "database"
    assert catalog["festival-of-the-holidays"]["source"] == "research"
    assert catalog["festival-of-the-holidays"]["note"] == "First pass from research."
    assert not catalog["flower-and-garden"]["has_data"]


def test_researched_rows_travel_separately_from_the_database_rows():
    """Both festivals have a "Refreshment Outpost"; one blob would merge them."""
    snapshot = _snapshot(_booth("Refreshment Outpost", [_item("Pork Belly")]))
    snapshot["festival"] = {"name": "EPCOT International Food & Wine Festival"}
    html = build_studio.render(snapshot, festivals=_research())
    assert [i["name"] for i in _embedded(html)["items"]] == ["Pork Belly"]
    holidays = _embedded_festivals(html)["festival-of-the-holidays"]
    assert [i["name"] for i in holidays["items"]] == ["Turkey Poutine"]
    assert holidays["items"][0]["badges"] == ["2025 menu"]
    assert holidays["booths"][0]["origin"] == "researched"


def test_only_a_researched_festival_names_itself_in_its_changeset():
    """A database changeset stays byte-for-byte what earlier builds wrote."""
    html = build_studio.render(_snapshot(_booth("Spain")), festivals=_research())
    assert "if (RESEARCH) changeset.festival = LOADED.key;" in html


def test_without_research_the_page_embeds_no_second_festival():
    html = build_studio.render(_snapshot(_booth("Spain")))
    assert _embedded_festivals(html) == {}
