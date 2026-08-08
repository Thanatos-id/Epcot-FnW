import datetime
import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from epcot_fw.db.models import Booth, ExtractedRecord, Review, Source
from epcot_fw.normalize.text import normalize_name


def _mentions_booth(normalized_review_text: str, normalized_booth_name: str) -> bool:
    if not normalized_booth_name:
        return False
    pattern = r"\b" + re.escape(normalized_booth_name) + r"\b"
    return re.search(pattern, normalized_review_text) is not None


def attach_review(
    session: Session, extracted_record: ExtractedRecord, source: Source, *, festival_id: int
) -> int:
    """Scan one raw review's free text for canonical booth-name mentions
    within this festival and insert a Review row per match.

    Unlike every other entity_type, a review legitimately attaches to zero,
    one, or several booths in the same pass (a single review often praises
    one booth and pans another in the same paragraph) - so this doesn't fit
    the 1:1 matcher/canonical_links pattern the rest of resolve/merge.py
    uses. Idempotency instead comes from the reviews table's own unique
    constraint (entity_type, entity_id, source_id, external_review_id) via
    ON CONFLICT DO NOTHING, so re-running this against the same review is
    always safe.

    Returns the number of booths this review was newly matched to (0 if the
    review mentioned no known booth by name, or lacked a usable rating).
    """
    payload = extracted_record.payload
    review_text = payload.get("review_text") or ""
    normalized_text = normalize_name(review_text)
    if not normalized_text:
        return 0

    rating_raw = payload.get("rating_raw")
    if rating_raw is None:
        return 0
    rating_scale = payload.get("rating_scale") or 10
    rating_5 = round(Decimal(rating_raw) * Decimal(5) / Decimal(rating_scale), 1)

    reviewed_at_str = payload.get("reviewed_at")
    reviewed_at = datetime.date.fromisoformat(reviewed_at_str) if reviewed_at_str else None

    booths = session.scalars(select(Booth).where(Booth.festival_id == festival_id)).all()

    matched = 0
    for booth in booths:
        booth_key = normalize_name(booth.canonical_name)
        if not _mentions_booth(normalized_text, booth_key):
            continue

        stmt = (
            pg_insert(Review)
            .values(
                entity_type="booth",
                entity_id=booth.id,
                source_id=source.id,
                external_review_id=payload.get("external_review_id"),
                reviewer_name=payload.get("reviewer_name"),
                rating=rating_5,
                rating_raw=Decimal(rating_raw),
                recommended=payload.get("recommended"),
                review_text=review_text,
                review_url=payload.get("review_url"),
                reviewed_at=reviewed_at,
                match_method="booth_name_mention",
            )
            .on_conflict_do_nothing(constraint="uq_reviews_entity_source_external")
            .returning(Review.id)
        )
        # rowcount is not reliably 0 on a suppressed ON CONFLICT DO NOTHING
        # across drivers - RETURNING is the actual SQL-level signal for
        # whether a row was inserted, which is what makes this idempotent
        # rerun detection (and thus the reported reviews_matched count)
        # trustworthy.
        inserted_id = session.execute(stmt).scalar()
        if inserted_id is not None:
            matched += 1

    return matched
