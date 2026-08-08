from epcot_fw.normalize.text import normalize_name
from epcot_fw.resolve.matcher import Candidate, find_best_match, score_pair


def test_identical_names_score_100():
    assert score_pair("the alps", "the alps") == 100.0


def test_near_duplicate_after_normalization_auto_merges():
    a = normalize_name("Bubbles & Brine (NEW)")
    b = normalize_name("Bubbles & Brine")
    result = find_best_match(a, [Candidate(canonical_id=1, natural_key=b)])
    assert result.outcome == "auto_merge"
    assert result.canonical_id == 1


def test_unrelated_short_names_do_not_false_positive():
    """Regression test: fuzz.WRatio previously scored completely unrelated
    booth names ~85 due to its partial-ratio fallback on differing string
    lengths, which caused legitimate new booths to get incorrectly withheld
    as "review" conflicts instead of being created. token_sort_ratio must
    keep clearly distinct names below the review threshold."""
    a = normalize_name("The Fry Basket")
    candidates = [
        Candidate(canonical_id=1, natural_key=normalize_name("The Noodle Exchange")),
        Candidate(canonical_id=2, natural_key=normalize_name("Refreshment Port hosted by Boursin Cheese")),
    ]
    result = find_best_match(a, candidates)
    assert result.outcome == "new_entity"


def test_no_candidates_is_new_entity():
    result = find_best_match("anything", [])
    assert result.outcome == "new_entity"
    assert result.canonical_id is None
