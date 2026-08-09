"""Autonomous triage for open `merge_conflicts` rows.

`resolve/merge.py` opens a `merge_conflicts` row whenever the matcher/merger
can't make a confident call on its own: two sources disagree on a field
value, an extracted record's name only fuzzy-matches a canonical entity in
the "review" band (see `resolve/matcher.py`), or a menu item's booth
reference doesn't match any known booth. Until now the only thing that
happened to those rows was `epcot-fw review` printing them for a human to
eyeball one by one.

This module adds a decision layer on top:

- For each open conflict, build a bit of extra context (the candidate
  values already on file, each source's `priority_rank`, and - for
  match-type conflicts - a fresh fuzzy-match pass) and ask a
  `ConflictResolver` for a `Proposal`.
- High-confidence field-*value* proposals are applied immediately, with the
  same effect as if a human had picked that value by hand.
- Everything else the resolver has an opinion on is written back with
  `status="suggested"` and the proposal (value/rationale/confidence) stored
  in `resolution_value`, so `epcot-fw review` shows a concrete
  recommendation instead of a bare disagreement, and a human can
  `epcot-fw review accept/reject <id>` it in one step.
- Conflicts the resolver has no useful opinion on (`decision="needs_human"`)
  are left completely untouched (`status` stays `"open"`).

Deliberately no LLM call in the default resolver: every rule below is a
small, deterministic, explainable heuristic. That keeps this fully
unit-testable with no network/API-key dependency and safe to run unattended
inside a scheduled `epcot-fw refresh` (see pipeline/refresh.py). A future
LLM-backed `ConflictResolver` can slot in behind the same `propose()`
interface for the cases these heuristics punt on.
"""

import datetime
import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import (
    Booth,
    EntityFieldProvenance,
    ExtractedRecord,
    MergeConflict,
    Source,
)
from epcot_fw.normalize.text import normalize_name
from epcot_fw.resolve.matcher import (
    AUTO_MERGE_THRESHOLD,
    REVIEW_THRESHOLD,
    find_best_match,
    score_pair,
)
from epcot_fw.resolve.merge import (
    ENTITY_MODEL,
    NAME_MODEL_FIELD,
    NAME_PAYLOAD_KEY,
    _coerce,
    _load_scoped_candidates,
    apply_match_outcome,
    resolve_booth_id,
)
from epcot_fw.resolve.priority import NUMERIC_DISAGREEMENT_THRESHOLD

Decision = Literal["value", "match", "new_entity", "needs_human"]

# A "value" proposal at or above this confidence is applied automatically.
# "match"/"new_entity" proposals are NEVER auto-applied regardless of
# confidence - creating a canonical entity or linking one record into
# another has a much higher blast radius than picking between two values
# that were already both observed and tracked, so those always wait for an
# explicit `epcot-fw review accept`.
AUTO_APPLY_CONFIDENCE = 0.85

# A booth-name match needs to beat the runner-up by at least this many
# fuzzy-score points before the triage agent will suggest it - a high score
# with a near-tied second place means the name is genuinely ambiguous
# between two real booths.
BOOTH_MATCH_FLOOR = 75.0
BOOTH_MATCH_SEPARATION = 15.0


@dataclass(frozen=True)
class Proposal:
    """One resolver's recommendation for one open conflict.

    `decision="value"` means "here's the field value to use" (`value` set).
    `decision="match"` means "link to this existing canonical entity"
    (`canonical_id` set - an id of the *same* entity_type as the conflict).
    `decision="new_entity"` means "this is not the same as the ambiguous
    existing candidate; create a fresh entity for it instead".
    `decision="needs_human"` means the resolver has no confident call at
    all - the conflict is left exactly as it was found.

    `booth_id` is a special case only used for menu-item "booth reference"
    conflicts (see `_propose_booth_reference`): there `canonical_id` isn't
    meaningful yet (no menu_item exists to link to), and this instead
    carries the *booth* the item name should be attached to once accepted.
    """

    decision: Decision
    confidence: float = 0.0
    rationale: str = ""
    value: Any = None
    canonical_id: int | None = None
    booth_id: int | None = None

    @property
    def is_actionable(self) -> bool:
        return self.decision != "needs_human"


class ConflictResolver(Protocol):
    def propose(self, conflict: MergeConflict, session: Session) -> Proposal: ...


def _needs_human(rationale: str) -> Proposal:
    return Proposal(decision="needs_human", rationale=rationale)


def _json_safe(value: Any) -> Any:
    return str(value) if isinstance(value, Decimal) else value


@dataclass(frozen=True)
class _FieldCandidate:
    source_id: int
    priority_rank: int
    value: Any


class HeuristicConflictResolver:
    """Deterministic, LLM-free triage rules.

    Three kinds of open conflict exist (see resolve/merge.py), and each gets
    its own rule set below:

    1. Field-value disagreements (`field_name` is set): a numeric outlier
       check for prices/etc., and a text-normalization / substring check for
       everything else.
    2. Ambiguous fuzzy-name matches (`field_name` is None, `canonical_id` is
       set): re-examines where in the "review" band the score sits.
    3. Unmatched menu-item booth references (`field_name` and `canonical_id`
       both None): a fresh fuzzy-match pass against known booths, requiring
       both a decent score and clear separation from the runner-up.
    """

    def propose(self, conflict: MergeConflict, session: Session) -> Proposal:
        if conflict.field_name is not None:
            return self._propose_field_value(conflict, session)
        if conflict.canonical_id is not None:
            return self._propose_fuzzy_match(conflict, session)
        return self._propose_booth_reference(conflict, session)

    # ---- 1. field-value disagreements ---------------------------------

    def _propose_field_value(self, conflict: MergeConflict, session: Session) -> Proposal:
        candidates = self._load_field_candidates(conflict, session)
        if len(candidates) < 2:
            return _needs_human("only one candidate value on file for this field; nothing to compare")

        numeric_proposal = self._propose_numeric_value(candidates)
        if numeric_proposal is not None:
            return numeric_proposal

        return self._propose_text_value(candidates)

    def _load_field_candidates(self, conflict: MergeConflict, session: Session) -> list[_FieldCandidate]:
        candidates = []
        for source_id_str, value in conflict.candidate_values.items():
            source = session.get(Source, int(source_id_str))
            if source is None:
                continue
            candidates.append(
                _FieldCandidate(source_id=source.id, priority_rank=source.priority_rank, value=value)
            )
        return candidates

    def _propose_numeric_value(self, candidates: list[_FieldCandidate]) -> Proposal | None:
        try:
            numbers = [float(c.value) for c in candidates]
        except (TypeError, ValueError):
            return None

        median = statistics.median(numbers)
        agree, disagree = [], []
        for candidate, number in zip(candidates, numbers):
            rel_diff = abs(number - median) / abs(median) if median else float(number != 0)
            (agree if rel_diff <= NUMERIC_DISAGREEMENT_THRESHOLD else disagree).append(candidate)

        if not disagree or len(agree) <= len(disagree):
            spread = max(numbers) - min(numbers)
            return _needs_human(
                f"no clear majority among {len(candidates)} numeric candidates (spread {spread:g}); "
                "needs a human call"
            )

        # A minority "outlier" among an otherwise-agreeing majority is most
        # likely a stale cache or a mis-scraped number, not evidence the
        # underlying price/etc. actually changed - trust the majority's
        # highest-priority source.
        winner = min(agree, key=lambda c: c.priority_rank)
        outliers = ", ".join(str(c.source_id) for c in disagree)
        return Proposal(
            decision="value",
            value=winner.value,
            confidence=0.9,
            rationale=(
                f"{len(agree)}/{len(candidates)} sources agree on {winner.value!r} "
                f"(within {NUMERIC_DISAGREEMENT_THRESHOLD:.0%} of each other); "
                f"source id(s) {outliers} look like the outlier"
            ),
        )

    def _propose_text_value(self, candidates: list[_FieldCandidate]) -> Proposal:
        normalized = [(c, normalize_name(str(c.value))) for c in candidates]
        distinct_norms = {norm for _, norm in normalized}

        if len(distinct_norms) == 1:
            # Only differs in casing/whitespace/punctuation once normalized
            # - not a real disagreement, just different source formatting.
            winner = min(candidates, key=lambda c: c.priority_rank)
            return Proposal(
                decision="value",
                value=winner.value,
                confidence=0.95,
                rationale="all candidates are identical once normalized (casing/whitespace only)",
            )

        # One candidate fully contains every other as a substring, e.g.
        # "Cheese Plate" vs. "Cheese Plate with Crackers and Grapes" - the
        # longer one is strictly more informative, not a contradiction.
        # Confidence is kept below AUTO_APPLY_CONFIDENCE on purpose: this
        # heuristic is naive about short substrings that are *not* just more
        # detail (e.g. "Ham" inside "Hamburger"), so it's surfaced as a
        # suggestion for a human to confirm rather than applied outright.
        longest_candidate, longest_norm = max(normalized, key=lambda pair: len(pair[1]))
        if all(norm in longest_norm for _, norm in normalized):
            return Proposal(
                decision="value",
                value=longest_candidate.value,
                confidence=0.7,
                rationale="one candidate's text is a superset of the other(s); recommend the more detailed text",
            )

        values_by_source = ", ".join(f"source {c.source_id}: {c.value!r}" for c in candidates)
        return _needs_human(f"text values genuinely disagree ({values_by_source})")

    # ---- 2. ambiguous fuzzy-name matches --------------------------------

    def _propose_fuzzy_match(self, conflict: MergeConflict, session: Session) -> Proposal:
        score = conflict.candidate_values.get("score")
        extracted_name = conflict.candidate_values.get("extracted_name")
        if score is None:
            return _needs_human("candidate_values is missing the original match score")

        score = float(score)
        entity_label = self._entity_label(conflict.entity_type, conflict.canonical_id, session)

        # REVIEW_THRESHOLD..AUTO_MERGE_THRESHOLD is the "review" band the
        # matcher already withheld this record into - splitting it in half
        # surfaces *where* in that band the score sits, which the matcher's
        # own fixed thresholds don't tell a reviewer.
        midpoint = (REVIEW_THRESHOLD + AUTO_MERGE_THRESHOLD) / 2

        if score >= midpoint:
            confidence = min(0.5 + 0.3 * (score - midpoint) / (AUTO_MERGE_THRESHOLD - midpoint), 0.8)
            return Proposal(
                decision="match",
                canonical_id=conflict.canonical_id,
                confidence=confidence,
                rationale=(
                    f"{extracted_name!r} scored {score:.1f}, close to the auto-merge threshold "
                    f"({AUTO_MERGE_THRESHOLD:.0f}); recommend linking to existing {entity_label!r}"
                ),
            )

        confidence = min(0.5 + 0.3 * (midpoint - score) / (midpoint - REVIEW_THRESHOLD), 0.8)
        return Proposal(
            decision="new_entity",
            confidence=confidence,
            rationale=(
                f"{extracted_name!r} scored only {score:.1f}, close to the new-entity threshold "
                f"({REVIEW_THRESHOLD:.0f}); recommend treating it as a distinct "
                f"{conflict.entity_type} rather than merging into {entity_label!r}"
            ),
        )

    def _entity_label(self, entity_type: str, canonical_id: int | None, session: Session) -> str:
        model_cls = ENTITY_MODEL.get(entity_type)
        if model_cls is None or canonical_id is None:
            return "(unknown)"
        obj = session.get(model_cls, canonical_id)
        if obj is None:
            return "(deleted)"
        return getattr(obj, NAME_MODEL_FIELD[entity_type])

    # ---- 3. unmatched menu-item booth references ------------------------

    def _propose_booth_reference(self, conflict: MergeConflict, session: Session) -> Proposal:
        booth_name = conflict.candidate_values.get("booth_name")
        item_name = conflict.candidate_values.get("item")
        if not booth_name:
            return _needs_human("no booth name recorded on this menu item")

        key = normalize_name(booth_name)
        booths = session.scalars(select(Booth)).all()
        scored = sorted(
            ((score_pair(key, normalize_name(b.canonical_name)), b) for b in booths),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not scored:
            return _needs_human(f"no booths exist yet to match {booth_name!r} against")

        best_score, best_booth = scored[0]
        runner_up_score = scored[1][0] if len(scored) > 1 else 0.0

        if best_score >= BOOTH_MATCH_FLOOR and (best_score - runner_up_score) >= BOOTH_MATCH_SEPARATION:
            confidence = min(0.5 + (best_score - BOOTH_MATCH_FLOOR) / 50.0, 0.8)
            return Proposal(
                decision="match",
                booth_id=best_booth.id,
                confidence=confidence,
                rationale=(
                    f"{booth_name!r} (from menu item {item_name!r}) best matches booth "
                    f"{best_booth.canonical_name!r} (score {best_score:.1f}, next-best {runner_up_score:.1f})"
                ),
            )

        top = ", ".join(f"{b.canonical_name!r} ({s:.1f})" for s, b in scored[:3])
        return _needs_human(
            f"{booth_name!r} (from menu item {item_name!r}) has no clearly-best booth match; "
            f"closest candidates: {top}"
        )


def _apply_value_proposal(session: Session, conflict: MergeConflict, proposal: Proposal) -> None:
    """Mark the winning EntityFieldProvenance candidate(s) selected, write
    the value through to the canonical column, and close the conflict.
    Never fabricates a value the pipeline hasn't already observed from some
    source - it only ever picks among `conflict.candidate_values`."""
    target = _json_safe(proposal.value)

    rows = session.scalars(
        select(EntityFieldProvenance).where(
            EntityFieldProvenance.entity_type == conflict.entity_type,
            EntityFieldProvenance.canonical_id == conflict.canonical_id,
            EntityFieldProvenance.field_name == conflict.field_name,
        )
    ).all()
    for row in rows:
        row.is_selected = row.value == target

    model_cls = ENTITY_MODEL[conflict.entity_type]
    model_obj = session.get(model_cls, conflict.canonical_id)
    if model_obj is not None:
        setattr(model_obj, conflict.field_name, _coerce(model_cls, conflict.field_name, proposal.value))

    conflict.status = "resolved"
    conflict.resolved_at = datetime.datetime.now(datetime.UTC)
    conflict.resolution_value = {
        "decided_by": "agent",
        "decision": "value",
        "value": target,
        "confidence": proposal.confidence,
        "rationale": proposal.rationale,
    }


def _record_suggestion(conflict: MergeConflict, proposal: Proposal) -> None:
    conflict.status = "suggested"
    conflict.resolution_value = {
        "decided_by": "agent",
        "decision": proposal.decision,
        "value": _json_safe(proposal.value),
        "canonical_id": proposal.canonical_id,
        "booth_id": proposal.booth_id,
        "confidence": proposal.confidence,
        "rationale": proposal.rationale,
    }


@dataclass
class TriageStats:
    examined: int = 0
    auto_resolved: int = 0
    suggested: int = 0
    unchanged: int = 0


def run_conflict_triage(
    session: Session,
    *,
    resolver: ConflictResolver | None = None,
    limit: int | None = None,
) -> TriageStats:
    """Run one pass of triage over every currently-open `merge_conflicts`
    row. Safe to call repeatedly: only `status="open"` rows are examined, so
    a conflict this already turned into `"resolved"` or `"suggested"` is
    left alone on the next pass (a human's `accept`/`reject` is what moves a
    `"suggested"` row on from there - see accept_suggestion/reject_suggestion
    below)."""
    resolver = resolver or HeuristicConflictResolver()
    stats = TriageStats()

    stmt = select(MergeConflict).where(MergeConflict.status == "open").order_by(MergeConflict.id)
    if limit is not None:
        stmt = stmt.limit(limit)

    for conflict in session.scalars(stmt).all():
        stats.examined += 1
        proposal = resolver.propose(conflict, session)

        if not proposal.is_actionable:
            stats.unchanged += 1
            continue

        if proposal.decision == "value" and proposal.confidence >= AUTO_APPLY_CONFIDENCE:
            _apply_value_proposal(session, conflict, proposal)
            stats.auto_resolved += 1
        else:
            _record_suggestion(conflict, proposal)
            stats.suggested += 1

    session.flush()
    return stats


def accept_suggestion(session: Session, conflict: MergeConflict, *, festival_id: int) -> None:
    """Apply a `status="suggested"` conflict's stored proposal for real, as
    if a human had made that same call directly.

    - A field-value suggestion is applied exactly like an auto-resolved one
      (see `_apply_value_proposal`).
    - A fuzzy-name-match suggestion (`canonical_id` set) links the extracted
      record into the recommended existing entity, or creates a fresh one
      for "new_entity", via the same `apply_match_outcome` the automatic
      matcher itself uses.
    - A booth-reference suggestion (`booth_id` set instead) attaches the
      menu item to that booth, then runs the ordinary item-name match within
      that booth's existing items - exactly what `resolve_extracted_record`
      would have done itself had the booth match been confident the first
      time around.
    """
    if conflict.status != "suggested":
        raise ValueError(f"conflict {conflict.id} is not in 'suggested' status (status={conflict.status!r})")

    payload = conflict.resolution_value or {}

    if conflict.field_name is not None:
        _apply_value_proposal(
            session,
            conflict,
            Proposal(
                decision="value",
                value=payload.get("value"),
                confidence=payload.get("confidence", 0.0),
                rationale=payload.get("rationale", ""),
            ),
        )
        return

    extracted_record_id = conflict.candidate_values.get("extracted_record_id")
    extracted_record = session.get(ExtractedRecord, extracted_record_id) if extracted_record_id else None
    if extracted_record is None:
        raise ValueError(f"conflict {conflict.id} has no extracted_record to finish linking")

    source = session.get(Source, extracted_record.source_id)
    decision = payload.get("decision")

    if conflict.canonical_id is None and payload.get("booth_id") is not None:
        # Booth-reference conflict: the recommendation was a *booth*, not a
        # menu_item - the item's own name was never matched against that
        # booth's existing items, so do that now before finishing the link.
        booth_id = payload["booth_id"]
        name = extracted_record.payload.get(NAME_PAYLOAD_KEY["menu_item"])
        candidates = _load_scoped_candidates(session, "menu_item", festival_id=festival_id, booth_id=booth_id)
        item_match = find_best_match(extracted_record.natural_key_hint or normalize_name(name), candidates)
        # A still-ambiguous item name at this point falls back to creating a
        # new item at the now-known booth rather than risking a bad merge -
        # the next full `epcot-fw resolve` pass can reconcile it further.
        outcome = "auto_merge" if item_match.outcome == "auto_merge" else "new_entity"
        apply_match_outcome(
            session,
            extracted_record,
            source,
            entity_type="menu_item",
            outcome=outcome,
            canonical_id=item_match.canonical_id,
            booth_id=booth_id,
            match_score=item_match.score,
            match_method="agent_accepted_booth_ref",
            festival_id=festival_id,
        )
    else:
        # Fuzzy-name-match-band conflict: candidate_values still has the
        # original 0-100 matcher score - reuse it for match_confidence
        # rather than the agent's own 0-1 confidence, which is a different
        # (meta-)quantity about how sure the agent is in its recommendation.
        booth_id = None
        if conflict.entity_type == "menu_item" and decision == "new_entity":
            booth_id = resolve_booth_id(session, festival_id, extracted_record.payload.get("booth_name"))
        apply_match_outcome(
            session,
            extracted_record,
            source,
            entity_type=conflict.entity_type,
            outcome="new_entity" if decision == "new_entity" else "auto_merge",
            canonical_id=payload.get("canonical_id"),
            booth_id=booth_id,
            match_score=conflict.candidate_values.get("score"),
            match_method="agent_accepted",
            festival_id=festival_id,
        )

    conflict.status = "resolved"
    conflict.resolved_at = datetime.datetime.now(datetime.UTC)


def reject_suggestion(conflict: MergeConflict) -> None:
    """Dismiss a `status="suggested"` conflict without applying it. Unlike
    `"open"`, `"dismissed"` is a terminal status - `run_conflict_triage`
    only ever looks at `"open"` rows, so a dismissed conflict won't get
    re-suggested on the next pass."""
    if conflict.status != "suggested":
        raise ValueError(f"conflict {conflict.id} is not in 'suggested' status (status={conflict.status!r})")
    conflict.status = "dismissed"
    conflict.resolved_at = datetime.datetime.now(datetime.UTC)
