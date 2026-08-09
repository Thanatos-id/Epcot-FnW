import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "data_ledger"))

import metrics  # noqa: E402


def _snapshot(booths=None, sources=None, conflicts=None):
    return {
        "festival": {"name": "Test Festival"},
        "booths": booths if booths is not None else [],
        "sources": sources if sources is not None else [],
        "conflicts": conflicts if conflicts is not None else [],
        "runs": [],
    }


def _booth(name="Booth", items=None, image_url=None, review_count=0):
    return {
        "name": name,
        "image_url": image_url,
        "review_count": review_count,
        "items": items if items is not None else [],
    }


# ---------------------------------------------------------------------------
# data_metrics
# ---------------------------------------------------------------------------


def test_data_metrics_on_an_empty_snapshot_is_all_zero():
    assert metrics.data_metrics(_snapshot()) == {
        "booths": 0,
        "menu_items": 0,
        "items_priced": 0,
        "items_with_image": 0,
        "items_tagged": 0,
        "booths_with_menu": 0,
        "booths_with_image": 0,
        "booths_rated": 0,
        "reviews": 0,
        "sources_enabled": 0,
        "open_conflicts": 0,
    }


def test_data_metrics_counts_items_across_booths():
    snap = _snapshot(
        booths=[
            _booth("A", items=[{"price": 5, "tags": ["vegan"]}, {"price": None, "tags": []}]),
            _booth("B", items=[{"price": 9, "tags": []}]),
            _booth("C", items=[]),
        ]
    )
    m = metrics.data_metrics(snap)
    assert m["booths"] == 3
    assert m["menu_items"] == 3
    assert m["items_priced"] == 2
    assert m["items_tagged"] == 1
    assert m["booths_with_menu"] == 2


def test_data_metrics_counts_images_ratings_sources_and_conflicts():
    snap = _snapshot(
        booths=[
            _booth("A", image_url="https://example.test/a.jpg", review_count=3),
            _booth("B", image_url=None, review_count=0),
        ],
        sources=[{"enabled": True}, {"enabled": False}, {"enabled": True}],
        conflicts=[{"entity_type": "booth"}, {"entity_type": "menu_item"}],
    )
    m = metrics.data_metrics(snap)
    assert m["booths_with_image"] == 1
    assert m["booths_rated"] == 1
    assert m["reviews"] == 3
    assert m["sources_enabled"] == 2
    assert m["open_conflicts"] == 2


def test_data_metrics_counts_dishes_that_have_a_photo():
    snap = _snapshot(
        booths=[
            _booth(
                "A",
                items=[
                    {"image_url": "https://ex.test/dish.jpg"},
                    {"image_url": None},
                    {},
                ],
            )
        ]
    )
    m = metrics.data_metrics(snap)
    assert m["menu_items"] == 3
    assert m["items_with_image"] == 1


def test_newly_photographed_dishes_register_as_a_gain():
    rows = {
        r["key"]: r
        for r in metrics.diff_metrics(
            {"menu_items": 180, "items_with_image": 0},
            {"menu_items": 180, "items_with_image": 46},
        )
    }
    assert rows["items_with_image"]["verdict"] == "gain"
    assert rows["items_with_image"]["delta"] == 46
    assert rows["items_with_image"]["current_pct"] == 25.6


def test_data_metrics_tolerates_missing_keys():
    assert metrics.data_metrics({})["booths"] == 0


# ---------------------------------------------------------------------------
# pct
# ---------------------------------------------------------------------------


def test_pct_returns_none_when_there_is_nothing_to_measure():
    assert metrics.pct(0, 0) is None


def test_pct_rounds_to_one_decimal():
    assert metrics.pct(1, 3) == 33.3
    assert metrics.pct(180, 180) == 100.0


# ---------------------------------------------------------------------------
# diff_metrics
# ---------------------------------------------------------------------------


def test_diff_against_no_previous_snapshot_is_a_baseline_not_a_zero_delta():
    current = metrics.data_metrics(_snapshot(booths=[_booth("A", items=[{"price": 5}])]))
    rows = metrics.diff_metrics(None, current)

    assert all(row["delta"] is None for row in rows)
    assert all(row["previous"] is None for row in rows)
    assert all(row["verdict"] == "same" for row in rows)


def test_rising_count_of_a_higher_is_better_metric_is_a_gain():
    rows = {r["key"]: r for r in metrics.diff_metrics({"booths": 30}, {"booths": 32})}
    assert rows["booths"]["delta"] == 2
    assert rows["booths"]["verdict"] == "gain"


def test_falling_count_of_a_higher_is_better_metric_is_a_loss():
    rows = {r["key"]: r for r in metrics.diff_metrics({"menu_items": 180}, {"menu_items": 174})}
    assert rows["menu_items"]["delta"] == -6
    assert rows["menu_items"]["verdict"] == "loss"


def test_more_open_conflicts_is_a_loss_and_fewer_is_a_gain():
    worse = {r["key"]: r for r in metrics.diff_metrics({"open_conflicts": 10}, {"open_conflicts": 14})}
    better = {r["key"]: r for r in metrics.diff_metrics({"open_conflicts": 10}, {"open_conflicts": 4})}
    assert worse["open_conflicts"]["verdict"] == "loss"
    assert better["open_conflicts"]["verdict"] == "gain"


def test_unchanged_metric_is_marked_same():
    rows = {r["key"]: r for r in metrics.diff_metrics({"booths": 32}, {"booths": 32})}
    assert rows["booths"]["delta"] == 0
    assert rows["booths"]["verdict"] == "same"


def test_ratio_metrics_expose_current_and_previous_percentages():
    previous = {"menu_items": 180, "items_priced": 0}
    current = {"menu_items": 180, "items_priced": 90}
    rows = {r["key"]: r for r in metrics.diff_metrics(previous, current)}

    assert rows["items_priced"]["current_pct"] == 50.0
    assert rows["items_priced"]["previous_pct"] == 0.0
    assert rows["items_priced"]["verdict"] == "gain"


def test_ratio_percentage_is_none_when_the_denominator_is_zero():
    rows = {r["key"]: r for r in metrics.diff_metrics(None, {"menu_items": 0, "items_priced": 0})}
    assert rows["items_priced"]["current_pct"] is None


def test_diff_returns_a_row_for_every_declared_metric():
    rows = metrics.diff_metrics(None, {})
    assert [r["key"] for r in rows] == [spec["key"] for spec in metrics.METRIC_SPECS]


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


@pytest.fixture()
def history_path(tmp_path):
    return tmp_path / "ledger_history.json"


def test_load_history_of_a_missing_file_is_empty(history_path):
    assert metrics.load_history(history_path) == []


def test_record_first_snapshot_has_no_previous(history_path):
    snap = _snapshot(booths=[_booth("A")])
    history, current, previous = metrics.record_snapshot(snap, path=history_path)

    assert len(history) == 1
    assert previous is None
    assert current["data"]["booths"] == 1


def test_record_second_distinct_snapshot_exposes_the_first_as_previous(history_path):
    metrics.record_snapshot(_snapshot(booths=[_booth("A")]), path=history_path)
    history, current, previous = metrics.record_snapshot(
        _snapshot(booths=[_booth("A"), _booth("B")]), path=history_path
    )

    assert len(history) == 2
    assert previous is not None
    assert previous["data"]["booths"] == 1
    assert current["data"]["booths"] == 2


def test_rebuilding_without_new_data_does_not_append_a_duplicate_row(history_path):
    snap = _snapshot(booths=[_booth("A")])
    metrics.record_snapshot(snap, path=history_path)
    metrics.record_snapshot(snap, path=history_path)
    history, _, previous = metrics.record_snapshot(snap, path=history_path)

    assert len(history) == 1, "identical metrics must collapse instead of faking a no-change diff"
    assert previous is None


def test_newly_tracked_metric_does_not_masquerade_as_a_data_change(history_path):
    """Adding a metric to METRIC_SPECS must not append a history row: the
    older row simply never measured it, which is not the same as the data
    having moved."""
    snap = _snapshot(booths=[_booth("A")])
    metrics.record_snapshot(snap, path=history_path)

    stored = json.loads(history_path.read_text())
    stored["snapshots"][0]["data"].pop("items_with_image")
    history_path.write_text(json.dumps(stored))

    history, _, previous = metrics.record_snapshot(snap, path=history_path)
    assert len(history) == 1
    assert previous is None


def test_a_real_change_alongside_a_new_metric_still_appends(history_path):
    metrics.record_snapshot(_snapshot(booths=[_booth("A")]), path=history_path)

    stored = json.loads(history_path.read_text())
    stored["snapshots"][0]["data"].pop("items_with_image")
    history_path.write_text(json.dumps(stored))

    history, _, previous = metrics.record_snapshot(
        _snapshot(booths=[_booth("A"), _booth("B")]), path=history_path
    )
    assert len(history) == 2
    assert previous is not None


def test_duplicate_rebuild_refreshes_the_timestamp_of_the_existing_row(history_path):
    snap = _snapshot(booths=[_booth("A")])
    metrics.record_snapshot(snap, recorded_at="2026-01-01T00:00:00+00:00", path=history_path)
    history, current, _ = metrics.record_snapshot(
        snap, recorded_at="2026-02-01T00:00:00+00:00", path=history_path
    )

    assert len(history) == 1
    assert current["recorded_at"] == "2026-02-01T00:00:00+00:00"


def test_duplicate_rebuild_still_preserves_an_earlier_distinct_snapshot(history_path):
    metrics.record_snapshot(_snapshot(booths=[_booth("A")]), path=history_path)
    changed = _snapshot(booths=[_booth("A"), _booth("B")])
    metrics.record_snapshot(changed, path=history_path)
    history, _, previous = metrics.record_snapshot(changed, path=history_path)

    assert len(history) == 2
    assert previous["data"]["booths"] == 1


def test_pipeline_metrics_are_stored_alongside_data_metrics(history_path):
    _, current, _ = metrics.record_snapshot(
        _snapshot(), pipeline={"coverage_pct": 93.0, "tests": 126}, path=history_path
    )
    assert current["pipeline"] == {"coverage_pct": 93.0, "tests": 126}


def test_history_is_written_as_readable_json(history_path):
    metrics.record_snapshot(_snapshot(booths=[_booth("A")]), path=history_path)
    parsed = json.loads(history_path.read_text())
    assert "snapshots" in parsed
    assert isinstance(parsed["snapshots"], list)
