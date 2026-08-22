"""The editable table view.

`render()` is pure, so the shape of what reaches the page is testable here:
which rows appear, what identifies them, and whether the embedded snapshot
can be trusted inside a <script> tag.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools/data_ledger"))

import build_editor  # noqa: E402


def _item(name, **kw):
    return {
        "name": name,
        "description": kw.get("description"),
        "price": kw.get("price"),
        "category": kw.get("category", "food"),
        "tags": kw.get("tags", []),
    }


def _snapshot(*booths):
    return {"booths": list(booths)}


def _booth(name, items=None, **kw):
    return {"name": name, "items": items or [], **kw}


def _embedded(html):
    match = re.search(
        r'<script id="editor-data" type="application/json">(.*?)</script>', html, re.DOTALL
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
    rows = build_editor.editor_rows(
        _snapshot(
            _booth("Belgium", [_item("Beer Flight", price=12.75)]),
            _booth("Germany", [_item("Beer Flight", price=12.75)]),
        )
    )
    assert [(i["booth"], i["name"]) for i in rows["items"]] == [
        ("Belgium", "Beer Flight"),
        ("Germany", "Beer Flight"),
    ]


def test_booths_carry_their_item_count_and_placement():
    rows = build_editor.editor_rows(
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
    rows = build_editor.editor_rows(
        _snapshot(_booth("", [_item("Orphan")]), _booth("Spain", [_item(""), _item("Paella")]))
    )
    assert [b["name"] for b in rows["booths"]] == ["Spain"]
    assert [i["name"] for i in rows["items"]] == ["Paella"]


def test_tags_arrive_sorted_so_a_reorder_is_not_mistaken_for_an_edit():
    """The page compares edited tags against these to decide what changed;
    unsorted originals would make every touched row look dirty."""
    rows = build_editor.editor_rows(
        _snapshot(_booth("Greece", [_item("Gyro", tags=["spicy", "contains_nuts"])]))
    )
    assert rows["items"][0]["tags"] == ["contains_nuts", "spicy"]


def test_an_empty_snapshot_renders_rather_than_raising():
    assert build_editor.editor_rows({}) == {"booths": [], "items": []}
    assert "Database Editor" in build_editor.render({})


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------


def test_the_vocabularies_the_page_edits_match_the_ones_the_pipeline_accepts():
    """The dropdown and the tag toggles are the only spellings a curated file
    will ever get from here, so they have to be the pipeline's own."""
    from epcot_fw.normalize.dietary_tags import _TAG_PATTERNS

    assert set(build_editor.TAGS) == set(_TAG_PATTERNS)
    assert set(build_editor.CATEGORIES) == {"food", "alcoholic_beverage", "non_alcoholic_beverage"}


def test_a_dish_name_cannot_close_the_script_tag():
    hostile = '</script><script>alert(1)</script>'
    html = build_editor.render(_snapshot(_booth("Japan", [_item(hostile)])))
    payload = re.search(
        r'<script id="editor-data" type="application/json">(.*?)</script>', html, re.DOTALL
    )
    assert payload, "the closing tag must still be the one the template wrote"
    assert hostile not in payload.group(1)
    assert _embedded(html)["items"][0]["name"] == hostile


def test_the_page_is_self_contained():
    html = build_editor.render(_snapshot(_booth("France", [_item("Crème Brûlée")])))
    assert 'name="viewport"' in html
    assert "<script src=" not in html
    assert "http://" not in html.replace("http://www.w3.org", "")
