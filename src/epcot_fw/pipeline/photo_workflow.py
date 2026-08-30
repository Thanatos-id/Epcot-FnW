"""Round-trip dish photos out to a folder for external processing (an AI
image pass, a designer, a manual crop) and back in as curated overrides.

Two commands, meant to be used in sequence:

    epcot-fw images export ./dish-photos
    ...process every file in ./dish-photos with whatever tool you like...
    epcot-fw images import ./dish-photos

Files are named by the dish's public_id, not its name or booth. A name is
scraped text that changes - punctuation gets cleaned up, a rename lands
through the editor - but public_id is the one thing guaranteed stable
across a rebuild, and the same thing the app itself saves a favourite by.
Whatever comes back from processing only has to keep that filename to be
matched to the right dish; nothing else about it needs to line up, and an
AI tool is free to change the file extension (a JPEG in, a PNG out) without
breaking the match.

This only ever reads and writes MenuItem.image_url. There is no code path
here that touches a Booth - the export query doesn't select one, and the
curated file this writes to (data/manual/menu_items.json) has no field for
one. Location photos are a different feature this deliberately isn't.
"""

from __future__ import annotations

import csv
import datetime
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import Booth, MenuItem
from epcot_fw.pipeline.manual import DEFAULT_ITEMS_PATH, merge_menu_item_overrides

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
_DEFAULT_EXTENSION = ".jpg"

# Where published dish photos go, anchored to the repo rather than to
# whatever directory the command was typed in.
#
# A cwd-relative default is silent when it is wrong: run from anywhere but
# the repo root and the photos are written to ./docs/dish-photos under that
# directory, while the image_url recorded against the dish still points at
# the published Pages path. The curated file gets its correction, the
# database says the dish has a photo, the site 404s, and nothing anywhere
# reports a problem. The curated files themselves have always resolved this
# way (see pipeline/manual.py); this brings the photos in line with them.
DEFAULT_PUBLISH_DIR = Path(__file__).resolve().parents[3] / "docs" / "dish-photos"


@dataclass(frozen=True)
class PhotoRecord:
    public_id: str
    booth_name: str
    dish_name: str
    category: str
    original_url: str
    filename: str
    downloaded: bool


@dataclass
class ExportReport:
    photos: list[PhotoRecord] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.photos)

    @property
    def downloaded(self) -> int:
        return sum(1 for p in self.photos if p.downloaded)

    @property
    def failed(self) -> list[PhotoRecord]:
        return [p for p in self.photos if not p.downloaded]


@dataclass
class ImportReport:
    published: list[str] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)


def _guess_extension(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    # A bare, plausible-looking image extension only - anything else (no
    # suffix, or a query-string artifact like ".php") falls back rather than
    # naming a file something misleading.
    return suffix if suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif") else _DEFAULT_EXTENSION


def _download_bytes(url: str, *, crawl_delay_sec: float = 5.0) -> bytes | None:
    """A plain, polite binary fetch - robots.txt and per-domain rate limits
    apply the same as any page fetch. Not fetch/http_client.fetch(), which
    decodes the body as text and would corrupt image bytes."""
    import httpx

    from epcot_fw.config import settings
    from epcot_fw.fetch import rate_limiter, robots

    if not robots.is_allowed(url):
        logger.warning("robots.txt disallows fetching %s - skipping", url)
        return None
    rate_limiter.wait_for_domain(url, crawl_delay_sec)
    try:
        resp = httpx.get(
            url, headers={"User-Agent": settings.user_agent}, timeout=20, follow_redirects=True
        )
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPError:
        logger.warning("failed to download %s", url, exc_info=True)
        return None


def export_dish_photos(session: Session, out_dir: Path) -> ExportReport:
    """Download every active dish's current photo into `out_dir`, named by
    its public_id, plus a manifest for `import_dish_photos` to read back."""
    rows = session.execute(
        select(
            MenuItem.public_id,
            MenuItem.canonical_name,
            MenuItem.category,
            MenuItem.image_url,
            Booth.canonical_name.label("booth_name"),
        )
        .join(Booth, Booth.id == MenuItem.booth_id)
        .where(MenuItem.is_active.is_(True), MenuItem.image_url.isnot(None))
        .order_by(Booth.canonical_name, MenuItem.canonical_name)
    ).all()

    out_dir.mkdir(parents=True, exist_ok=True)
    photos: list[PhotoRecord] = []

    for row in rows:
        filename = f"{row.public_id}{_guess_extension(row.image_url)}"
        content = _download_bytes(row.image_url)
        if content is not None:
            (out_dir / filename).write_bytes(content)
        photos.append(
            PhotoRecord(
                public_id=str(row.public_id),
                booth_name=row.booth_name,
                dish_name=row.canonical_name,
                category=row.category,
                original_url=row.image_url,
                filename=filename,
                downloaded=content is not None,
            )
        )

    _write_manifest(out_dir, photos)
    return ExportReport(photos=photos)


def _write_manifest(out_dir: Path, photos: list[PhotoRecord]) -> None:
    manifest = {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "photos": [
            {
                "public_id": p.public_id,
                "booth_name": p.booth_name,
                "dish_name": p.dish_name,
                "category": p.category,
                "original_url": p.original_url,
                "filename": p.filename,
                "downloaded": p.downloaded,
            }
            for p in photos
        ],
    }
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    # A second copy as a flat table, purely for a human skimming the batch in
    # a spreadsheet while working through it - manifest.json stays the one
    # `import_dish_photos` actually reads.
    with (out_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["public_id", "booth_name", "dish_name", "category", "filename", "downloaded"]
        )
        writer.writeheader()
        for p in photos:
            writer.writerow(
                {
                    "public_id": p.public_id,
                    "booth_name": p.booth_name,
                    "dish_name": p.dish_name,
                    "category": p.category,
                    "filename": p.filename,
                    "downloaded": p.downloaded,
                }
            )


def import_dish_photos(
    in_dir: Path,
    *,
    publish_dir: Path,
    base_url: str,
    overrides_path: Path = DEFAULT_ITEMS_PATH,
) -> ImportReport:
    """Publish whatever processed photos are in `in_dir` and stage their
    URLs as curated overrides, matching each to a dish by the public_id in
    its filename.

    Does not touch the database or need one open - it only reads the
    manifest `export_dish_photos` wrote and the files sitting next to it.
    Deliberately overwrites: unlike the backfill search, running this
    command is a decision to set these specific dishes' photos to what's in
    this folder, whatever was there before.
    """
    manifest_path = in_dir / MANIFEST_NAME
    if not manifest_path.exists():
        raise RuntimeError(f"no {MANIFEST_NAME} in {in_dir} - run `epcot-fw images export` first")
    manifest = json.loads(manifest_path.read_text())

    publish_dir.mkdir(parents=True, exist_ok=True)
    base = base_url.rstrip("/")
    slug = publish_dir.name

    published: list[str] = []
    missing: list[dict[str, Any]] = []
    overrides: list[dict[str, Any]] = []

    for photo in manifest.get("photos") or []:
        public_id = photo["public_id"]
        candidates = sorted(p for p in in_dir.glob(f"{public_id}.*") if p.name != MANIFEST_NAME)
        if not candidates:
            missing.append(photo)
            continue

        src = candidates[0]
        shutil.copy2(src, publish_dir / src.name)
        overrides.append(
            {
                "booth_name": photo["booth_name"],
                "name": photo["dish_name"],
                "image_url": f"{base}/{slug}/{src.name}",
            }
        )
        published.append(photo["dish_name"])

    if overrides:
        merge_menu_item_overrides(overrides_path, overrides, overwrite=True)

    return ImportReport(published=published, missing=missing)
