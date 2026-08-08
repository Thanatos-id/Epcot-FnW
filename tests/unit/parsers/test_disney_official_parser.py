from pathlib import Path

from epcot_fw.sources.disney_official import DisneyOfficialAdapter

FIXTURE = (
    Path(__file__).parent.parent.parent
    / "fixtures/html_snapshots/disney_official/festival_overview.html"
)


def test_extracts_festival_name_and_dates():
    html = FIXTURE.read_text()
    records = DisneyOfficialAdapter().parse(
        html,
        "https://disneyworld.disney.go.com/events-tours/epcot/epcot-international-food-and-wine-festival/",
        "festival_overview",
    )
    festivals = [r for r in records if r.entity_type == "festival"]
    assert len(festivals) == 1
    payload = festivals[0].payload
    assert "Food & Wine" in payload["name"]
    assert payload["start_date"] and payload["end_date"]
    assert payload["start_date"] < payload["end_date"]


def test_no_booths_while_placeholder_copy_is_live():
    """As of this fixture's capture, the live page shows a "check back soon"
    placeholder instead of real booth listings - the parser should not
    fabricate booth records from that placeholder."""
    html = FIXTURE.read_text()
    records = DisneyOfficialAdapter().parse(html, "https://example.test", "festival_overview")
    booths = [r for r in records if r.entity_type == "booth"]
    assert booths == []
