import datetime
import re
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from epcot_fw.db.models import (
    Booth,
    CanonicalLink,
    ConcertEvent,
    EntityFieldProvenance,
    ExtractedRecord,
    Festival,
    MenuItem,
    MergeConflict,
    Seminar,
    Source,
)
from epcot_fw.normalize.dietary_tags import (
    extract_dietary_tags,  # noqa: F401 (re-export convenience)
)
from epcot_fw.normalize.text import normalize_name
from epcot_fw.resolve.matcher import Candidate, find_best_match
from epcot_fw.resolve.priority import FieldCandidate, resolve_field

ENTITY_MODEL: dict[str, type] = {
    "festival": Festival,
    "booth": Booth,
    "menu_item": MenuItem,
    "event": ConcertEvent,
    "seminar": Seminar,
}

NAME_PAYLOAD_KEY: dict[str, str] = {
    "festival": "name",
    "booth": "name",
    "menu_item": "name",
    "event": "artist_name",
    "seminar": "title",
}

NAME_MODEL_FIELD: dict[str, str] = {
    "festival": "name",
    "booth": "canonical_name",
    "menu_item": "canonical_name",
    "event": "artist_name",
    "seminar": "title",
}

# payload key -> canonical column name, for fields that are plain scalar copies
# once resolved. dietary_tags (menu_item) is handled separately as an M2M.
FIELD_MAP: dict[str, dict[str, str]] = {
    "festival": {"name": "name", "start_date": "start_date", "end_date": "end_date", "official_url": "official_url"},
    "booth": {
        "name": "canonical_name",
        "category": "category",
        "region_theme": "region_theme",
        "description": "description",
        "image_url": "image_url",
    },
    "menu_item": {"name": "canonical_name", "description": "description", "category": "category", "price_usd": "price_usd"},
    "event": {"artist_name": "artist_name", "performance_date": "performance_date", "venue": "venue", "description": "description"},
    "seminar": {
        "title": "title",
        "seminar_type": "seminar_type",
        "description": "description",
        "presenter_names": "presenter_names",
        "event_date": "event_date",
        "venue": "venue",
        "price_usd": "price_usd",
    },
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "item"


def _coerce(model_cls: type, field_name: str, value: Any) -> Any:
    if value is None:
        return None
    column = model_cls.__table__.columns.get(field_name)
    if column is None:
        return value
    try:
        py_type = column.type.python_type
    except NotImplementedError:
        return value
    if py_type is datetime.date and isinstance(value, str):
        return datetime.date.fromisoformat(value)
    if py_type is datetime.time and isinstance(value, str):
        return datetime.time.fromisoformat(value)
    if py_type is Decimal and not isinstance(value, Decimal):
        return Decimal(str(value))
    return value


def resolve_booth_id(session: Session, festival_id: int, booth_name_hint: str | None) -> int | None:
    """Look up an already-canonicalized booth by fuzzy name match, for linking
    a menu_item extracted record to its parent. Only an auto_merge-confidence
    match counts - anything shakier means "no confident parent", not a
    fabricated relationship."""
    if not booth_name_hint:
        return None
    key = normalize_name(booth_name_hint)
    rows = session.scalars(select(Booth).where(Booth.festival_id == festival_id)).all()
    candidates = [Candidate(canonical_id=b.id, natural_key=normalize_name(b.canonical_name)) for b in rows]
    result = find_best_match(key, candidates)
    if result.outcome == "auto_merge":
        return result.canonical_id
    return None


def _create_new(entity_type: str, *, festival_id: int, booth_id: int | None, name: str) -> Any:
    if entity_type == "festival":
        year = datetime.date.today().year
        return Festival(year=year, name=name, slug=f"{slugify(name)}-{year}", status="upcoming")
    if entity_type == "booth":
        return Booth(festival_id=festival_id, canonical_name=name, slug=slugify(name))
    if entity_type == "menu_item":
        return MenuItem(booth_id=booth_id, canonical_name=name, category="food")
    if entity_type == "event":
        return ConcertEvent(
            festival_id=festival_id, artist_name=name, performance_date=datetime.date.today()
        )
    if entity_type == "seminar":
        return Seminar(festival_id=festival_id, title=name, seminar_type="culinary_demo")
    raise ValueError(f"unknown entity_type {entity_type}")


def _load_scoped_candidates(
    session: Session, entity_type: str, *, festival_id: int, booth_id: int | None
) -> list[Candidate]:
    model_cls = ENTITY_MODEL[entity_type]
    name_field = getattr(model_cls, NAME_MODEL_FIELD[entity_type])

    if entity_type == "festival":
        stmt = select(model_cls.id, name_field)
    elif entity_type == "menu_item":
        stmt = select(model_cls.id, name_field).where(model_cls.booth_id == booth_id)
    else:
        stmt = select(model_cls.id, name_field).where(model_cls.festival_id == festival_id)

    rows = session.execute(stmt).all()
    return [Candidate(canonical_id=row[0], natural_key=normalize_name(row[1])) for row in rows]


def _open_conflict(
    session: Session, entity_type: str, canonical_id: int | None, field_name: str | None
) -> MergeConflict | None:
    stmt = select(MergeConflict).where(
        MergeConflict.entity_type == entity_type,
        MergeConflict.canonical_id == canonical_id,
        MergeConflict.field_name == field_name,
        MergeConflict.status == "open",
    )
    return session.scalars(stmt).first()


def _match_conflict_already_flagged(session: Session, entity_type: str, extracted_record_id: int) -> bool:
    """Guards the "no confident match" conflict-creation paths (unmatched
    booth reference, review-band fuzzy match) against duplicating a conflict
    every time run_resolve revisits a still-unlinked extracted_record - those
    records have no canonical_links row to short-circuit on, so without this
    check re-running `epcot-fw refresh`/`resolve` would pile up a fresh
    duplicate conflict per run for the same unresolved record."""
    stmt = select(MergeConflict.id).where(
        MergeConflict.entity_type == entity_type,
        MergeConflict.field_name.is_(None),
        MergeConflict.candidate_values["extracted_record_id"].as_string() == str(extracted_record_id),
    )
    return session.scalars(stmt).first() is not None


def _write_and_resolve_field(
    session: Session,
    *,
    entity_type: str,
    canonical_id: int,
    field_name: str,
    source: Source,
    extracted_record: ExtractedRecord,
    raw_value: Any,
    observed_at: datetime.datetime,
):
    """Write this source's candidate value for a field and re-resolve the
    winner across all candidates seen so far for that field. Returns the
    FieldResolution; does not touch the canonical ORM object - callers decide
    how to apply it (plain setattr for scalar columns, M2M sync for
    relationships like menu_item.dietary_tags)."""
    json_value = str(raw_value) if isinstance(raw_value, Decimal) else raw_value

    stmt = (
        pg_insert(EntityFieldProvenance)
        .values(
            entity_type=entity_type,
            canonical_id=canonical_id,
            field_name=field_name,
            source_id=source.id,
            extracted_record_id=extracted_record.id,
            value=json_value,
            observed_at=observed_at,
            is_selected=False,
        )
        .on_conflict_do_nothing(constraint="uq_field_prov_candidate")
    )
    session.execute(stmt)
    session.flush()

    rows = session.scalars(
        select(EntityFieldProvenance).where(
            EntityFieldProvenance.entity_type == entity_type,
            EntityFieldProvenance.canonical_id == canonical_id,
            EntityFieldProvenance.field_name == field_name,
        )
    ).all()

    candidates = [
        FieldCandidate(
            ref=row.id,
            source_id=row.source_id,
            priority_rank=row.source.priority_rank,
            observed_at=row.observed_at,
            value=row.value,
        )
        for row in rows
    ]
    resolution = resolve_field(field_name, candidates)

    for row in rows:
        row.is_selected = row.id in resolution.winner_refs

    conflict = _open_conflict(session, entity_type, canonical_id, field_name)
    if resolution.has_disagreement:
        candidate_map = {str(c.source_id): c.value for c in candidates}
        if conflict is None:
            session.add(
                MergeConflict(
                    entity_type=entity_type,
                    canonical_id=canonical_id,
                    field_name=field_name,
                    candidate_values=candidate_map,
                    status="open",
                    opened_at=datetime.datetime.now(datetime.UTC),
                )
            )
        else:
            conflict.candidate_values = candidate_map
    elif conflict is not None:
        conflict.status = "resolved"
        conflict.resolved_at = datetime.datetime.now(datetime.UTC)

    return resolution


def resolve_extracted_record(
    session: Session,
    extracted_record: ExtractedRecord,
    source: Source,
    *,
    festival_id: int,
) -> None:
    """Idempotently match+merge one extracted_record into the canonical layer.

    Safe to call repeatedly for the same extracted_record (a prior
    canonical_links row for it short-circuits the whole thing), which is what
    makes `epcot-fw refresh` runs idempotent.
    """
    existing_link = session.scalars(
        select(CanonicalLink).where(CanonicalLink.extracted_record_id == extracted_record.id)
    ).first()
    if existing_link is not None:
        return

    entity_type = extracted_record.entity_type
    payload = extracted_record.payload
    name = payload.get(NAME_PAYLOAD_KEY[entity_type])
    if not name:
        return

    booth_id: int | None = None
    if entity_type == "menu_item":
        booth_id = resolve_booth_id(session, festival_id, payload.get("booth_name"))
        if booth_id is None:
            if not _match_conflict_already_flagged(session, "menu_item", extracted_record.id):
                session.add(
                    MergeConflict(
                        entity_type="menu_item",
                        canonical_id=None,
                        field_name=None,
                        candidate_values={
                            "booth_name": payload.get("booth_name"),
                            "item": name,
                            "extracted_record_id": extracted_record.id,
                        },
                        status="open",
                        opened_at=datetime.datetime.now(datetime.UTC),
                    )
                )
            return

    candidates = _load_scoped_candidates(session, entity_type, festival_id=festival_id, booth_id=booth_id)
    match = find_best_match(extracted_record.natural_key_hint or normalize_name(name), candidates)

    if match.outcome == "review":
        if not _match_conflict_already_flagged(session, entity_type, extracted_record.id):
            session.add(
                MergeConflict(
                    entity_type=entity_type,
                    canonical_id=match.canonical_id,
                    field_name=None,
                    candidate_values={
                        "extracted_name": name,
                        "score": match.score,
                        "extracted_record_id": extracted_record.id,
                    },
                    status="open",
                    opened_at=datetime.datetime.now(datetime.UTC),
                )
            )
        return

    if match.outcome == "new_entity":
        model_obj = _create_new(entity_type, festival_id=festival_id, booth_id=booth_id, name=name)
        session.add(model_obj)
        session.flush()
        canonical_id = model_obj.id
        match_method = "new"
    else:
        canonical_id = match.canonical_id
        model_obj = session.get(ENTITY_MODEL[entity_type], canonical_id)
        match_method = "fuzzy_name"

    session.add(
        CanonicalLink(
            entity_type=entity_type,
            canonical_id=canonical_id,
            extracted_record_id=extracted_record.id,
            source_id=source.id,
            match_confidence=match.score,
            match_method=match_method,
            matched_at=datetime.datetime.now(datetime.UTC),
        )
    )

    observed_at = extracted_record.extracted_at
    for payload_key, field_name in FIELD_MAP[entity_type].items():
        raw_value = payload.get(payload_key)
        if raw_value is None:
            continue
        resolution = _write_and_resolve_field(
            session,
            entity_type=entity_type,
            canonical_id=canonical_id,
            field_name=field_name,
            source=source,
            extracted_record=extracted_record,
            raw_value=raw_value,
            observed_at=observed_at,
        )
        if resolution.value is not None:
            setattr(model_obj, field_name, _coerce(type(model_obj), field_name, resolution.value))

    if entity_type == "menu_item" and payload.get("dietary_tags"):
        resolution = _write_and_resolve_field(
            session,
            entity_type=entity_type,
            canonical_id=canonical_id,
            field_name="dietary_tags",
            source=source,
            extracted_record=extracted_record,
            raw_value=payload.get("dietary_tags") or [],
            observed_at=observed_at,
        )
        _sync_dietary_tags(session, model_obj, resolution.value or [])

    session.flush()


def _sync_dietary_tags(session: Session, menu_item: MenuItem, codes: list[str]) -> None:
    from epcot_fw.db.models import DietaryTag

    if not codes:
        return
    tags = session.scalars(select(DietaryTag).where(DietaryTag.code.in_(codes))).all()
    menu_item.dietary_tags = list(tags)
