"""Dietary tags inferred from menu copy.

These drive what a guest sees on a dish and, for drinks, which category it
lands in - so a miss on `contains_alcohol` hands someone a cocktail they
thought was a soft drink, and a miss on `contains_nuts` is worse than that.
Every case here came out of the real 2026 menus.
"""

import pytest

from epcot_fw.normalize.dietary_tags import extract_dietary_tags


def tags(*texts):
    return set(extract_dietary_tags(*texts))


# ---------------------------------------------------------------------------
# alcohol: the words a keyword list forgets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # spirits, none of which say "spirit"
        "Boyd & Blair Pomegranate Codder — Vodka, Pomegranate, and Lime",
        "Spiced Apple Rum Old Fashioned with Boyd & Blair Rum",
        "Frozen Waffle Old Fashioned: Maker's Mark Kentucky Straight Bourbon Whisky",
        "Hainan Prosperity — Tequila, Vodka, Orange Juice, and Mango Syrup",
        # a liqueur is not a "liquor"
        "Chilled Belgian Coffee with ChocoLat Deluxe Salted Caramel Chocolate Liqueur",
        # beer styles that never say "beer"
        "Peroni Pilsner",
        "Weihenstephaner Festbier",
        "Schöfferhofer Grapefruit Hefeweizen",
        "Civil Society Brewing Everyday I'm Waffle'n IPA",
        # wine by varietal, which is how a wine list is actually written
        "1000 Stories Bourbon Barrel-Aged Zinfandel",
        "Caymus Vineyards Cabernet Sauvignon",
        "Selbach-Oster Riesling",
        "Zoe Rosé",
        "Saracco Moscato",
        "Jackson-Triggs Reserve Red Blend",
    ],
)
def test_drinks_that_used_to_read_as_non_alcoholic(text):
    assert "contains_alcohol" in tags(text)


def test_an_explicit_disclaimer_beats_every_keyword():
    """A mocktail's description names the spirit it stands in for, and the
    plain version of a spiked cold brew sits next to the spiked one."""
    assert "contains_alcohol" not in tags(
        "Frozen Szarlotka — Frozen Apple Pie flavors with Vanilla (non-alcoholic)"
    )
    assert "contains_alcohol" not in tags("Virgin Mojito with Mint and Lime")
    assert "contains_alcohol" not in tags("Zero-proof Mocktail Flight, alcohol-free")


def test_the_spiked_sibling_still_counts():
    assert "contains_alcohol" in tags(
        "Dolce Affogato Cold Brew with Baileys Original Irish Cream Liqueur"
    )


@pytest.mark.parametrize(
    "text",
    [
        # soft drinks that contain the word "beer"
        "Root Beer Float with Vanilla Ice Cream",
        "Spiced Apple Slushy — Frozen Ginger Beer blended with Lively Lime",
        # in the US, cider without "hard" is apple juice
        "Grilled Cider-brined Pork Tenderloin with Roasted Vegetables",
        "Hot Apple Cider with Cinnamon",
    ],
)
def test_soft_drinks_are_not_dragged_in_by_a_shared_word(text):
    assert "contains_alcohol" not in tags(text)


def test_hard_cider_is_still_caught():
    assert "contains_alcohol" in tags("Keel Farms Goji Berry Citrus Hard Cider")


def test_food_cooked_with_alcohol_is_flagged_because_it_is_still_in_there():
    for text in ("Beer-braised Beef", "Red Wine-braised Beef Short Rib"):
        assert "contains_alcohol" in tags(text)


# ---------------------------------------------------------------------------
# nuts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Pineapple Cheesecake with passion fruit curd and macadamia nuts", True),
        ("Cold Brew topped with Whipped Cream and Toffee Nut Sauce", True),
        ("Pumpkin-Mascarpone Ravioli with hazelnut praline", True),
        ("Amaretto Bellini", True),  # amaretto is an almond liqueur
        ("Chocolate-Pistachio Cookie", True),
        ("Roasted Chestnut Soup", True),
        # words that merely contain the letters
        ("Vanilla-Butternut Squash Purée", False),
        ("Coconut-Chili Sauce", False),
        ("Pumpkin Spice Doughnut with Nutmeg", False),
        ("Stir-fried Water Chestnuts and Snow Peas", False),
    ],
)
def test_nut_detection(text, expected):
    assert ("contains_nuts" in tags(text)) is expected


# ---------------------------------------------------------------------------
# the positive claims stay conservative
# ---------------------------------------------------------------------------


def test_dietary_claims_are_only_made_when_the_source_makes_them():
    """Asserting "vegan" from ingredients we happen to recognise would be
    inventing a claim the source never made."""
    assert tags("Edamame Dumplings with Butternut Squash Purée and Sage") == set()
    assert "plant_based" in tags("Edamame Dumplings (plant-based)")
    assert "vegan" in tags("Vegan Chocolate Mousse")
    assert "gluten_free" in tags("Gluten-Friendly Brownie")


def test_no_text_yields_no_tags():
    assert extract_dietary_tags() == []
    assert extract_dietary_tags("", None) == []


# ---------------------------------------------------------------------------
# shellfish
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Crab Cake with Tropical Fruit Chutney", True),
        ("Gulf Coast-style Seafood Roll with Warm-Water Lobster, Rock Shrimp", True),
        ("Seafood Pot Pie with Shrimp, Scallops, and Lobster Bisque", True),
        ("Moqueca de Camarão: Plancha-seared Shrimp in Coconut Milk Broth", True),
        ("Seafood Salad with Bay Scallops, Mussels, Olive Oil", True),
        # Molluscs a guest avoiding shellfish would not expect to meet.
        ("Trio d'Escargots, Garniture a l'ail et au Persil", True),
        ("Grilled Octopus with Salsa Verde", True),
        # Nothing shellfish about these.
        ("Beijing Zhajiang Noodles with Stir-fried Minced Beef", False),
        ("Pão de Queijo: Brazilian Cheese Bread", False),
        ("Crab Apple Cider Doughnut", True),  # "crab" alone is enough; a miss costs more
    ],
)
def test_shellfish_detection(text, expected):
    assert ("contains_shellfish" in tags(text)) is expected


# ---------------------------------------------------------------------------
# heat by name, not just the word "spicy"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Seoul, South Korea Bo Ssam Pork Poutine with Gochujang Gravy, Kimchi", True),
        ("Spiced Flank Steak Hummus Bowl with Harissa Yogurt", True),
        ("BBQ Braai Chicken Pizza with Piri Piri Sauce", True),
        ("Taco de Camaron with Chipotle Aïoli", True),
        ("Berry Ice Pop topped with Chili-Lime Seasoning", True),
        ("Mango-Apple Fruit Pearl with Wasabi-Soy Sauce", True),
        ("Unnecessarily Spicy Carolina Reaper Pepper-Curry Wings", True),
        # The ham, not the pepper - this menu says "Jamón Serrano" far more
        # often than it says the chile, and the bare word filed it as spicy.
        ("Croquetas de Jamón with Saffron Aïoli and Shaved Jamón Serrano", False),
        ("Freshly Baked Carrot Cake with Cream Cheese Frosting", False),
    ],
)
def test_heat_detection(text, expected):
    assert ("spicy" in tags(text)) is expected


def test_gluten_friendly_survives_the_separator_the_menus_actually_use():
    """The 2026 menus write "(Gluten/ Wheat Friendly)" - a slash AND a space.
    A single optional separator matched the slash and then failed on the
    space, so every gluten-friendly dish was invisible to the one filter
    people search *for*."""
    assert "gluten_free" in tags("Pão de Queijo: Brazilian cheese bread (Gluten/ Wheat Friendly)")
    assert "gluten_free" in tags("Paella with Rice, Chorizo, and Shrimp (Gluten/Wheat Friendly)")
    assert "gluten_free" in tags("Griddled Cheese (Gluten / Wheat Friendly)")
    assert "gluten_free" in tags("Gluten-Free Brownie")


def test_cachaca_is_a_spirit():
    """Brazil's own, and what the Frozen Caipirinha is built on - missing from
    the spirit list, so the drink read as soft."""
    assert "contains_alcohol" in tags("Frozen Caipirinha with Cachaça")
    assert "contains_alcohol" in tags("Frozen Caipirinha with Cachaca Spirit")
