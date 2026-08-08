from pathlib import Path

from epcot_fw.sources.disney_food_blog import DisneyFoodBlogAdapter

FIXTURE = (
    Path(__file__).parent.parent.parent
    / "fixtures/html_snapshots/disney_food_blog/booth_menus_hub.html"
)


def test_extracts_booths_and_priced_menu_items():
    html = FIXTURE.read_text()
    records = DisneyFoodBlogAdapter().parse(
        html,
        "https://www.disneyfoodblog.com/2025-epcot-food-and-wine-festival-booths-menus-and-food-photos/",
        "booth_list",
    )
    booths = [r for r in records if r.entity_type == "booth"]
    items = [r for r in records if r.entity_type == "menu_item"]

    assert len(booths) > 25
    assert len(items) > 50

    priced = [item for item in items if item.payload["price_usd"]]
    # Disney Food Blog reliably publishes a $ price for every menu line -
    # this is what makes it worth a higher source priority for price_usd.
    assert len(priced) == len(items)
