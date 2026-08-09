import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

Strategy = Literal["priority", "most_recent", "union"]

# Default per-field override rules. Anything not listed falls back to
# DEFAULT_STRATEGY ("priority" - lower sources.priority_rank wins).
FIELD_STRATEGIES: dict[str, Strategy] = {
    "price_usd": "most_recent",  # festival prices genuinely change mid-run
    "dietary_tags": "union",  # more info is strictly better, not a real conflict
}
DEFAULT_STRATEGY: Strategy = "priority"

# If numeric candidate values disagree by more than this fraction even after
# a winner is picked, still log a merge_conflicts row for visibility.
NUMERIC_DISAGREEMENT_THRESHOLD = 0.20


@dataclass(frozen=True)
class FieldCandidate:
    ref: Any  # caller-defined identifier (e.g. an EntityFieldProvenance row id)
    source_id: int
    priority_rank: int
    observed_at: datetime.datetime
    value: Any


@dataclass(frozen=True)
class FieldResolution:
    value: Any
    has_disagreement: bool
    winner_refs: list[Any]  # refs of the candidate(s) that populate the canonical value


def resolve_field(field_name: str, candidates: list[FieldCandidate]) -> FieldResolution:
    if not candidates:
        return FieldResolution(value=None, has_disagreement=False, winner_refs=[])

    strategy = FIELD_STRATEGIES.get(field_name, DEFAULT_STRATEGY)

    if strategy == "union":
        merged: list[Any] = []
        refs: list[Any] = []
        for c in candidates:
            refs.append(c.ref)
            for v in c.value or []:
                if v not in merged:
                    merged.append(v)
        return FieldResolution(value=merged, has_disagreement=False, winner_refs=refs)

    if strategy == "most_recent":
        winner = max(candidates, key=lambda c: c.observed_at)
    else:  # "priority"
        # Best source wins; among equally-trusted observations the most recent
        # one does. The tie-break matters more than it looks: a source that
        # re-reports a changed value (a revised description, a corrected
        # coordinate) contributes a second candidate at the *same* rank, and
        # picking either arbitrarily means a stale value can outlive its
        # correction - non-deterministically, since the rows come back
        # unordered.
        best_rank = min(c.priority_rank for c in candidates)
        winner = max(
            (c for c in candidates if c.priority_rank == best_rank),
            key=lambda c: c.observed_at,
        )

    return FieldResolution(
        value=winner.value,
        has_disagreement=_disagree(candidates, winner.value),
        winner_refs=[winner.ref],
    )


def _disagree(candidates: list[FieldCandidate], winning_value: Any) -> bool:
    values = [c.value for c in candidates if c.value is not None]
    if len(values) <= 1:
        return False

    if all(isinstance(v, (int, float, Decimal)) for v in values) and winning_value is not None:
        winning_float = float(winning_value)
        if winning_float == 0:
            return any(float(v) != 0 for v in values)
        for v in values:
            if abs(float(v) - winning_float) / abs(winning_float) > NUMERIC_DISAGREEMENT_THRESHOLD:
                return True
        return False

    return len({str(v) for v in values}) > 1
