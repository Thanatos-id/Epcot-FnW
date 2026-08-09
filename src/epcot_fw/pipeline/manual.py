"""Stages hand-curated booth facts into the normal resolution pipeline.

Some things no source publishes. Booth coordinates are the motivating case:
the app needs to sort booths by distance, and not one of the seven crawled
sources emits a latitude. Those facts get surveyed by hand into
`data/manual/booth_locations.json`.

Rather than writing them straight onto the canonical rows, they are staged as
ordinary `extracted_records` belonging to a `manual` source with
priority_rank 0. That buys three things for free: they merge onto the right
booth by the same fuzzy matching every crawled record goes through, they win
field resolution against every crawled source (rank 0 beats 1-7), and they
carry provenance, so `/booths/{id}/provenance` shows the coordinate came from
curation rather than a blog.

Re-applying an unchanged file is a no-op: the staged raw_page is keyed by the
file's content hash, and resolve short-circuits records that already have a
canonical link.
"""

import datetime
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import ExtractedRecord, RawPage, Source

logger = logging.getLogger(__name__)

MANUAL_SOURCE_KEY = "manual"
MANUAL_URL = "manual://booth-locations"
DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "manual" / "booth_locations.json"

# Curated keys that map onto booth payload fields the resolver understands.
# Anything else in the file (notably the "_README" block) is ignored.
BOOTH_FIELDS = ("latitude", "longitude", "location_description", "region_theme", "category")


def load_booth_overrides(path: Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    """Curated booth entries, skipping any without a usable name."""
    if not path.exists():
        return []

    payload = json.loads(path.read_text())
    entries = []
    for raw in payload.get("booths") or []:
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        entry: dict[str, Any] = {"name": name}
        for field in BOOTH_FIELDS:
            # `is not None` rather than truthiness: 0.0 is a legitimate
            # coordinate, and dropping it would silently lose a survey.
            if raw.get(field) is not None:
                entry[field] = raw[field]
        entries.append(entry)
    return entries


def _content_hash(entries: list[dict[str, Any]]) -> str:
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def stage_manual_overrides(session: Session, *, path: Path = DEFAULT_PATH) -> int:
    """Stage curated booth entries as extracted_records. Returns how many were
    staged - 0 when the file is empty or unchanged since the last run."""
    entries = load_booth_overrides(path)
    if not entries:
        return 0

    source = session.scalars(select(Source).where(Source.key == MANUAL_SOURCE_KEY)).first()
    if source is None:
        logger.warning(
            "no '%s' source row - run `epcot-fw db seed`; skipping curated overrides",
            MANUAL_SOURCE_KEY,
        )
        return 0

    digest = _content_hash(entries)
    existing = session.scalars(
        select(RawPage).where(RawPage.url == MANUAL_URL, RawPage.content_hash == digest)
    ).first()
    if existing is not None:
        return 0

    now = datetime.datetime.now(datetime.UTC)
    raw_page = RawPage(
        source_id=source.id,
        url=MANUAL_URL,
        page_kind="manual",
        fetched_at=now,
        http_status=200,
        content_hash=digest,
        raw_html=None,
        first_seen_at=now,
    )
    session.add(raw_page)
    session.flush()

    for entry in entries:
        session.add(
            ExtractedRecord(
                raw_page_id=raw_page.id,
                source_id=source.id,
                entity_type="booth",
                extracted_at=now,
                extractor_version="manual-1",
                payload=entry,
                natural_key_hint=None,
            )
        )
    session.flush()

    logger.info("staged %d curated booth override(s)", len(entries))
    return len(entries)
