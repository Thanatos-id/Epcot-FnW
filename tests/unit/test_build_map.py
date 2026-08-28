"""The desk-based map capture page.

`render()` is pure, so everything except the browser/Leaflet behaviour is
testable here: which booths appear, in what order, and whether the snapshot
blob can be trusted once it is inside a <script> tag. Unlike survey.html,
this page legitimately needs the network at view time (Leaflet + map tiles),
so it is not held to the "no external resource" bar that page's tests use.
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools/data_ledger"))

import build_map  # noqa: E402


def _booth(name, *, lat=None, lon=None, precision=None, description=None):
    return {
        "name": name,
        "latitude": lat,
        "longitude": lon,
        "location_precision": precision,
        "location_description": description,
        "items": [],
    }


def _snapshot(booths):
    return {"booths": booths}


def _embedded(html: str) -> list[dict]:
    match = re.search(
        r'<script id="booth-data" type="application/json">(.*?)</script>', html, re.DOTALL
    )
    assert match, "the page must carry its booth list"
    return json.loads(match.group(1).replace("<\\/", "</"))


# ---------------------------------------------------------------------------
# booth list (shared with the survey page)
# ---------------------------------------------------------------------------


def test_the_aggregate_heading_is_not_offered_for_placement():
    booths = build_map.render(
        _snapshot([_booth("Additional Festival Locations"), _booth("Belgium")])
    )
    assert "Additional Festival Locations" not in _dump_names(booths)


def _dump_names(html: str) -> list[str]:
    return [b["name"] for b in _embedded(html)]


def test_an_empty_snapshot_renders_rather_than_raising():
    assert "Booth Map" in build_map.render({})


def test_coordinates_and_precision_reach_the_page():
    html = build_map.render(
        _snapshot([_booth("Italy", lat=28.3675, lon=-81.5483, precision="anchored")])
    )
    (italy,) = _embedded(html)
    assert italy["latitude"] == 28.3675
    assert italy["longitude"] == -81.5483
    assert italy["precision"] == "anchored"


@pytest.mark.parametrize(
    "hostile_name",
    [
        '</script><script>alert(1)</script>',
        'Brew-Wing Lab </SCRIPT> Sampler',
    ],
)
def test_a_booth_name_cannot_close_the_script_tag(hostile_name):
    html = build_map.render(_snapshot([_booth(hostile_name)]))
    payload = re.search(
        r'<script id="booth-data" type="application/json">(.*?)</script>', html, re.DOTALL
    )
    assert payload, "the closing tag must still be the one the template wrote"
    assert hostile_name not in payload.group(1)
    assert _embedded(html)[0]["name"] == hostile_name


# ---------------------------------------------------------------------------
# map setup
# ---------------------------------------------------------------------------


def test_the_map_centers_on_world_showcase():
    html = build_map.render(_snapshot([_booth("Spain")]))
    assert json.dumps(build_map.DEFAULT_CENTER) in html
    assert f"var ZOOM = {build_map.DEFAULT_ZOOM};" in html


def test_leaflet_and_both_tile_providers_are_present():
    html = build_map.render(_snapshot([_booth("Spain")]))
    assert "leaflet@1.9.4/dist/leaflet.js" in html
    assert "leaflet@1.9.4/dist/leaflet.css" in html
    assert "arcgisonline.com" in html  # satellite tiles
    assert "tile.openstreetmap.org" in html  # street tiles


def test_dropped_pins_are_staged_as_mapped_precision():
    html = build_map.render(_snapshot([_booth("Spain")]))
    assert "location_precision: 'mapped'" in html
