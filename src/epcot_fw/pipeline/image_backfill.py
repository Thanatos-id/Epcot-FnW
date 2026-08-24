"""Backfill this year's menu-item photos from prior seasons of the same source.

DFB's 2026 hub carries zero photos of its own - see sources/disney_food_blog.py
for why. But World Showcase pavilions repeat much of their lineup season to
season ("Kirschwasser Torte" at Germany is not new), so a photo captured in
2022-2025 is very often still a photo of a dish being sold today.

Three rules keep this from inventing anything:

1. A photo only ever attaches to a menu_item that already exists on the
   *current, active* festival menu. A caption for a dish that has not
   returned this year is reported and dropped, never used to create one.
2. The booth and the dish are each matched against this year's real rows
   with the same fuzzy-match confidence the rest of the pipeline requires
   (resolve/matcher.AUTO_MERGE_THRESHOLD). Anything short of that is
   reported, not guessed at.
3. This never touches Booth.image_url. The user asked for dish photos, not
   booth/location photos, and a booth also being the only thing with a
   confident match is not license to photograph it.

Results are written to data/manual/menu_items.json - the same curated
overlay the editor exports to - rather than to the database directly, so a
backfill run is reviewable and reversible exactly like a hand-typed
correction, and only ever takes effect through `epcot-fw manual`. An
existing image_url, in the database or already pending in that file, is
never overwritten by this: a human's answer, or something already staged,
always outranks a historical guess. (Compare pipeline/photo_workflow.py's
import step, which is a deliberate publish rather than a background search
and overwrites on purpose - see merge_menu_item_overrides in
pipeline/manual.py for both sides of that.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import Booth, Festival, MenuItem, Source
from epcot_fw.normalize.text import normalize_name
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.pipeline.manual import DEFAULT_ITEMS_PATH, merge_menu_item_overrides
from epcot_fw.resolve.matcher import Candidate, find_best_match
from epcot_fw.sources.disney_food_blog import DisneyFoodBlogAdapter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillMatch:
    booth_name: str  # this year's canonical booth name
    item_name: str  # this year's canonical dish name
    image_url: str
    source_year: int
    caption: str  # the historical caption, kept for the report


@dataclass(frozen=True)
class SkippedCaption:
    year: int
    booth_name: str
    caption: str


@dataclass
class BackfillReport:
    years_scanned: list[int]
    photo_posts_fetched: int = 0
    captions_found: int = 0
    matched: list[BackfillMatch] = field(default_factory=list)
    skipped_no_booth_match: list[SkippedCaption] = field(default_factory=list)
    skipped_no_item_match: list[SkippedCaption] = field(default_factory=list)
    skipped_already_pictured: list[BackfillMatch] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "years_scanned": self.years_scanned,
            "photo_posts_fetched": self.photo_posts_fetched,
            "captions_found": self.captions_found,
            "matched": len(self.matched),
            "skipped_no_booth_match": len(self.skipped_no_booth_match),
            "skipped_no_item_match": len(self.skipped_no_item_match),
            "skipped_already_pictured": len(self.skipped_already_pictured),
        }


def _historical_dish_photos(
    adapter: DisneyFoodBlogAdapter, years: list[int]
) -> tuple[list[tuple[int, ExtractedRecordDTO]], int]:
    """(year, record) for every captioned dish photo found across `years`,
    plus how many photo posts were actually fetched."""
    from epcot_fw.fetch import http_client

    dated_records: list[tuple[int, ExtractedRecordDTO]] = []
    fetched = 0

    for year in years:
        try:
            seeds = adapter.historical_detail_seeds(year)
        except Exception:
            logger.warning("could not read the %s photo hub - skipping that year", year, exc_info=True)
            continue

        for seed in seeds:
            try:
                result = http_client.fetch(seed.url, crawl_delay_sec=5)
            except Exception:
                logger.warning("fetch failed for %s", seed.url, exc_info=True)
                continue
            if not (200 <= result.status_code < 300) or not result.text:
                continue
            fetched += 1
            try:
                records = adapter.parse(result.text, seed.url, seed.page_kind)
            except Exception:
                logger.warning("parse failed for %s", seed.url, exc_info=True)
                continue
            dated_records.extend((year, record) for record in records)

    return dated_records, fetched


def _active_booth_candidates(session: Session, festival_id: int) -> tuple[list[Candidate], dict[int, str]]:
    rows = session.execute(
        select(Booth.id, Booth.canonical_name).where(
            Booth.festival_id == festival_id, Booth.is_active.is_(True)
        )
    ).all()
    candidates = [Candidate(canonical_id=r.id, natural_key=normalize_name(r.canonical_name)) for r in rows]
    names = {r.id: r.canonical_name for r in rows}
    return candidates, names


def _match_dish(
    session: Session, booth_id: int, caption: str
) -> tuple[int, str, str | None] | None:
    """(item_id, canonical_name, existing_image_url) for the current active
    dish this caption confidently names, or None."""
    rows = session.execute(
        select(MenuItem.id, MenuItem.canonical_name, MenuItem.image_url).where(
            MenuItem.booth_id == booth_id, MenuItem.is_active.is_(True)
        )
    ).all()
    candidates = [Candidate(canonical_id=r.id, natural_key=normalize_name(r.canonical_name)) for r in rows]
    match = find_best_match(normalize_name(caption), candidates)
    if match.outcome != "auto_merge":
        return None
    row = next(r for r in rows if r.id == match.canonical_id)
    return row.id, row.canonical_name, row.image_url


def backfill_dish_images(
    session: Session,
    *,
    years: int = 5,
    path: Path = DEFAULT_ITEMS_PATH,
    dry_run: bool = False,
) -> BackfillReport:
    """Search the past `years` seasons of DFB's per-booth photo posts for
    photos of dishes still on this year's menu, and stage confident matches
    into `path` for `epcot-fw manual` to apply.

    `dry_run=True` runs the whole search and returns what it would have
    written, without touching the file - use it to see the match counts
    before committing to a run over several seasons' worth of pages.
    """
    festival = session.scalars(select(Festival).order_by(Festival.year.desc())).first()
    if festival is None:
        raise RuntimeError("No festival row found - run `epcot-fw db seed` first.")

    source = session.scalars(select(Source).where(Source.key == "disney_food_blog")).first()
    if source is None:
        raise RuntimeError("disney_food_blog is not a known source - run `epcot-fw db seed` first.")

    year_list = [festival.year - n for n in range(1, years + 1)]

    booth_candidates, booth_name_by_id = _active_booth_candidates(session, festival.id)

    adapter = DisneyFoodBlogAdapter()
    dated_records, fetched = _historical_dish_photos(adapter, year_list)

    matched: dict[tuple[int, int], BackfillMatch] = {}
    already_pictured: list[BackfillMatch] = []
    skipped_no_booth: list[SkippedCaption] = []
    skipped_no_item: list[SkippedCaption] = []

    # Most recent season first, so the first (and only) match kept for a
    # given (booth, dish) is the newest photo of it - a 2025 shot of a dish
    # over a 2021 one, when both exist.
    for year, record in sorted(dated_records, key=lambda pair: -pair[0]):
        payload = record.payload
        booth_name = payload.get("booth_name") or ""
        caption = payload["name"]
        image_url = payload.get("image_url")
        if not image_url:
            continue

        booth_match = find_best_match(normalize_name(booth_name), booth_candidates)
        if booth_match.outcome != "auto_merge":
            skipped_no_booth.append(SkippedCaption(year, booth_name, caption))
            continue
        booth_id = booth_match.canonical_id
        assert booth_id is not None

        item = _match_dish(session, booth_id, caption)
        if item is None:
            skipped_no_item.append(SkippedCaption(year, booth_name, caption))
            continue
        item_id, item_name, existing_image_url = item

        key = (booth_id, item_id)
        if key in matched:
            continue  # a more recent season already claimed this dish

        candidate = BackfillMatch(
            booth_name=booth_name_by_id[booth_id],
            item_name=item_name,
            image_url=image_url,
            source_year=year,
            caption=caption,
        )
        if existing_image_url:
            already_pictured.append(candidate)
            continue

        matched[key] = candidate

    if not dry_run and matched:
        merge_menu_item_overrides(
            path,
            [
                {"booth_name": m.booth_name, "name": m.item_name, "image_url": m.image_url}
                for m in matched.values()
            ],
            overwrite=False,
        )

    return BackfillReport(
        years_scanned=year_list,
        photo_posts_fetched=fetched,
        captions_found=len(dated_records),
        matched=sorted(matched.values(), key=lambda m: (m.booth_name, m.item_name)),
        skipped_no_booth_match=skipped_no_booth,
        skipped_no_item_match=skipped_no_item,
        skipped_already_pictured=already_pictured,
    )


