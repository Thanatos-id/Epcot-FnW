"""Matching Foodie Guide photos to a researched festival's dishes.

The fixtures are cut down from the real 2025 and 2024 guides, including the
three ways the real ones misbehave: a photo labelled with another booth's
dish, a photo filed above the neighbouring booth's heading, and an alt text
that drops a word of the dish's name.
"""

import json

from epcot_fw.pipeline.festival_photos import VIA, apply_photos, match_photos, parse_guide

GUIDE_2025 = """
<main><article>
<img src="https://example.test/header.jpg" alt="Disney Eats: Foodie Guide">
<h2>World Showcase</h2>
<img src="https://example.test/tostada.jpg" alt="Tostada de Carne: Braised beef tips">
<img src="https://example.test/tamale.jpg" alt="Plant-based Chorizo Tamale with plant-based cotija">
<h3>Las Posadas Holiday Kitchen Menu</h3>
<img src="https://example.test/fondue.jpg" alt="Cheese Fondue in a bread bowl with steamed baby vegetables">
<h3>Bavaria Holiday Kitchen Menu</h3>
<img src="https://example.test/sundae.jpg" alt="Apple Pie Sundae: Apple pie filling">
<img src="https://example.test/slush.jpg" alt="Apple Pie Frozen Slush: Frozen apple juice">
<h3>Fife and Drum Menu</h3>
<h3>Block &amp; Hans Menu</h3>
<img src="https://example.test/waffle.jpg" alt="Holiday Sweater Liege Waffle: Chocolate-coated">
<h3>Connections Café Menu</h3>
<img src="https://example.test/shake.jpg" alt="Gingerbread Milk Shake with whipped cream vodka">
<h3>Experimental Prototype Cookies of Tomorrow Menu</h3>
<img src="https://example.test/chorizo.jpg" alt="Plant-based Chorizo Tamale with plant-based cotija">
<h3>Nochebuena Cocina Menu</h3>
<img src="https://example.test/related.jpg" alt="Some other foodie guide">
<img src="https://example.test/icon.svg" alt="icon">
</article></main>
"""

GUIDE_2024 = """
<main>
<img src="https://example.test/2024-group.jpg" alt="Las Posadas Holiday Kitchen Food - 2024 Menus">
<h3>World Showcase</h3>
<h4>NEW! Las Posadas Holiday Kitchen Menu</h4>
<img src="https://example.test/2024-tostada.jpg" alt="Tostada de Carne">
<img src="https://example.test/2024-tamal.jpg" alt="Tamal de Pollo con Mole">
<h4>Las Posadas Holiday Kitchen Menu</h4>
</main>
"""

BOOTHS = [
    "Las Posadas Holiday Kitchen", "Bavaria Holiday Kitchen", "Fife and Drum", "Block & Hans",
    "Connections Café & Eatery", "Experimental Prototype Cookies of Tomorrow", "Nochebuena Cocina",
]


def _dish(booth, name, **kw):
    return {"booth_name": booth, "name": name, "category": "food", **kw}


def _menu():
    return [
        _dish("Las Posadas Holiday Kitchen", "Tostada de Carne"),
        _dish("Las Posadas Holiday Kitchen", "Tamal de Pollo con Mole"),
        _dish("Bavaria Holiday Kitchen", "Cheese Fondue"),
        _dish("Fife and Drum", "Apple Pie Sundae"),
        _dish("Block & Hans", "Apple Pie Frozen Slush"),
        _dish("Block & Hans", "Apple Pie Frozen Slush with Apple Pie Moonshine"),
        _dish("Connections Café & Eatery", "Figment Holiday Sweater Liège Waffle"),
        _dish("Experimental Prototype Cookies of Tomorrow", "Gingerbread Milk Shake"),
        _dish("Experimental Prototype Cookies of Tomorrow", "Gingerbread Milk Shake with Whipped Cream Vodka"),
        _dish("Nochebuena Cocina", "Plant-based Chorizo Tamale"),
    ]


def _matched(html=GUIDE_2025, menu=None):
    matches, near, none = match_photos(parse_guide(html), menu or _menu(), BOOTHS)
    return {(i["booth_name"], i["name"]): p.url.rsplit("/", 1)[-1] for p, i, _ in matches}, near, none


def test_each_photo_is_read_as_belonging_to_the_menu_heading_after_it():
    photos = parse_guide(GUIDE_2025)
    by_url = {p.url.rsplit("/", 1)[-1]: p.heading for p in photos}
    assert by_url["tostada.jpg"] == "Las Posadas Holiday Kitchen"
    assert by_url["chorizo.jpg"] == "Nochebuena Cocina"
    # Before the first menu: the header. After the last: related posts. SVG: icons.
    assert by_url["header.jpg"] == "Las Posadas Holiday Kitchen"
    assert "related.jpg" not in by_url and "icon.svg" not in by_url


def test_an_older_layout_with_deeper_headings_and_new_prefixes_still_parses():
    headings = {p.url.rsplit("/", 1)[-1]: p.heading for p in parse_guide(GUIDE_2024)}
    assert headings["2024-group.jpg"] == "Las Posadas Holiday Kitchen"
    assert headings["2024-tamal.jpg"] == "Las Posadas Holiday Kitchen"


def test_dish_names_are_found_through_the_descriptions_after_them():
    matched, _, _ = _matched()
    assert matched[("Las Posadas Holiday Kitchen", "Tostada de Carne")] == "tostada.jpg"
    assert matched[("Bavaria Holiday Kitchen", "Cheese Fondue")] == "fondue.jpg"


def test_an_alt_that_drops_a_word_of_the_name_still_matches():
    matched, _, _ = _matched()
    assert matched[("Connections Café & Eatery", "Figment Holiday Sweater Liège Waffle")] == "waffle.jpg"


def test_the_spirited_drink_gets_the_photo_that_names_it_in_full():
    matched, _, _ = _matched()
    assert matched[("Experimental Prototype Cookies of Tomorrow",
                    "Gingerbread Milk Shake with Whipped Cream Vodka")] == "shake.jpg"
    assert ("Experimental Prototype Cookies of Tomorrow", "Gingerbread Milk Shake") not in matched


def test_a_photo_filed_under_the_neighbouring_heading_finds_its_dish():
    matched, _, _ = _matched()
    assert matched[("Block & Hans", "Apple Pie Frozen Slush")] == "slush.jpg"
    assert matched[("Fife and Drum", "Apple Pie Sundae")] == "sundae.jpg"


def test_a_mislabelled_photo_never_beats_the_dish_s_own_photo():
    """2025 put the chorizo tamale's alt on Las Posadas' photo, ahead of the real one."""
    matched, near, _ = _matched()
    assert matched[("Nochebuena Cocina", "Plant-based Chorizo Tamale")] == "chorizo.jpg"
    assert ("Las Posadas Holiday Kitchen", "Tamal de Pollo con Mole") not in matched
    assert any("tamale" in line.lower() for line in near)


def test_a_booth_group_shot_is_never_taken_for_a_dish():
    matched, _, none = _matched(GUIDE_2024)
    assert "2024-group.jpg" not in matched.values()
    assert any("Kitchen Food" in line for line in none)


def _festival(tmp_path, menu):
    (tmp_path / "menu_items.json").write_text(json.dumps({"menu_items": menu}))
    (tmp_path / "booths.json").write_text(json.dumps({"booths": [{"name": n} for n in BOOTHS]}))
    return tmp_path


def _pages():
    return [
        {"url": "https://example.test/guide-2024", "season": 2024},
        {"url": "https://example.test/guide-2025", "season": 2025},
    ]


def _fetch(url):
    return GUIDE_2025 if url.endswith("2025") else GUIDE_2024


def _items(directory):
    return {i["name"]: i for i in json.loads((directory / "menu_items.json").read_text())["menu_items"]}


def test_the_newest_guide_wins_and_the_photo_is_credited(tmp_path):
    directory = _festival(tmp_path, _menu())
    report = apply_photos(directory, _pages(), _fetch)
    tostada = _items(directory)["Tostada de Carne"]
    assert tostada["image_url"] == "https://example.test/tostada.jpg"
    assert tostada["image_source"]["season"] == 2025
    assert tostada["image_source"]["via"] == VIA
    # 2024 only fills what 2025 left empty.
    assert _items(directory)["Tamal de Pollo con Mole"]["image_url"] == "https://example.test/2024-tamal.jpg"
    assert report.pages == ["https://example.test/guide-2025", "https://example.test/guide-2024"]


def test_a_photo_someone_chose_is_never_replaced(tmp_path):
    menu = _menu()
    menu[0]["image_url"] = "https://thanatos-id.github.io/Epcot-FnW/dish-photos/abc.jpg"
    directory = _festival(tmp_path, menu)
    apply_photos(directory, _pages(), _fetch)
    assert _items(directory)["Tostada de Carne"]["image_url"].endswith("/dish-photos/abc.jpg")


def test_its_own_older_photo_gives_way_to_a_newer_season(tmp_path):
    menu = _menu()
    menu[0]["image_url"] = "https://example.test/2023-tostada.jpg"
    menu[0]["image_source"] = {"via": VIA, "season": 2023}
    directory = _festival(tmp_path, menu)
    report = apply_photos(directory, _pages(), _fetch)
    assert _items(directory)["Tostada de Carne"]["image_url"] == "https://example.test/tostada.jpg"
    assert [r.item_name for r in report.replaced] == ["Tostada de Carne"]


def test_a_dry_run_writes_nothing(tmp_path):
    directory = _festival(tmp_path, _menu())
    before = (directory / "menu_items.json").read_text()
    report = apply_photos(directory, _pages(), _fetch, dry_run=True)
    assert report.matched
    assert (directory / "menu_items.json").read_text() == before


GUIDE_CARDS = """
<main>
<div><img src="https://example.test/banner.jpg" alt="Foodie Guide banner"></div>
<h2>World Celebration</h2>
<p class="p01"><strong>Florida Fresh Menu</strong></p>
<p><em>Available March 4 through May 25</em><br><strong>Location: </strong>CommuniCore Plaza</p>
<div class="card-container"><div class="card-image"><img src="https://example.test/conch.jpg" alt="Conch Fritters with Key Lime aioli"></div>
  <div class="content-container"><h4>Conch Fritters</h4><p>with Key Lime aioli</p></div></div>
<div class="card-container"><div class="card-image"><img src="https://example.test/conch.jpg" alt="Conch Fritters with Key Lime aioli"></div>
  <div class="content-container"><h4>Conch Fritters</h4><p>with Key Lime aioli</p></div></div>
<p class="p01"><strong>Nectar hosted by AdventHealth Menu</strong></p>
<div class="card-container"><img src="https://example.test/panna.jpg" alt="A dessert">
  <h4>🥕Coconut Panna Cotta</h4><p>with a cherry gelée</p></div>
<div id="KidsPicks"></div>
<p><strong>Florida Fresh</strong></p>
<div class="card-container"><img src="https://example.test/kids.jpg" alt="Kids plate"><h4>Conch Fritters</h4></div>
</main>
"""


def test_a_card_layout_reads_each_dish_from_its_own_card():
    photos = {p.url.rsplit("/", 1)[-1]: p for p in parse_guide(GUIDE_CARDS)}
    assert photos["conch.jpg"].heading == "Florida Fresh"
    assert photos["conch.jpg"].alt == "Conch Fritters"
    # The card's title beats a vague alt text, and loses its stroll emoji.
    assert photos["panna.jpg"].alt == "Coconut Panna Cotta"
    assert photos["panna.jpg"].heading == "Nectar hosted by AdventHealth"


def test_a_photo_repeated_for_phones_is_taken_once_and_kids_picks_are_skipped():
    urls = [p.url for p in parse_guide(GUIDE_CARDS)]
    assert urls.count("https://example.test/conch.jpg") == 1
    assert "https://example.test/kids.jpg" not in urls


ARCHIVED_PAGE = "https://web.archive.org/web/20250207090202/https://disneyparksblog.com/wdw/guide-2025/"
ARCHIVED_HTML = """
<main>
<img src="/web/20250207090202im_/https://disneyparksblog.com/app/uploads/2025/01/tostada.jpg" alt="Tostada de Carne">
<h3>Las Posadas Holiday Kitchen Menu</h3>
</main>
"""


def _archived(tmp_path, live):
    directory = _festival(tmp_path, _menu())
    apply_photos(directory, [{"url": ARCHIVED_PAGE, "season": 2025}], lambda url: ARCHIVED_HTML,
                 image_is_live=lambda url: live)
    return _items(directory)["Tostada de Carne"]


def test_an_archived_guide_links_disney_s_original_photo_while_it_is_live(tmp_path):
    tostada = _archived(tmp_path, live=True)
    assert tostada["image_url"] == "https://disneyparksblog.com/app/uploads/2025/01/tostada.jpg"
    source = tostada["image_source"]
    assert source["credit"] == "Disney Parks Blog"
    assert source["page_url"] == "https://disneyparksblog.com/wdw/guide-2025/"
    assert source["archived_at"] == ARCHIVED_PAGE


def test_an_archived_guide_falls_back_to_the_archive_s_copy_when_the_original_is_gone(tmp_path):
    tostada = _archived(tmp_path, live=False)
    assert tostada["image_url"].startswith("https://web.archive.org/web/20250207090202im_/")
    assert tostada["image_source"]["credit"] == "Disney Parks Blog"
