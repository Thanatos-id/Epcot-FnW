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
