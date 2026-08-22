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
from epcot_fw.normalize.text import normalize_name

logger = logging.getLogger(__name__)

MANUAL_SOURCE_KEY = "manual"
MANUAL_URL = "manual://booth-locations"
MANUAL_ITEMS_URL = "manual://menu-items"

_MANUAL_DIR = Path(__file__).resolve().parents[3] / "data" / "manual"
DEFAULT_PATH = _MANUAL_DIR / "booth_locations.json"
DEFAULT_ITEMS_PATH = _MANUAL_DIR / "menu_items.json"

# Curated keys that map onto booth payload fields the resolver understands.
# Anything else in the file (notably the "_README" block) is ignored.
BOOTH_FIELDS = (
    "latitude",
    "longitude",
    "location_precision",
    "location_description",
    "region_theme",
    "category",
)

# Same, for a dish. `booth_name` is not in this list because it is not an
# editable field - it is how the record finds the booth to be matched inside,
# exactly as a crawled menu_item record does.
MENU_ITEM_FIELDS = ("description", "price_usd", "category", "image_url", "dietary_tags")

# Carries the dish's existing name into `natural_key_hint` so a rename can
# find the row it is renaming. Stripped before the payload is stored - the
# canonical layer has no use for it once the match is made.
MATCH_KEY = "match_name"


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


def load_menu_item_overrides(path: Path = DEFAULT_ITEMS_PATH) -> list[dict[str, Any]]:
    """Curated menu-item entries.

    An entry needs a name and the booth it belongs to: menu items are matched
    within a booth, so a dish name with nothing to scope it cannot be resolved
    and is skipped rather than guessed at.
    """
    if not path.exists():
        return []

    payload = json.loads(path.read_text())
    entries = []
    for raw in payload.get("menu_items") or []:
        name = (raw.get("name") or "").strip()
        booth_name = (raw.get("booth_name") or "").strip()
        if not name or not booth_name:
            continue
        # `name` is how the dish is found; `rename_to`, when given, is what it
        # becomes. Keeping them separate is what makes a rename possible at
        # all - a record whose name is already the new one matches nothing.
        rename_to = (raw.get("rename_to") or "").strip()
        entry: dict[str, Any] = {
            "name": rename_to or name,
            "booth_name": booth_name,
            MATCH_KEY: name,
        }
        for field in MENU_ITEM_FIELDS:
            # `is not None` rather than truthiness: an empty dietary_tags list
            # is how a wrong tag gets removed, and 0 is a real price.
            if raw.get(field) is not None:
                entry[field] = raw[field]
        entries.append(entry)
    return entries


def _content_hash(entries: list[dict[str, Any]]) -> str:
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stage(
    session: Session,
    source: Source,
    *,
    url: str,
    entity_type: str,
    entries: list[dict[str, Any]],
) -> int:
    """Stage one curated file's entries, or 0 if it hasn't changed."""
    if not entries:
        return 0

    digest = _content_hash(entries)
    existing = session.scalars(
        select(RawPage).where(RawPage.url == url, RawPage.content_hash == digest)
    ).first()
    if existing is not None:
        return 0

    now = datetime.datetime.now(datetime.UTC)
    raw_page = RawPage(
        source_id=source.id,
        url=url,
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
        payload = {k: v for k, v in entry.items() if k != MATCH_KEY}
        match_name = entry.get(MATCH_KEY)
        session.add(
            ExtractedRecord(
                raw_page_id=raw_page.id,
                source_id=source.id,
                entity_type=entity_type,
                extracted_at=now,
                extractor_version="manual-1",
                payload=payload,
                natural_key_hint=normalize_name(match_name) if match_name else None,
            )
        )
    session.flush()
    return len(entries)


def stage_manual_overrides(
    session: Session,
    *,
    path: Path = DEFAULT_PATH,
    items_path: Path = DEFAULT_ITEMS_PATH,
) -> int:
    """Stage every curated entry as extracted_records. Returns how many were
    staged - 0 when the files are empty or unchanged since the last run."""
    booths = load_booth_overrides(path)
    items = load_menu_item_overrides(items_path)
    if not booths and not items:
        return 0

    source = session.scalars(select(Source).where(Source.key == MANUAL_SOURCE_KEY)).first()
    if source is None:
        logger.warning(
            "no '%s' source row - run `epcot-fw db seed`; skipping curated overrides",
            MANUAL_SOURCE_KEY,
        )
        return 0

    # Two files, two raw_pages: editing dish corrections must not restage
    # every booth coordinate, and vice versa.
    staged = _stage(session, source, url=MANUAL_URL, entity_type="booth", entries=booths)
    staged += _stage(
        session, source, url=MANUAL_ITEMS_URL, entity_type="menu_item", entries=items
    )

    if staged:
        logger.info("staged %d curated override(s)", staged)
    return staged
