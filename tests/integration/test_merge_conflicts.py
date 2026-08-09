import datetime

from sqlalchemy import select

from epcot_fw.db.models import ExtractedRecord, MergeConflict, RawPage, Source
from epcot_fw.resolve.merge import _open_conflict, _write_and_resolve_field

CANONICAL_ID = 999_001


def _make_record(session, source_key: str, payload: dict) -> tuple[ExtractedRecord, Source]:
    source = session.scalars(select(Source).where(Source.key == source_key)).one()
    now = datetime.datetime.now(datetime.UTC)
    raw_page = RawPage(
        source_id=source.id,
        url=f"https://example.test/{source_key}",
        page_kind="booth_list",
        fetched_at=now,
        http_status=200,
        content_hash=f"test-{source_key}-{payload}",
        first_seen_at=now,
    )
    session.add(raw_page)
    session.flush()
    record = ExtractedRecord(
        raw_page_id=raw_page.id,
        source_id=source.id,
        entity_type="menu_item",
        extracted_at=now,
        extractor_version="test",
        payload=payload,
    )
    session.add(record)
    session.flush()
    return record, source


def test_disagreement_opens_a_merge_conflict(db_session):
    early = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    late = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)

    record_a, source_a = _make_record(db_session, "disney_official", {"price_usd": "8.00"})
    _write_and_resolve_field(
        db_session,
        entity_type="menu_item",
        canonical_id=CANONICAL_ID,
        field_name="price_usd",
        source=source_a,
        extracted_record=record_a,
        raw_value="8.00",
        observed_at=early,
    )
    assert _open_conflict(db_session, "menu_item", CANONICAL_ID, "price_usd") is None

    record_b, source_b = _make_record(db_session, "allears", {"price_usd": "13.00"})
    resolution = _write_and_resolve_field(
        db_session,
        entity_type="menu_item",
        canonical_id=CANONICAL_ID,
        field_name="price_usd",
        source=source_b,
        extracted_record=record_b,
        raw_value="13.00",
        observed_at=late,
    )

    assert resolution.has_disagreement is True
    conflict = _open_conflict(db_session, "menu_item", CANONICAL_ID, "price_usd")
    assert conflict is not None
    assert conflict.status == "open"
    assert conflict.candidate_values == {str(source_a.id): "8.00", str(source_b.id): "13.00"}


def test_repeated_disagreement_updates_existing_conflict_instead_of_duplicating(db_session):
    t1 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    t2 = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
    t3 = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

    record_a, source_a = _make_record(db_session, "disney_official", {"price_usd": "8.00"})
    _write_and_resolve_field(
        db_session,
        entity_type="menu_item",
        canonical_id=CANONICAL_ID,
        field_name="price_usd",
        source=source_a,
        extracted_record=record_a,
        raw_value="8.00",
        observed_at=t1,
    )

    record_b, source_b = _make_record(db_session, "allears", {"price_usd": "13.00"})
    _write_and_resolve_field(
        db_session,
        entity_type="menu_item",
        canonical_id=CANONICAL_ID,
        field_name="price_usd",
        source=source_b,
        extracted_record=record_b,
        raw_value="13.00",
        observed_at=t2,
    )

    record_c, source_c = _make_record(db_session, "disney_food_blog", {"price_usd": "13.50"})
    _write_and_resolve_field(
        db_session,
        entity_type="menu_item",
        canonical_id=CANONICAL_ID,
        field_name="price_usd",
        source=source_c,
        extracted_record=record_c,
        raw_value="13.50",
        observed_at=t3,
    )

    open_conflicts = db_session.scalars(
        select(MergeConflict).where(
            MergeConflict.entity_type == "menu_item",
            MergeConflict.canonical_id == CANONICAL_ID,
            MergeConflict.field_name == "price_usd",
        )
    ).all()
    assert len(open_conflicts) == 1, "a further disagreement must update the existing row, not add a new one"
    conflict = open_conflicts[0]
    assert conflict.status == "open"
    assert conflict.candidate_values == {
        str(source_a.id): "8.00",
        str(source_b.id): "13.00",
        str(source_c.id): "13.50",
    }


def test_conflict_is_marked_resolved_once_new_evidence_removes_the_disagreement(db_session):
    """_disagree()'s numeric-threshold branch only activates for raw int/float/
    Decimal values (see resolve/priority.py) - every current source adapter
    serializes price_usd as a str (e.g. disney_food_blog.py passes
    `str(price)`), which round-trips through the JSONB provenance column and
    is compared as a plain string forever after, so in production a
    disagreement on a string-valued field can never self-resolve once two
    distinct strings have been recorded (old provenance rows are never
    updated or deleted). This test drives the same bookkeeping with raw
    numeric values to prove the *numeric* comparison path - and therefore the
    open->resolved transition - behaves correctly when it is reached."""
    t1 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    t2 = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
    t3 = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)

    record_a, source_a = _make_record(db_session, "disney_official", {"price_usd": 100.0})
    _write_and_resolve_field(
        db_session,
        entity_type="menu_item",
        canonical_id=CANONICAL_ID,
        field_name="price_usd",
        source=source_a,
        extracted_record=record_a,
        raw_value=100.0,
        observed_at=t1,
    )

    record_b, source_b = _make_record(db_session, "allears", {"price_usd": 140.0})
    _write_and_resolve_field(
        db_session,
        entity_type="menu_item",
        canonical_id=CANONICAL_ID,
        field_name="price_usd",
        source=source_b,
        extracted_record=record_b,
        raw_value=140.0,
        observed_at=t2,
    )
    conflict = _open_conflict(db_session, "menu_item", CANONICAL_ID, "price_usd")
    assert conflict is not None and conflict.status == "open"

    # 120.0 is within the 20% disagreement threshold of *both* 100.0 and
    # 140.0, so once it becomes the most-recent (winning) value, none of the
    # candidates disagree with it any more.
    record_c, source_c = _make_record(db_session, "disney_food_blog", {"price_usd": 120.0})
    resolution = _write_and_resolve_field(
        db_session,
        entity_type="menu_item",
        canonical_id=CANONICAL_ID,
        field_name="price_usd",
        source=source_c,
        extracted_record=record_c,
        raw_value=120.0,
        observed_at=t3,
    )

    assert resolution.has_disagreement is False
    assert conflict.status == "resolved"
    assert conflict.resolved_at is not None
