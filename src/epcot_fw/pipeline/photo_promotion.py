"""Lets this season's photo of a dish supersede last season's stand-in.

`backfill-images` searches prior seasons for a photo of a dish still on the
menu and stages what it finds into data/manual/menu_items.json. That file is
the curated source at priority_rank 0, which is the whole point for a
correction somebody typed - and the wrong rank for a best-effort search,
because it means a historical guess outranks every later observation
permanently.

That cost nothing while the current season had no photos of its own. The
moment Disney Food Blog starts publishing 2026 reviews it costs the thing
the crawl exists for: a dish ends up showing a 2025 plate while an actual
photo of what is being served today sits underneath it, selected against,
for the rest of the season.

This clears the historical value once a real one has arrived - and only
then. Three conditions, all required:

  * the value currently winning comes from curation;
  * it is not one published from docs/studio.html. A photo someone attached
    by hand is an answer, not a stand-in, and stays on top whatever the
    crawl finds. Those are the ones served from this project's own Pages
    site, which is how they are told apart;
  * some crawled source is offering a photo from the current festival year,
    and the curated one is not from that year.

Nothing is invented and nothing is downloaded: this only ever stops
preferring a value that is already there, so the worst case of running it is
that a dish shows a newer photo of itself.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import Booth, EntityFieldProvenance, Festival, MenuItem
from epcot_fw.pipeline.manual import DEFAULT_ITEMS_PATH, MANUAL_SOURCE_KEY
from epcot_fw.resolve.priority import FieldCandidate, resolve_field

logger = logging.getLogger(__name__)

FIELD = "image_url"

# WordPress files uploads under /wp-content/uploads/YYYY/MM/, which is what
# dates a photo to a season. A URL with no such stamp is treated as undated
# rather than as current - the point is to promote a photo known to be from
# this year, not to demote anything that cannot be read.
_UPLOAD_YEAR_RE = re.compile(r"/uploads/(?P<year>20\d{2})/")

# Photos this project published itself, from docs/studio.html. Matched on the
# path rather than the host so a fork's Pages domain works too.
_OWN_PHOTO_PATH = "/dish-photos/"


@dataclass(frozen=True)
class Promotion:
    booth_name: str
    dish_name: str
    was: str
    now: str


@dataclass
class PromotionReport:
    promotions: list[Promotion] = field(default_factory=list)
    kept_hand_attached: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.promotions)


def photo_season(image_url: str | None) -> int | None:
    """The festival year a photo URL dates itself to, if it says."""
    if not image_url:
        return None
    match = _UPLOAD_YEAR_RE.search(image_url)
    return int(match.group("year")) if match else None


def is_hand_published(image_url: str | None) -> bool:
    return bool(image_url) and _OWN_PHOTO_PATH in image_url


def _clear_curated_image(path: Path, wanted: set[tuple[str, str]]) -> int:
    """Drop `image_url` from the curated entries naming these (booth, dish)
    pairs, and drop an entry that carried nothing else. Everything the file
    says about anything else is left exactly as it was."""
    if not path.exists():
        return 0
    payload: dict[str, Any] = json.loads(path.read_text())
    entries: list[dict[str, Any]] = list(payload.get("menu_items") or [])

    kept: list[dict[str, Any]] = []
    cleared = 0
    for entry in entries:
        key = (entry.get("booth_name"), entry.get("name"))
        if key in wanted and entry.get(FIELD):
            entry = {k: v for k, v in entry.items() if k != FIELD}
            cleared += 1
            # booth_name and name are only ever there to find the dish; with
            # nothing left to say about it the entry is noise.
            if set(entry) <= {"booth_name", "name"}:
                continue
        kept.append(entry)

    if cleared:
        payload["menu_items"] = kept
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return cleared


def promote_current_season_photos(
    session: Session,
    *,
    path: Path = DEFAULT_ITEMS_PATH,
    dry_run: bool = False,
) -> PromotionReport:
    """Stop preferring a historical curated photo wherever a current-season
    crawled one is available."""
    festival = session.scalars(select(Festival).order_by(Festival.year.desc())).first()
    if festival is None:
        raise RuntimeError("No festival row found - run `epcot-fw db seed` first.")

    rows = session.scalars(
        select(EntityFieldProvenance).where(
            EntityFieldProvenance.entity_type == "menu_item",
            EntityFieldProvenance.field_name == FIELD,
        )
    ).all()
    by_item: dict[int, list[EntityFieldProvenance]] = {}
    for row in rows:
        by_item.setdefault(row.canonical_id, []).append(row)

    report = PromotionReport()
    to_clear: set[tuple[str, str]] = set()
    stale_rows: list[EntityFieldProvenance] = []

    for item_id, candidates in by_item.items():
        selected = next((c for c in candidates if c.is_selected), None)
        if selected is None or selected.source.key != MANUAL_SOURCE_KEY:
            continue

        item = session.get(MenuItem, item_id)
        if item is None or not item.is_active:
            continue

        if is_hand_published(selected.value):
            report.kept_hand_attached.append(item.canonical_name)
            continue
        if photo_season(selected.value) == festival.year:
            continue

        fresh = next(
            (
                c
                for c in candidates
                if c.source.key != MANUAL_SOURCE_KEY and photo_season(c.value) == festival.year
            ),
            None,
        )
        if fresh is None:
            continue

        booth = session.get(Booth, item.booth_id)
        report.promotions.append(
            Promotion(
                booth_name=booth.canonical_name if booth else "?",
                dish_name=item.canonical_name,
                was=str(selected.value),
                now=str(fresh.value),
            )
        )
        to_clear.add((booth.canonical_name if booth else "", item.canonical_name))

        # Every historical curated candidate for this dish, not just the one
        # currently winning. The curated file gets restaged whenever its
        # contents change, and each staging leaves its own provenance row -
        # most dishes here carry three. Removing only the selected one just
        # promotes the next identical row into its place, so the same dish
        # comes back as a promotion on the next run, and the run after that.
        stale_rows.extend(
            c
            for c in candidates
            if c.source.key == MANUAL_SOURCE_KEY
            and not is_hand_published(c.value)
            and photo_season(c.value) != festival.year
        )

    if dry_run or not report.promotions:
        return report

    # The curated file and the staged candidate have to go together: clearing
    # only the file leaves the provenance row still winning, and clearing only
    # the row lets the next `epcot-fw manual` restage it.
    _clear_curated_image(path, to_clear)

    doomed = {row.id for row in stale_rows}
    for stale in stale_rows:
        session.delete(stale)
    session.flush()

    for item_id in {row.canonical_id for row in stale_rows}:
        remaining = [c for c in by_item[item_id] if c.id not in doomed]
        resolution = resolve_field(
            FIELD,
            [
                FieldCandidate(
                    ref=c.id,
                    source_id=c.source_id,
                    priority_rank=c.source.priority_rank,
                    observed_at=c.observed_at,
                    value=c.value,
                )
                for c in remaining
            ],
        )
        for c in remaining:
            c.is_selected = c.id in resolution.winner_refs
        item = session.get(MenuItem, item_id)
        if item is not None:
            item.image_url = resolution.value
    session.flush()
    return report
