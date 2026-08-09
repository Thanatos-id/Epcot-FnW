import datetime
from decimal import Decimal

from epcot_fw.resolve.priority import FieldCandidate, resolve_field


def _cand(ref, source_id, priority_rank, observed_at, value):
    return FieldCandidate(
        ref=ref,
        source_id=source_id,
        priority_rank=priority_rank,
        observed_at=observed_at,
        value=value,
    )


def test_no_candidates_returns_empty_resolution():
    result = resolve_field("category", [])
    assert result.value is None
    assert result.has_disagreement is False
    assert result.winner_refs == []


def test_default_strategy_picks_lowest_priority_rank():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    candidates = [
        _cand("a", source_id=1, priority_rank=2, observed_at=now, value="from rank 2"),
        _cand("b", source_id=2, priority_rank=1, observed_at=now, value="from rank 1"),
    ]
    result = resolve_field("category", candidates)
    assert result.value == "from rank 1"
    assert result.winner_refs == ["b"]


def test_most_recent_strategy_picks_latest_observed_at():
    early = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    late = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
    candidates = [
        _cand("a", source_id=1, priority_rank=1, observed_at=early, value=Decimal("10.00")),
        _cand("b", source_id=2, priority_rank=2, observed_at=late, value=Decimal("12.00")),
    ]
    result = resolve_field("price_usd", candidates)
    assert result.value == Decimal("12.00")
    assert result.winner_refs == ["b"]


def test_union_strategy_merges_lists_deduplicated_preserving_first_occurrence_order():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    candidates = [
        _cand("a", source_id=1, priority_rank=1, observed_at=now, value=["vegan", "gluten_free"]),
        _cand("b", source_id=2, priority_rank=2, observed_at=now, value=["gluten_free", "vegetarian"]),
    ]
    result = resolve_field("dietary_tags", candidates)
    assert result.value == ["vegan", "gluten_free", "vegetarian"]
    assert result.has_disagreement is False
    assert result.winner_refs == ["a", "b"]


def test_union_strategy_handles_none_and_empty_values():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    candidates = [
        _cand("a", source_id=1, priority_rank=1, observed_at=now, value=None),
        _cand("b", source_id=2, priority_rank=2, observed_at=now, value=[]),
    ]
    result = resolve_field("dietary_tags", candidates)
    assert result.value == []
    assert result.has_disagreement is False


def test_single_candidate_never_disagrees():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    candidates = [_cand("a", source_id=1, priority_rank=1, observed_at=now, value="Pork Belly")]
    result = resolve_field("category", candidates)
    assert result.has_disagreement is False


def test_string_candidates_disagree_when_values_differ():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    candidates = [
        _cand("a", source_id=1, priority_rank=1, observed_at=now, value="food"),
        _cand("b", source_id=2, priority_rank=2, observed_at=now, value="beverage"),
    ]
    result = resolve_field("category", candidates)
    assert result.has_disagreement is True
    assert result.value == "food"


def test_string_candidates_agree_when_values_match():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    candidates = [
        _cand("a", source_id=1, priority_rank=1, observed_at=now, value="food"),
        _cand("b", source_id=2, priority_rank=2, observed_at=now, value="food"),
    ]
    result = resolve_field("category", candidates)
    assert result.has_disagreement is False


def test_string_disagreement_ignores_none_values():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    candidates = [
        _cand("a", source_id=1, priority_rank=1, observed_at=now, value="food"),
        _cand("b", source_id=2, priority_rank=2, observed_at=now, value=None),
    ]
    result = resolve_field("category", candidates)
    assert result.has_disagreement is False


def test_numeric_candidates_within_threshold_do_not_disagree():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    candidates = [
        _cand("a", source_id=1, priority_rank=1, observed_at=now, value=Decimal("10.00")),
        _cand("b", source_id=2, priority_rank=2, observed_at=now, value=Decimal("11.00")),
    ]
    result = resolve_field("category", candidates)
    assert result.has_disagreement is False


def test_numeric_candidates_beyond_threshold_disagree():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    candidates = [
        _cand("a", source_id=1, priority_rank=1, observed_at=now, value=Decimal("10.00")),
        _cand("b", source_id=2, priority_rank=2, observed_at=now, value=Decimal("15.00")),
    ]
    result = resolve_field("category", candidates)
    assert result.has_disagreement is True


def test_numeric_disagreement_when_winner_is_zero_and_others_are_not():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    candidates = [
        _cand("a", source_id=1, priority_rank=1, observed_at=now, value=0),
        _cand("b", source_id=2, priority_rank=2, observed_at=now, value=5),
    ]
    result = resolve_field("category", candidates)
    assert result.value == 0
    assert result.has_disagreement is True


def test_numeric_no_disagreement_when_all_zero():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    candidates = [
        _cand("a", source_id=1, priority_rank=1, observed_at=now, value=0),
        _cand("b", source_id=2, priority_rank=2, observed_at=now, value=0),
    ]
    result = resolve_field("category", candidates)
    assert result.has_disagreement is False
