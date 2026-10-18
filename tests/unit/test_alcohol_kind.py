"""beer | wine | liquor | cider, and the order that keeps them apart."""

import pytest

from epcot_fw.normalize.alcohol_kind import alcohol_kind_payload, classify_alcohol


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Cider first, or the brewery that made it would claim it for beer.
        ("3 Daughters Brewing Apple Strudel Hard Cider", "cider"),
        ("Coppertail Brewing Co. Cherry Cola Hard Cider", "cider"),
        ("Hard Cider Flight", "cider"),
        # Wine before beer, so a barrel does not decide it.
        ("1000 Stories Bourbon Barrel-Aged Zinfandel", "wine"),
        ("Bulletin Place Sauvignon Blanc, Riverina", "wine"),
        ("Schlumberger Klassik Brut, Weinviertel, Austria", "wine"),
        ("Mimosa Flight", "wine"),
        # Beer by style, and by the people who brew it.
        ("Allagash Brewing Company Haunted House Hoppy Dark Ale", "beer"),
        ("Beer Flight", "beer"),
        ("Brouwerij St. Bernardus Watou Blond Ale", "beer"),
        # Liquor last: a cocktail lists its spirits and its mixers.
        ("Frozen Caipirinha with Cachaça", "liquor"),
        ("Spiced Apple Mule with Iceberg Canadian Vodka", "liquor"),
        ("Summer in Spain: Frozen Lemonade with Yellow Chartreuse Liqueur", "liquor"),
        ("Kirinzan Lemonade Sake", "liquor"),
        # A beer style beats a wine word: these four read wrong until it did.
        ("Schöfferhofer Orange Spritz Hefeweizen", "beer"),
        ("Parish Brewing Co. SIPS Cabernet Franc Strawberry Berliner Weisse", "beer"),
        # Ginger beer and ginger ale are mixers, not beer.
        ("Spiced Apple Mule: Frozen Ginger Beer with Iceberg Canadian Vodka", "liquor"),
        ("Frozen Apple Blossom: Apple Cider, Ginger Ale, Hartley Apple VSOP Brandy", "liquor"),
        ("Strawberry Beer Float", "beer"),
    ],
)
def test_classification(text, expected):
    assert classify_alcohol(text) == expected


def test_a_drink_the_copy_does_not_identify_gets_no_guess():
    assert classify_alcohol("Château des Charmes Pétales Rouge") == "wine"  # château
    assert classify_alcohol("Something Entirely Unlabelled") is None


def test_only_alcoholic_drinks_are_classified():
    """A cake named after a spirit is still a cake, and beef braised in beer
    is still beef."""
    assert alcohol_kind_payload("food", "Kirschwasser Torte") == {}
    assert alcohol_kind_payload("food", "Beer-braised Beef") == {}
    assert alcohol_kind_payload("non_alcoholic_beverage", "Chilled Belgian Coffee") == {}
    assert alcohol_kind_payload("alcoholic_beverage", "Beer Flight") == {"alcohol_kind": "beer"}


def test_nothing_identifiable_yields_no_key():
    assert alcohol_kind_payload("alcoholic_beverage", "Mystery Pour") == {}
