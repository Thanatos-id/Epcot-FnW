"""Sweet, savoury, both, or neither.

The guards are most of the value here: this menu is full of words that mean
dessert in one dish and dinner in the next.
"""

import pytest

from epcot_fw.normalize.flavour import extract_flavour_tags, flavour_payload


def tags(*texts):
    return set(extract_flavour_tags(*texts))


@pytest.mark.parametrize(
    "text",
    [
        "Freshly Baked Carrot Cake with Cream Cheese Icing",
        "Smoked Chocolate Bread Pudding with chocolate ganache",
        "Liquid Nitrogen Almond Truffle Mousse",
        "Pumpkin Cheesecake Mousse Trifle",
        "Cannoli Milk Shake",
        "Lemon-Almond-Olive Oil Cake with Whipped Greek Yogurt Panna Cotta",
    ],
)
def test_desserts_read_sweet_and_not_savoury(text):
    assert tags(text) == {"sweet"}


@pytest.mark.parametrize(
    "text",
    [
        "Beer-braised Beef served with smoked gouda mashed potatoes",
        "Crab Cake with Tropical Fruit Chutney and Mustard Sauce",
        "Seafood Pot Pie with Shrimp, Scallops, and Lobster Bisque",
        "Tartiflette: Potatoes Gratin, Caramelized Onions, Bacon, Thyme",
        "Zwiebelkuchen: German Onion Cake with Caramelized Onions, Bacon, and a Savory Custard",
        "Potato Pierogi with Kielbasa, Caramelized Onions",
    ],
)
def test_dinner_reads_savoury_and_not_sweet(text):
    """Every one of these tripped the sweet list before its guard existed:
    a crab *cake*, a pot *pie*, an onion *cake*, *caramelised* onions, and a
    custard the menu itself calls savoury."""
    assert tags(text) == {"savory"}


def test_sweet_potato_is_a_vegetable():
    assert tags("Sweet Potato Mealie Pap with a Stew of Beans and Peppers") == {"savory"}
    assert tags("Berbere-spiced Beef Stew with Sweet Potato Mealie Pap") == {"savory"}


@pytest.mark.parametrize(
    "text",
    [
        "Fry Flight: Sea Salt Fries / Sweet Potato Casserole Fries with candied pecans",
        "Sweet Chile-Lime Plant-based Chicken Strips",
        "Brûléed Sweet Potatoes with Dried Cranberries, Walnut Streusel, and Orange Goat Cheese",
    ],
)
def test_a_dish_can_honestly_be_both(text):
    assert tags(text) == {"sweet", "savory"}


@pytest.mark.parametrize(
    "text",
    [
        "3 Daughters Brewing Beach Blonde Ale",
        "Bulletin Place Sauvignon Blanc, Riverina",
        "Allagash Brewing Company Haunted House Hoppy Dark Ale",
    ],
)
def test_most_drinks_are_neither(text):
    """A dry white and a hoppy ale are not sweet and not savoury, and
    pretending otherwise would fill a 'sweet drinks' filter with wine."""
    assert tags(text) == set()


def test_the_payload_is_omitted_when_nothing_matched():
    assert flavour_payload("Pumpkin Cheesecake") == {"flavor_tags": ["sweet"]}
    assert flavour_payload("Bulletin Place Sauvignon Blanc") == {}
    assert flavour_payload() == {}
