"""Reading the season's "new" mark off a dish, and refusing the one that lies.

The asymmetry these lock down is the whole design of normalize/newness.py:
"(New)" is believed, "NEW!" is stripped but never believed, and the ordinary
English of a menu ("New York Strip") is neither.
"""

import pytest

from epcot_fw.normalize.newness import (
    mentions_new_this_year,
    new_this_year_payload,
    strip_new_marker,
)


@pytest.mark.parametrize(
    "text",
    [
        "Orange-Cardamom Wings (New)",
        "Sun King Brewing Caipirinha Lager, Sarasota, FL (New)",
        "Yalumba 'Y' Viognier ( New)",
        "Dark Chocolate Fondue with Berries, Pound Cake and Meringues (NEW)",
    ],
)
def test_the_parenthesised_mark_is_read_as_new(text):
    assert mentions_new_this_year(text)


@pytest.mark.parametrize(
    "text",
    [
        "NEW! Belgian Waffle",
        "NEW Affogato alle Mandorle Cold Brew",
        "NEW: Wiener Schnitzel",
    ],
)
def test_the_badge_is_not_believed(text):
    """Disney Food Blog hangs "NEW!" on returning dishes - Belgian Waffle and
    Wiener Schnitzel are both in the database wearing it, and AllEars lists
    both with no mark at all. A guest told the Belgian Waffle is new is being
    told something false, so the badge never sets the flag."""
    assert not mentions_new_this_year(text)


@pytest.mark.parametrize(
    "text",
    [
        "New York Strip Steak",
        "New England Clam Chowder",
        "New Zealand Sauvignon Blanc",
        "Newcastle Brown Ale",
        "Freshly Baked New Potatoes",
    ],
)
def test_the_ordinary_word_new_is_not_a_mark(text):
    assert not mentions_new_this_year(text)
    assert strip_new_marker(text) == text


@pytest.mark.parametrize(
    "text",
    [
        # Exactly what DFB writes on the Belgian Waffle, unbalanced parens and all.
        (
            "with cookie butter and whipped cream topped with speculoos cookie "
            "pieces (30th anniversary legacy item (New)"
        ),
        "Pretzel Bread Pudding with Whiskey-Caramel Sauce (30th Anniversary Legacy Item) (New)",
        "Beef Bulgogi (A 30th Anniversary Legacy Item — Reimagined for 2026!) (New)",
    ],
)
def test_a_legacy_note_beats_the_mark(text):
    """The source contradicts itself on these lines - it calls the same dish
    both new and a legacy item. A dish that has been at the festival for
    years is the one to believe."""
    assert not mentions_new_this_year(text)
    assert new_this_year_payload(text) == {}


def test_a_legacy_note_in_a_sibling_text_still_beats_the_mark():
    """The mark and the disclaimer routinely land in different fields once a
    line is split into name and description."""
    assert not mentions_new_this_year("Belgian Waffle (New)", "a 30th anniversary legacy item")


def test_words_that_only_look_like_a_legacy_note_are_left_alone():
    """"Classic" and "Returning" were nearly included here until the corpus
    showed them to be product names."""
    assert mentions_new_this_year("Famille Hugel Classic Pinot Noir (New)")
    assert mentions_new_this_year("CORKCICLE Classic Tumbler (New)")


def test_a_mark_in_any_of_the_texts_counts():
    assert mentions_new_this_year("Amaretto Bellini", "Peach Purée and Prosecco (NEW)")
    assert not mentions_new_this_year("Amaretto Bellini", "Peach Purée and Prosecco")


def test_the_payload_carries_the_flag_only_when_the_mark_is_there():
    """Absence has to stay absence. disney_official outranks every blog that
    writes the mark, so a `False` from a source that simply never writes it
    would bury every `True` from the sources that do."""
    assert new_this_year_payload("Orange-Cardamom Wings (New)") == {"is_new_this_year": True}
    assert new_this_year_payload("Orange-Cardamom Wings") == {}
    assert new_this_year_payload("NEW! Belgian Waffle") == {}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Orange-Cardamom Wings (New)", "Orange-Cardamom Wings"),
        ("Yalumba 'Y' Viognier ( New)", "Yalumba 'Y' Viognier"),
        # The badge comes off a name even though it is not believed: what the
        # dish is called and whether it is new are different questions.
        ("NEW! Belgian Waffle", "Belgian Waffle"),
        ("NEW Affogato alle Mandorle", "Affogato alle Mandorle"),
        ("NEW: Wiener Schnitzel", "Wiener Schnitzel"),
        # Only the mark goes; the dish's own parentheses stay.
        (
            "Plant-based Chicken Tenders (New) (plant-based item)",
            "Plant-based Chicken Tenders (plant-based item)",
        ),
    ],
)
def test_the_mark_comes_off_the_name(raw, expected):
    assert strip_new_marker(raw) == expected


def test_stripping_an_empty_name_is_not_an_error():
    assert strip_new_marker("") == ""
