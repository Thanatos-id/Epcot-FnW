from epcot_fw.normalize.text import normalize_name


def test_strips_boilerplate_and_parens():
    assert normalize_name("Bubbles & Brine (NEW)") == "bubbles brine"


def test_case_and_accent_insensitive():
    assert normalize_name("Tangierine Café: Flavors of the Medina") == normalize_name(
        "Tangierine Cafe: Flavors of the Medina"
    )


def test_strips_presented_by():
    assert normalize_name("Eat to the Beat Concert Series Presented by Enterprise") == normalize_name(
        "Eat to the Beat Concert Series"
    )


def test_collapses_whitespace():
    assert normalize_name("  The   Alps  ") == "the alps"


def test_strips_a_price_folded_into_the_name():
    """Some sources put the price in the item name. It is pricing detail, not
    identity - the same drink appears without it on a photo caption, and left
    in, the digits drag an obvious pairing down out of the auto-merge band."""
    assert normalize_name("Frozen Rosé — $9.50") == normalize_name("Frozen Rosé")


def test_strips_serving_sizes_and_multiple_prices():
    assert normalize_name(
        "Stiegl Brewery Goldbräu Austrian Märzen Lager (New) — 6 oz $5.75 / 12 oz $9.75"
    ) == normalize_name("Stiegl Brewery Goldbräu Austrian Märzen Lager")


def test_price_stripping_does_not_eat_ordinary_numbers():
    assert normalize_name("Trio of 3 Cheeses") == "trio of 3 cheeses"


def test_price_stripping_does_not_eat_words_starting_with_a_size_unit():
    assert normalize_name("12 Ounce Ozark Lager") == "ozark lager"
    assert normalize_name("Oaxacan Mole") == "oaxacan mole"
