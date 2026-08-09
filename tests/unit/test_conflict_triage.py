import datetime

from sqlalchemy import select

from epcot_fw.agents.conflict_triage import (
    AUTO_APPLY_CONFIDENCE,
    HeuristicConflictResolver,
    Proposal,
    TriageStats,
    _apply_value_proposal,
    accept_suggestion,
    reject_suggestion,
    run_conflict_triage,
)
from epcot_fw.db.models import (
    Booth,
    EntityFieldProvenance,
    ExtractedRecord,
    MergeConflict,
    RawPage,
    Source,
)

resolver = HeuristicConflictResolver()


def _source_id(session, key: str) -> int:
    return session.scalars(select(Source.id).where(Source.key == key)).one()


def _open_conflict(**kwargs) -> MergeConflict:
    return MergeConflict(status="open", opened_at=datetime.datetime.now(datetime.UTC), **kwargs)


def _add_booth(session, name: str = "The Alps") -> Booth:
    festival_id = session.info["festival_id"]
    booth = Booth(festival_id=festival_id, canonical_name=name, slug=name.lower().replace(" ", "-"))
    session.add(booth)
    session.flush()
    return booth


def _add_extracted_record(session, source_id: int, entity_type: str = "booth", payload: dict | None = None) -> int:
    now = datetime.datetime.now(datetime.UTC)
    raw_page = RawPage(
        source_id=source_id,
        url=f"https://example.test/{source_id}/{entity_type}",
        page_kind="booth_list",
        fetched_at=now,
        http_status=200,
        content_hash=f"test-{source_id}-{entity_type}-{id(payload)}",
        first_seen_at=now,
    )
    session.add(raw_page)
    session.flush()

    record = ExtractedRecord(
        raw_page_id=raw_page.id,
        source_id=source_id,
        entity_type=entity_type,
        extracted_at=now,
        extractor_version="test",
        payload=payload or {},
    )
    session.add(record)
    session.flush()
    return record.id


# ---- field-value disagreements --------------------------------------------


def test_numeric_majority_auto_resolves_and_ignores_outlier(db_session):
    booth = _add_booth(db_session)
    allears = _source_id(db_session, "allears")
    dfb = _source_id(db_session, "disney_food_blog")
    official = _source_id(db_session, "disney_official")

    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="price_usd",
        candidate_values={str(allears): "8.75", str(dfb): "8.75", str(official): "15.00"},
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = resolver.propose(conflict, db_session)
    assert proposal.decision == "value"
    assert proposal.value == "8.75"
    assert proposal.confidence >= AUTO_APPLY_CONFIDENCE


def test_two_way_price_disagreement_with_no_majority_needs_human(db_session):
    booth = _add_booth(db_session)
    allears = _source_id(db_session, "allears")
    dfb = _source_id(db_session, "disney_food_blog")

    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="price_usd",
        candidate_values={str(allears): "8.75", str(dfb): "15.00"},
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = resolver.propose(conflict, db_session)
    assert proposal.decision == "needs_human"


def test_numeric_outlier_among_larger_majority_is_ignored(db_session):
    booth = _add_booth(db_session)
    disney_official = _source_id(db_session, "disney_official")
    allears = _source_id(db_session, "allears")
    dfb = _source_id(db_session, "disney_food_blog")

    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="price_usd",
        candidate_values={str(disney_official): "8.75", str(allears): "8.75", str(dfb): "15.00"},
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = resolver.propose(conflict, db_session)
    assert proposal.decision == "value"
    assert proposal.value == "8.75"
    assert proposal.confidence >= AUTO_APPLY_CONFIDENCE
    assert str(dfb) in proposal.rationale


def test_text_that_only_differs_by_formatting_auto_resolves(db_session):
    booth = _add_booth(db_session)
    allears = _source_id(db_session, "allears")
    dfb = _source_id(db_session, "disney_food_blog")

    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="category",
        candidate_values={str(allears): "Flavors of America (NEW)", str(dfb): "Flavors of America"},
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = resolver.propose(conflict, db_session)
    assert proposal.decision == "value"
    assert proposal.confidence >= AUTO_APPLY_CONFIDENCE


def test_superset_text_is_suggested_but_not_auto_applied(db_session):
    booth = _add_booth(db_session)
    allears = _source_id(db_session, "allears")
    dfb = _source_id(db_session, "disney_food_blog")

    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="description",
        candidate_values={str(allears): "Cheese Plate", str(dfb): "Cheese Plate with Crackers and Grapes"},
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = resolver.propose(conflict, db_session)
    assert proposal.decision == "value"
    assert proposal.value == "Cheese Plate with Crackers and Grapes"
    assert proposal.confidence < AUTO_APPLY_CONFIDENCE


def test_genuinely_different_text_needs_human(db_session):
    booth = _add_booth(db_session)
    allears = _source_id(db_session, "allears")
    dfb = _source_id(db_session, "disney_food_blog")

    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="canonical_name",
        candidate_values={
            str(allears): "Mylonas Assyrtiko White Wine",
            str(dfb): "Mylonas Winery Assyrtiko Dry White",
        },
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = resolver.propose(conflict, db_session)
    assert proposal.decision == "needs_human"


def test_single_candidate_needs_human(db_session):
    """A field-value conflict with only one candidate can happen when two
    extracted_records from the *same* source both resolved to the same
    canonical field (the candidate_values dict is keyed by source_id, so the
    second write overwrites the first) - there's nothing left to compare, so
    this must never crash and must always defer to a human."""
    booth = _add_booth(db_session)
    allears = _source_id(db_session, "allears")

    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="description",
        candidate_values={str(allears): "only one value on file"},
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = resolver.propose(conflict, db_session)
    assert proposal.decision == "needs_human"


# ---- ambiguous fuzzy-name matches ------------------------------------------


def test_fuzzy_match_near_auto_merge_threshold_suggests_match(db_session):
    booth = _add_booth(db_session, name="Bubbles & Brine")

    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name=None,
        candidate_values={"extracted_name": "Bubbles and Brine", "score": 89.0, "extracted_record_id": 1},
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = resolver.propose(conflict, db_session)
    assert proposal.decision == "match"
    assert proposal.canonical_id == booth.id
    assert proposal.confidence < AUTO_APPLY_CONFIDENCE  # match/new_entity never auto-apply


def test_fuzzy_match_near_new_entity_threshold_suggests_new_entity(db_session):
    booth = _add_booth(db_session, name="The Noodle Exchange")

    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name=None,
        candidate_values={"extracted_name": "The Fry Basket", "score": 71.0, "extracted_record_id": 2},
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = resolver.propose(conflict, db_session)
    assert proposal.decision == "new_entity"
    assert proposal.confidence < AUTO_APPLY_CONFIDENCE


# ---- unmatched menu-item booth references ----------------------------------


def test_clearly_best_booth_reference_is_suggested(db_session):
    _add_booth(db_session, name="The Alps")
    other = _add_booth(db_session, name="The Cheese Studio")

    conflict = _open_conflict(
        entity_type="menu_item",
        canonical_id=None,
        field_name=None,
        candidate_values={"booth_name": "The Alps", "item": "Sausage Plate", "extracted_record_id": 3},
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = resolver.propose(conflict, db_session)
    assert proposal.decision == "match"
    assert proposal.booth_id is not None
    assert proposal.booth_id != other.id


def test_ambiguous_booth_reference_needs_human(db_session):
    _add_booth(db_session, name="Cider House")
    _add_booth(db_session, name="Cider Barn")

    conflict = _open_conflict(
        entity_type="menu_item",
        canonical_id=None,
        field_name=None,
        candidate_values={"booth_name": "Cider Something", "item": "Mystery Item", "extracted_record_id": 4},
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = resolver.propose(conflict, db_session)
    assert proposal.decision == "needs_human"


def test_no_booths_at_all_needs_human(db_session):
    conflict = _open_conflict(
        entity_type="menu_item",
        canonical_id=None,
        field_name=None,
        candidate_values={"booth_name": "Anything", "item": "Anything", "extracted_record_id": 5},
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = resolver.propose(conflict, db_session)
    assert proposal.decision == "needs_human"


# ---- run_conflict_triage / accept / reject ---------------------------------


def test_run_conflict_triage_applies_and_suggests_and_leaves_the_rest(db_session):
    booth = _add_booth(db_session)
    allears = _source_id(db_session, "allears")
    dfb = _source_id(db_session, "disney_food_blog")

    auto = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="category",
        candidate_values={str(allears): "Flavors of America (NEW)", str(dfb): "Flavors of America"},
    )
    suggest = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="description",
        candidate_values={str(allears): "Cheese Plate", str(dfb): "Cheese Plate with Crackers"},
    )
    stuck = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="canonical_name",
        candidate_values={str(allears): "Totally Different Name", str(dfb): "Something Else Entirely"},
    )
    db_session.add_all([auto, suggest, stuck])
    db_session.flush()

    stats = run_conflict_triage(db_session)

    assert stats == TriageStats(examined=3, auto_resolved=1, suggested=1, unchanged=1)
    assert auto.status == "resolved"
    assert auto.resolution_value["decided_by"] == "agent"
    assert suggest.status == "suggested"
    assert stuck.status == "open"


def test_run_conflict_triage_is_idempotent(db_session):
    booth = _add_booth(db_session)
    allears = _source_id(db_session, "allears")
    dfb = _source_id(db_session, "disney_food_blog")

    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="category",
        candidate_values={str(allears): "Flavors of America (NEW)", str(dfb): "Flavors of America"},
    )
    db_session.add(conflict)
    db_session.flush()

    first = run_conflict_triage(db_session)
    second = run_conflict_triage(db_session)

    assert first.auto_resolved == 1
    assert second == TriageStats()


def test_apply_value_proposal_updates_canonical_column_and_provenance(db_session):
    booth = _add_booth(db_session)
    allears = _source_id(db_session, "allears")
    dfb = _source_id(db_session, "disney_food_blog")

    now = datetime.datetime.now(datetime.UTC)
    winner_row = EntityFieldProvenance(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="category",
        source_id=dfb,
        extracted_record_id=_add_extracted_record(db_session, dfb),
        value="Flavors of America",
        observed_at=now,
        is_selected=False,
    )
    loser_row = EntityFieldProvenance(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="category",
        source_id=allears,
        extracted_record_id=_add_extracted_record(db_session, allears),
        value="Flavors of America (NEW)",
        observed_at=now,
        is_selected=True,
    )
    db_session.add_all([winner_row, loser_row])
    db_session.flush()

    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="category",
        candidate_values={str(allears): "Flavors of America (NEW)", str(dfb): "Flavors of America"},
    )
    db_session.add(conflict)
    db_session.flush()

    proposal = Proposal(decision="value", value="Flavors of America", confidence=0.95, rationale="test")
    _apply_value_proposal(db_session, conflict, proposal)

    assert booth.category == "Flavors of America"
    assert winner_row.is_selected is True
    assert loser_row.is_selected is False
    assert conflict.status == "resolved"
    assert conflict.resolved_at is not None


def test_accept_suggestion_on_field_value_conflict(db_session):
    booth = _add_booth(db_session)
    allears = _source_id(db_session, "allears")
    dfb = _source_id(db_session, "disney_food_blog")

    now = datetime.datetime.now(datetime.UTC)
    db_session.add(
        EntityFieldProvenance(
            entity_type="booth",
            canonical_id=booth.id,
            field_name="description",
            source_id=dfb,
            extracted_record_id=_add_extracted_record(db_session, dfb),
            value="Cheese Plate with Crackers",
            observed_at=now,
            is_selected=False,
        )
    )
    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="description",
        candidate_values={str(allears): "Cheese Plate", str(dfb): "Cheese Plate with Crackers"},
    )
    db_session.add(conflict)
    db_session.flush()

    run_conflict_triage(db_session)
    assert conflict.status == "suggested"

    accept_suggestion(db_session, conflict, festival_id=db_session.info["festival_id"])

    assert conflict.status == "resolved"
    assert booth.description == "Cheese Plate with Crackers"


def test_reject_suggestion_marks_dismissed_and_is_not_re_suggested(db_session):
    booth = _add_booth(db_session)
    allears = _source_id(db_session, "allears")
    dfb = _source_id(db_session, "disney_food_blog")

    conflict = _open_conflict(
        entity_type="booth",
        canonical_id=booth.id,
        field_name="description",
        candidate_values={str(allears): "Cheese Plate", str(dfb): "Cheese Plate with Crackers"},
    )
    db_session.add(conflict)
    db_session.flush()

    run_conflict_triage(db_session)
    assert conflict.status == "suggested"

    reject_suggestion(conflict)
    assert conflict.status == "dismissed"

    stats = run_conflict_triage(db_session)
    assert stats == TriageStats()
    assert conflict.status == "dismissed"


def test_accept_requires_suggested_status(db_session):
    booth = _add_booth(db_session)
    conflict = _open_conflict(
        entity_type="booth", canonical_id=booth.id, field_name="description", candidate_values={}
    )
    db_session.add(conflict)
    db_session.flush()

    import pytest

    with pytest.raises(ValueError):
        accept_suggestion(db_session, conflict, festival_id=db_session.info["festival_id"])

    with pytest.raises(ValueError):
        reject_suggestion(conflict)
