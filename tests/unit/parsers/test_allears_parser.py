from pathlib import Path

from epcot_fw.sources.allears import AllEarsAdapter

FIXTURE = (
    Path(__file__).parent.parent.parent / "fixtures/html_snapshots/allears/booth_menus_hub.html"
)


def test_extracts_many_booths_and_menu_items():
    html = FIXTURE.read_text()
    records = AllEarsAdapter().parse(
        html, "https://allears.net/epcot-international-food-and-wine-festival-menus-and-food-photos/", "booth_list"
    )
    booths = [r for r in records if r.entity_type == "booth"]
    items = [r for r in records if r.entity_type == "menu_item"]

    assert len(booths) > 25
    assert len(items) > 100
    assert any(b.payload["name"] == "The Alps" for b in booths)


def test_name_split_across_two_strong_tags_is_reassembled():
    """Regression test: "Germany" is authored on this page as
    `<strong><a name="germany"/>G</strong><strong>ermany</strong>` - two
    sibling <strong> tags. Reading only the first <strong> previously
    truncated the name to "G"."""
    html = FIXTURE.read_text()
    records = AllEarsAdapter().parse(html, "https://example.test", "booth_list")
    names = [r.payload["name"] for r in records if r.entity_type == "booth"]
    assert "Germany" in names
    assert "G" not in names


def test_orphaned_return_to_top_anchor_is_not_read_as_a_booth():
    """Regression test: one boundary paragraph on this page is
    `<p><a href="#top">RETURN TO TOP</a><strong><a name="mac"></a></strong></p>`
    - an orphaned anchor with no real name text. Reading get_text() on the
    whole <p> previously picked up "RETURN TO TOP" as a fabricated booth."""
    html = FIXTURE.read_text()
    records = AllEarsAdapter().parse(html, "https://example.test", "booth_list")
    names = [r.payload["name"].upper() for r in records if r.entity_type == "booth"]
    assert "RETURN TO TOP" not in names


def test_extracts_booth_menu_board_image():
    html = FIXTURE.read_text()
    records = AllEarsAdapter().parse(html, "https://example.test", "booth_list")
    alps = next(r for r in records if r.entity_type == "booth" and r.payload["name"] == "The Alps")
    assert alps.payload["image_url"] == (
        "https://allears.net/wp-content/uploads/2022/07/"
        "2022-wdw-epcot-food-and-wine-festival-the-alps-booth-menu.jpg"
    )


def test_image_is_none_when_no_figure_precedes_menu_content():
    """A booth's image lookup must stop at the "Food Items:"/"Beverages:"
    label rather than wandering into a later, unrelated photo (e.g. the
    "full spread" shot each section also has after its menu lists)."""
    html = FIXTURE.read_text()
    records = AllEarsAdapter().parse(html, "https://example.test", "booth_list")
    booths_without_menus = [
        r for r in records if r.entity_type == "booth" and r.payload["name"] in ("Joffrey’s Coffee",)
    ]
    assert booths_without_menus
    assert booths_without_menus[0].payload["image_url"] is None


def test_alps_items_link_to_correct_booth_and_categorize_beverages():
    html = FIXTURE.read_text()
    records = AllEarsAdapter().parse(html, "https://example.test", "booth_list")
    alps_items = [
        r for r in records if r.entity_type == "menu_item" and r.payload["booth_name"] == "The Alps"
    ]
    assert len(alps_items) >= 3
    categories = {item.payload["category"] for item in alps_items}
    assert "food" in categories
    assert categories & {"alcoholic_beverage", "non_alcoholic_beverage"}
