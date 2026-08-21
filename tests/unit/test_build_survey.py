"""The in-park capture page.

`render()` is pure, so everything except the browser behaviour is testable
here: which booths appear, in what order, and whether the snapshot blob can be
trusted once it is inside a <script> tag.
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools/data_ledger"))

import build_survey  # noqa: E402


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
# which booths make the list
# ---------------------------------------------------------------------------


def test_the_aggregate_heading_is_not_offered_for_capture():
    """"Additional Festival Locations" is a heading covering dishes sold in
    several places at once. There is nowhere to stand, so offering it invites
    a coordinate that means nothing."""
    booths = build_survey.survey_booths(
        _snapshot([_booth("Additional Festival Locations"), _booth("Belgium")])
    )
    assert [b["name"] for b in booths] == ["Belgium"]


def test_booths_without_a_name_are_dropped():
    booths = build_survey.survey_booths(_snapshot([_booth(""), _booth(None), _booth("Spain")]))
    assert [b["name"] for b in booths] == ["Spain"]


def test_an_empty_snapshot_renders_rather_than_raising():
    assert build_survey.survey_booths({}) == []
    assert "Booth Survey" in build_survey.render({})


# ---------------------------------------------------------------------------
# capture order
# ---------------------------------------------------------------------------


def test_unplaced_booths_come_first():
    """The walk exists for the booths with no coordinate; a surveyor holding a
    phone one-handed shouldn't have to hunt for them."""
    booths = build_survey.survey_booths(
        _snapshot(
            [
                _booth("Japan", lat=28.3674, lon=-81.5505, precision="surveyed"),
                _booth("Germany", lat=28.3681, lon=-81.5469, precision="anchored"),
                _booth("The Wedge"),
            ]
        )
    )
    assert [b["name"] for b in booths] == ["The Wedge", "Germany", "Japan"]


def test_ties_break_on_name_so_the_list_holds_still_between_builds():
    booths = build_survey.survey_booths(
        _snapshot([_booth("the fry basket"), _booth("Brazil"), _booth("Coastal Eats")])
    )
    assert [b["name"] for b in booths] == ["Brazil", "Coastal Eats", "the fry basket"]


# ---------------------------------------------------------------------------
# the embedded payload
# ---------------------------------------------------------------------------


def test_coordinates_and_precision_reach_the_page():
    html = build_survey.render(
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
    """Booth names are scraped from someone else's page. JSON quoting alone
    does not save this: the HTML parser ends a <script> at the first `</`
    sequence regardless of what the JSON thinks."""
    html = build_survey.render(_snapshot([_booth(hostile_name)]))
    payload = re.search(
        r'<script id="booth-data" type="application/json">(.*?)</script>', html, re.DOTALL
    )
    assert payload, "the closing tag must still be the one the template wrote"
    assert hostile_name not in payload.group(1)
    assert _embedded(html)[0]["name"] == hostile_name


def test_the_page_is_self_contained_and_sized_for_a_phone():
    html = build_survey.render(_snapshot([_booth("Greece")]))
    assert 'name="viewport"' in html
    assert "http://" not in html.replace("http://www.w3.org", "")
    assert "<script src=" not in html
