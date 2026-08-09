from epcot_fw.cli.main import _parse_keys


def test_parse_keys_returns_none_for_no_input():
    assert _parse_keys(None) is None
    assert _parse_keys("") is None


def test_parse_keys_splits_and_strips_comma_separated_values():
    assert _parse_keys("allears, disney_official ,wdwmagic") == ["allears", "disney_official", "wdwmagic"]


def test_parse_keys_single_value():
    assert _parse_keys("allears") == ["allears"]
