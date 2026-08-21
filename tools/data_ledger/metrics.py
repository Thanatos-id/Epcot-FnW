"""Data-quality metrics for the ledger, plus the snapshot history that lets
each build show what was gained and lost since the previous one.

The ledger used to render a single point-in-time snapshot with no memory, so
there was no way to tell whether a refresh had improved coverage (prices
finally published, a booth's menu appearing) or regressed it (a source going
dark and taking its menu items with it). `ledger_history.json` keeps one
compact metrics row per snapshot - aggregate counts only, never the full
snapshot blob, which is ~1.3MB and belongs in docs/index.html rather than in
version control history.

Everything here is intentionally pure (dicts in, dicts out) so it can be
tested without a database or a rendered artifact - see
tests/unit/test_ledger_metrics.py.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

HISTORY_PATH = Path(__file__).parent / "ledger_history.json"

# direction: "up" = a rising number is an improvement, "down" = a rising
# number is a regression (open conflicts are the only one of those today).
# ratio_of: denominator metric, for the "N of M" coverage readouts.
METRIC_SPECS: list[dict[str, Any]] = [
    {"key": "booths", "label": "Booths", "direction": "up"},
    {"key": "menu_items", "label": "Menu items", "direction": "up"},
    {"key": "items_priced", "label": "Items priced", "direction": "up", "ratio_of": "menu_items"},
    {"key": "items_with_image", "label": "Dishes photographed", "direction": "up", "ratio_of": "menu_items"},
    {"key": "items_tagged", "label": "Items with dietary tags", "direction": "up", "ratio_of": "menu_items"},
    {"key": "booths_with_menu", "label": "Booths with a menu", "direction": "up", "ratio_of": "booths"},
    {"key": "booths_with_image", "label": "Booths with a photo", "direction": "up", "ratio_of": "booths"},
    {"key": "sources_enabled", "label": "Sources enabled", "direction": "up"},
    {"key": "open_conflicts", "label": "Open conflicts", "direction": "down"},
]

METRIC_SPEC_BY_KEY = {spec["key"]: spec for spec in METRIC_SPECS}


def data_metrics(snapshot: dict[str, Any]) -> dict[str, int]:
    """Aggregate one exported snapshot into the counts the ledger tracks."""
    booths = snapshot.get("booths") or []
    items = [item for booth in booths for item in (booth.get("items") or [])]

    return {
        "booths": len(booths),
        "menu_items": len(items),
        "items_priced": sum(1 for it in items if it.get("price") is not None),
        "items_with_image": sum(1 for it in items if it.get("image_url")),
        "items_tagged": sum(1 for it in items if it.get("tags")),
        "booths_with_menu": sum(1 for b in booths if b.get("items")),
        "booths_with_image": sum(1 for b in booths if b.get("image_url")),
        "sources_enabled": sum(1 for s in (snapshot.get("sources") or []) if s.get("enabled")),
        "open_conflicts": len(snapshot.get("conflicts") or []),
    }


def pct(numerator: int, denominator: int) -> float | None:
    """Percentage, or None when there's nothing to take a percentage of.

    Returning None rather than 0.0 matters for the pre-season ledger: "0 of 0
    items priced" is an empty festival, not 0% price coverage, and the two
    should not render identically.
    """
    if not denominator:
        return None
    return round(numerator / denominator * 100, 1)


def diff_metrics(
    previous: dict[str, int] | None, current: dict[str, int]
) -> list[dict[str, Any]]:
    """Per-metric comparison rows. `previous=None` (the very first tracked
    snapshot) yields rows with delta=None, which the template renders as a
    baseline rather than inventing a zero-change diff."""
    rows = []
    for spec in METRIC_SPECS:
        key = spec["key"]
        curr_value = current.get(key, 0)
        prev_value = previous.get(key) if previous is not None else None
        delta = None if prev_value is None else curr_value - prev_value

        if delta is None or delta == 0:
            verdict = "same"
        elif (delta > 0) == (spec["direction"] == "up"):
            verdict = "gain"
        else:
            verdict = "loss"

        ratio_key = spec.get("ratio_of")
        rows.append(
            {
                "key": key,
                "label": spec["label"],
                "current": curr_value,
                "previous": prev_value,
                "delta": delta,
                "verdict": verdict,
                "current_pct": pct(curr_value, current.get(ratio_key, 0)) if ratio_key else None,
                "previous_pct": (
                    pct(prev_value, previous.get(ratio_key, 0))
                    if ratio_key and previous is not None and prev_value is not None
                    else None
                ),
            }
        )
    return rows


def load_history(path: Path = HISTORY_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    parsed = json.loads(path.read_text())
    return parsed.get("snapshots", [])


def save_history(snapshots: list[dict[str, Any]], path: Path = HISTORY_PATH) -> None:
    path.write_text(json.dumps({"snapshots": snapshots}, indent=2) + "\n")


def _same_data(previous: dict[str, int], current: dict[str, int]) -> bool:
    """True when nothing measurable changed between two metric rows.

    Compared only on the metrics the two rows have in common, so that adding a
    newly tracked metric cannot masquerade as a data change - the older row
    simply never measured it, which is not the same as it having moved. Any
    shared metric changing value, or a metric disappearing, is a real
    difference.
    """
    if not set(previous) <= set(current):
        return False
    return all(previous[key] == current[key] for key in previous)


def record_snapshot(
    snapshot: dict[str, Any],
    *,
    pipeline: dict[str, Any] | None = None,
    recorded_at: str | None = None,
    label: str | None = None,
    path: Path = HISTORY_PATH,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    """Append this snapshot's metrics to the history and return
    (history, current_entry, previous_entry).

    Re-running the build without a fresh crawl must not pile up duplicate
    history rows and manufacture a fake "no change" comparison, so an entry
    whose metrics are identical to the newest one replaces it in place
    (keeping the newer timestamp) instead of being appended.
    """
    history = load_history(path)
    entry: dict[str, Any] = {
        "recorded_at": recorded_at or datetime.datetime.now(datetime.UTC).isoformat(),
        "label": label or "snapshot",
        "data": data_metrics(snapshot),
    }
    if pipeline is not None:
        entry["pipeline"] = pipeline

    if history and _same_data(history[-1].get("data", {}), entry["data"]):
        history[-1] = {**history[-1], **entry}
        previous = history[-2] if len(history) > 1 else None
    else:
        history.append(entry)
        previous = history[-2] if len(history) > 1 else None

    save_history(history, path)
    return history, history[-1], previous
