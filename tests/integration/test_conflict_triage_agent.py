"""End-to-end tests for the merge-conflict triage agent against real
crawler output: ingest actual fixture pages (producing the same
merge_conflicts a live crawl would), run the agent, and confirm it acts on
them sensibly and leaves the pipeline in a state a human reviewer -
or the next `epcot-fw resolve` pass - can build on."""

from pathlib import Path

from sqlalchemy import select

from epcot_fw.agents.conflict_triage import accept_suggestion, run_conflict_triage
from epcot_fw.db.models import Booth, CanonicalLink, MenuItem, MergeConflict, Source
from epcot_fw.sources.allears import AllEarsAdapter
from epcot_fw.sources.disney_food_blog import DisneyFoodBlogAdapter

from ._helpers import ingest

FIXTURES = Path(__file__).parent.parent / "fixtures/html_snapshots"


def _open_conflicts(session):
    return session.scalars(select(MergeConflict).where(MergeConflict.status == "open")).all()


def _source_id(session, key: str) -> int:
    return session.scalars(select(Source.id).where(Source.key == key)).one()


def test_triage_resolves_formatting_only_disagreements_across_two_sources(db_session):
    """AllEars and Disney Food Blog both list "Flavors of America" (one with
    a "(NEW)" suffix, one without) - a real cross-source disagreement that's
    purely cosmetic. The agent should close it without a human, while a
    genuinely different pair of names (e.g. differently-worded wine
    descriptions) is left for a human."""
    festival_id = db_session.info["festival_id"]

    allears_html = (FIXTURES / "allears/booth_menus_hub.html").read_text()
    dfb_html = (FIXTURES / "disney_food_blog/booth_menus_hub.html").read_text()
    ingest(db_session, AllEarsAdapter().parse(allears_html, "https://example.test/allears", "booth_list"),
           "allears", festival_id, url="https://example.test/allears")
    ingest(db_session, DisneyFoodBlogAdapter().parse(dfb_html, "https://example.test/dfb", "booth_list"),
           "disney_food_blog", festival_id, url="https://example.test/dfb")

    field_conflicts_before = [c for c in _open_conflicts(db_session) if c.field_name == "canonical_name"]
    assert field_conflicts_before, "fixture should produce at least one canonical_name disagreement"

    flavors_of_america = db_session.scalars(
        select(Booth).where(Booth.canonical_name.ilike("flavors of america%"))
    ).one()
    formatting_conflict = next(
        c for c in field_conflicts_before if c.canonical_id == flavors_of_america.id
    )

    stats = run_conflict_triage(db_session)
    assert stats.examined == len(field_conflicts_before) + len(
        [c for c in _open_conflicts(db_session) if c not in field_conflicts_before]
    ) or stats.examined > 0  # sanity: it actually looked at something

    assert formatting_conflict.status == "resolved"
    assert formatting_conflict.resolution_value["decided_by"] == "agent"
    assert flavors_of_america.canonical_name in ("Flavors of America", "Flavors of America (NEW)")

    # A pair of menu items with real wording differences (not just casing
    # or a superset) must still be left for a human.
    allears_id = str(_source_id(db_session, "allears"))
    dfb_id = str(_source_id(db_session, "disney_food_blog"))
    genuinely_different = [
        c
        for c in field_conflicts_before
        if len(c.candidate_values) == 2
        and c.candidate_values.get(allears_id, "").split()[:2] != c.candidate_values.get(dfb_id, "").split()[:2]
    ]
    still_open_or_suggested = [c for c in genuinely_different if c.status != "resolved"]
    assert still_open_or_suggested, "at least one real text disagreement should not be silently auto-resolved"


def test_triage_never_auto_applies_match_or_new_entity_decisions(db_session):
    """Ambiguous fuzzy-name matches and unmatched booth references must
    always come back as status=suggested (or stay open), never
    silently resolved - only field *value* picks are safe to auto-apply."""
    festival_id = db_session.info["festival_id"]
    html = (FIXTURES / "allears/booth_menus_hub.html").read_text()
    ingest(db_session, AllEarsAdapter().parse(html, "https://example.test/allears", "booth_list"),
           "allears", festival_id, url="https://example.test/allears")

    match_type_conflicts_before = [c for c in _open_conflicts(db_session) if c.field_name is None]
    assert match_type_conflicts_before, "fixture should produce at least one match-type conflict"

    run_conflict_triage(db_session)

    for conflict in match_type_conflicts_before:
        assert conflict.status in ("open", "suggested")
        if conflict.status == "suggested":
            assert conflict.resolution_value["decision"] in ("match", "new_entity")


def test_accepting_a_new_entity_suggestion_then_a_booth_reference_suggestion(db_session):
    """Full realistic workflow: the matcher couldn't confidently place
    "Refreshment Port hosted by Boursin(R) Cheese" (only a review-band fuzzy
    match against a differently-named existing booth), so it's a suggested
    new_entity. Accepting it creates the booth. Once it exists, the menu
    items that reference it by that same exact name - previously stuck as
    unmatched booth-reference conflicts - can be triaged again and become a
    confident, acceptable "match" suggestion instead of needing_human."""
    festival_id = db_session.info["festival_id"]
    html = (FIXTURES / "allears/booth_menus_hub.html").read_text()
    ingest(db_session, AllEarsAdapter().parse(html, "https://example.test/allears", "booth_list"),
           "allears", festival_id, url="https://example.test/allears")

    run_conflict_triage(db_session)

    booth_name = "Refreshment Port hosted by Boursin® Cheese"
    booth_new_entity_conflict = next(
        c
        for c in db_session.scalars(select(MergeConflict)).all()
        if c.entity_type == "booth"
        and c.status == "suggested"
        and c.candidate_values.get("extracted_name") == booth_name
    )
    assert booth_new_entity_conflict.resolution_value["decision"] == "new_entity"

    booth_refs_before = [
        c
        for c in db_session.scalars(select(MergeConflict)).all()
        if c.entity_type == "menu_item"
        and c.canonical_id is None
        and c.field_name is None
        and c.candidate_values.get("booth_name") == booth_name
    ]
    assert booth_refs_before, "fixture should have menu items referencing this exact booth name"
    assert all(c.status in ("open", "suggested") for c in booth_refs_before)

    booths_before = len(db_session.scalars(select(Booth)).all())
    accept_suggestion(db_session, booth_new_entity_conflict, festival_id=festival_id)
    assert booth_new_entity_conflict.status == "resolved"

    new_booth = db_session.scalars(select(Booth).where(Booth.canonical_name == booth_name)).one()
    assert len(db_session.scalars(select(Booth)).all()) == booths_before + 1
    assert (
        db_session.scalars(
            select(CanonicalLink).where(
                CanonicalLink.entity_type == "booth", CanonicalLink.canonical_id == new_booth.id
            )
        ).first()
        is not None
    )

    # Re-triage: the booth-reference conflicts should now resolve to a
    # confident "match" suggestion against the booth we just created.
    run_conflict_triage(db_session)
    for conflict in booth_refs_before:
        db_session.refresh(conflict)
        assert conflict.status == "suggested"
        assert conflict.resolution_value["decision"] == "match"
        assert conflict.resolution_value["booth_id"] == new_booth.id

    menu_items_before = len(db_session.scalars(select(MenuItem)).all())
    for conflict in booth_refs_before:
        accept_suggestion(db_session, conflict, festival_id=festival_id)
        assert conflict.status == "resolved"

    new_items = db_session.scalars(select(MenuItem).where(MenuItem.booth_id == new_booth.id)).all()
    assert len(new_items) == len(booth_refs_before)
    assert len(db_session.scalars(select(MenuItem)).all()) == menu_items_before + len(booth_refs_before)


def test_run_conflict_triage_then_accept_all_is_a_stable_end_state(db_session):
    """Running triage, accepting every suggestion it produces, and running
    triage again should reach a fixed point with no open work left over
    from formatting/majority-agreement conflicts (some conflicts will
    legitimately remain - genuine textual disagreements the resolver
    declines to call - those must still be present, not silently dropped)."""
    festival_id = db_session.info["festival_id"]
    allears_html = (FIXTURES / "allears/booth_menus_hub.html").read_text()
    dfb_html = (FIXTURES / "disney_food_blog/booth_menus_hub.html").read_text()
    ingest(db_session, AllEarsAdapter().parse(allears_html, "https://example.test/allears", "booth_list"),
           "allears", festival_id, url="https://example.test/allears")
    ingest(db_session, DisneyFoodBlogAdapter().parse(dfb_html, "https://example.test/dfb", "booth_list"),
           "disney_food_blog", festival_id, url="https://example.test/dfb")

    ids_before = {c.id for c in db_session.scalars(select(MergeConflict)).all()}
    total_before = len(ids_before)

    run_conflict_triage(db_session)
    suggested = db_session.scalars(select(MergeConflict).where(MergeConflict.status == "suggested")).all()
    for conflict in suggested:
        accept_suggestion(db_session, conflict, festival_id=festival_id)

    run_conflict_triage(db_session)

    ids_after = {c.id for c in db_session.scalars(select(MergeConflict)).all()}
    # Accepting a "match"/"new_entity" suggestion can legitimately surface
    # brand-new field-value conflicts (e.g. two records only get compared
    # once they're linked to the same canonical entity for the first time),
    # so the total may grow - but nothing that existed before may vanish.
    assert ids_before <= ids_after, "triage/accept must never delete a conflict row"

    remaining_open_or_suggested = db_session.scalars(
        select(MergeConflict).where(MergeConflict.status.in_(["open", "suggested"]))
    ).all()
    assert len(remaining_open_or_suggested) < total_before, "some conflicts should have been resolved"
