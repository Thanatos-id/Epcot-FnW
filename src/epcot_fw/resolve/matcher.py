from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

AUTO_MERGE_THRESHOLD = 90.0
REVIEW_THRESHOLD = 70.0

MatchOutcome = Literal["auto_merge", "review", "new_entity"]


@dataclass(frozen=True)
class Candidate:
    canonical_id: int
    natural_key: str


@dataclass(frozen=True)
class MatchResult:
    outcome: MatchOutcome
    canonical_id: int | None
    score: float | None


def score_pair(extracted_key: str, candidate_key: str, *, context_bonus: float = 0.0) -> float:
    """Fuzzy name similarity (0-100) plus a small bonus for corroborating
    context (matching category, same booth, close date, etc.) supplied by the
    caller, capped at 100.

    Uses token_sort_ratio rather than WRatio: WRatio falls back to a
    partial-ratio comparison when two strings have very different lengths,
    which produces misleadingly high scores (85+) for genuinely unrelated
    short names (e.g. "The Fry Basket" vs "The Noodle Exchange") - exactly
    the false-merge failure mode this matcher exists to avoid.
    """
    base = fuzz.token_sort_ratio(extracted_key, candidate_key)
    return min(100.0, base + context_bonus)


def find_best_match(
    extracted_key: str, candidates: list[Candidate], *, context_bonus: float = 0.0
) -> MatchResult:
    """Blocking is the caller's job (pass in only same-entity-type,
    same-festival/same-booth candidates). This just scores and classifies."""
    if not candidates:
        return MatchResult(outcome="new_entity", canonical_id=None, score=None)

    best = max(
        candidates,
        key=lambda c: score_pair(extracted_key, c.natural_key, context_bonus=context_bonus),
    )
    best_score = score_pair(extracted_key, best.natural_key, context_bonus=context_bonus)

    if best_score >= AUTO_MERGE_THRESHOLD:
        return MatchResult(outcome="auto_merge", canonical_id=best.canonical_id, score=best_score)
    if best_score >= REVIEW_THRESHOLD:
        return MatchResult(outcome="review", canonical_id=best.canonical_id, score=best_score)
    return MatchResult(outcome="new_entity", canonical_id=None, score=best_score)
