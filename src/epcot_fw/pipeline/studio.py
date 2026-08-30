"""Applies a changeset exported by docs/studio.html.

The studio is a static page. It can read the published snapshot and it can
hold work in the browser, but it cannot write to the repo, so the last step
of a session is a downloaded file:

    epcot-fw studio apply ~/Downloads/epcot-changeset-....json

That file is the same shape as the curated files it lands in, with one
addition: a dish may carry a `photo` block of base64 bytes. Photos are why
this exists at all. The editor it replaces exported a JSON block to paste by
hand, which works fine for a corrected price and not at all for a megabyte
of image, so the whole export became a file and this became the thing that
reads it.

What happens here, in order:

  1. every `photo` is decoded into the publish directory (docs/dish-photos/
     by default, served by GitHub Pages like the rest of docs/) and replaced
     by an `image_url` pointing at it - the same convention
     pipeline/photo_workflow.py already publishes under;
  2. what is left is merged into data/manual/menu_items.json and
     data/manual/booth_locations.json, preserving anything already there;
  3. the caller stages and re-resolves, exactly as `epcot-fw manual` does.

Steps 1 and 2 need no database, which is what makes the whole thing
testable without one - and what lets `--dry-run` report on a changeset
someone emailed you before any of it touches the disk.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from epcot_fw.pipeline.manual import (
    DEFAULT_ITEMS_PATH,
    DEFAULT_PATH,
    merge_booth_overrides,
    merge_menu_item_overrides,
)

logger = logging.getLogger(__name__)

SUPPORTED_VERSION = 1

_EXTENSION_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_DEFAULT_EXTENSION = ".jpg"

# A photo id is normally a public_id or a browser-generated uuid, but the
# changeset is a plain JSON file that a person can open and edit, so it is
# treated as untrusted: anything outside this alphabet is replaced by a
# digest of the original rather than reaching a filesystem path.
_SAFE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

# What a changeset is allowed to put into the curated files. A changeset is a
# plain JSON file someone can open and edit, and the curated files are read
# by people as well as by pipeline/manual.py, so an unrecognised key is
# dropped here rather than copied into a file it will sit in forever meaning
# nothing. These match the fields manual.py understands, plus the two the
# studio adds: `rename_to` and `new`.
_MENU_ITEM_KEYS = frozenset({
    "booth_name", "name", "rename_to", "description", "price_usd",
    "category", "image_url", "dietary_tags", "is_active", "new",
})
_BOOTH_KEYS = frozenset({
    "name", "latitude", "longitude", "location_precision",
    "location_description", "region_theme", "category", "is_active", "new",
})


@dataclass
class ApplyReport:
    photos: list[str] = field(default_factory=list)
    menu_items: list[str] = field(default_factory=list)
    booths: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.menu_items) + len(self.booths)


class ChangesetError(RuntimeError):
    """The file is not a changeset this build knows how to apply."""


def _safe_stem(photo_id: str) -> str:
    """A filename stem that cannot escape the publish directory.

    A well-formed id passes through unchanged so the file keeps the name the
    dish's public_id gives it, which is what makes the photo re-findable
    later. Anything else - a path separator, a `..`, an id built from a dish
    name by an older studio build - is replaced by a digest, which is ugly
    but stable and safe.
    """
    if _SAFE_ID.match(photo_id) and ".." not in photo_id:
        return photo_id
    return "photo-" + hashlib.sha256(photo_id.encode("utf-8")).hexdigest()[:32]


def _decode_photo(photo: dict[str, Any]) -> tuple[str, bytes]:
    """(filename, bytes) for one photo block."""
    photo_id = str(photo.get("id") or "").strip()
    if not photo_id:
        raise ChangesetError("a photo block has no id")
    data = photo.get("data_base64")
    if not isinstance(data, str) or not data:
        raise ChangesetError(f"photo {photo_id} carries no data")
    try:
        content = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ChangesetError(f"photo {photo_id} is not valid base64: {exc}") from exc
    extension = _EXTENSION_BY_MIME.get(str(photo.get("mime") or "").lower(), _DEFAULT_EXTENSION)
    return _safe_stem(photo_id) + extension, content


def load_changeset(path: Path) -> dict[str, Any]:
    """Read and sanity-check a changeset file."""
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ChangesetError(f"{path} is not readable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ChangesetError(f"{path} is not a changeset object")

    version = payload.get("version")
    if version != SUPPORTED_VERSION:
        raise ChangesetError(
            f"{path} is a version {version!r} changeset; this build applies version "
            f"{SUPPORTED_VERSION}. Rebuild docs/studio.html, or upgrade epcot-fw."
        )
    return payload


def apply_changeset(
    path: Path,
    *,
    publish_dir: Path,
    base_url: str,
    items_path: Path = DEFAULT_ITEMS_PATH,
    booths_path: Path = DEFAULT_PATH,
    dry_run: bool = False,
) -> ApplyReport:
    """Publish the changeset's photos and merge the rest into the curated
    files. Does not touch the database - the caller stages and re-resolves.

    Deliberately overwrites what is already curated: exporting a changeset
    is a decision that these specific dishes should say exactly this. That
    is the same stance `epcot-fw images import` takes, and the opposite of
    `backfill-images`, which is a search and leaves a chosen value alone.
    """
    payload = load_changeset(path)
    report = ApplyReport()

    base = base_url.rstrip("/")
    slug = publish_dir.name

    item_entries: list[dict[str, Any]] = []
    for raw in payload.get("menu_items") or []:
        name = (raw.get("name") or "").strip()
        booth_name = (raw.get("booth_name") or "").strip()
        if not name or not booth_name:
            # A dish is only identified by the pair, so there is nothing to
            # match this against. Reported rather than guessed at.
            report.skipped.append(f"menu item {name or '(unnamed)'}: missing booth_name or name")
            continue

        entry = {k: v for k, v in raw.items() if k in _MENU_ITEM_KEYS}
        photo = raw.get("photo")
        if isinstance(photo, dict):
            filename, content = _decode_photo(photo)
            if not dry_run:
                publish_dir.mkdir(parents=True, exist_ok=True)
                (publish_dir / filename).write_bytes(content)
            entry["image_url"] = f"{base}/{slug}/{filename}"
            report.photos.append(filename)

        item_entries.append(entry)
        label = f"{booth_name} / {raw.get('rename_to') or name}"
        report.menu_items.append(label)
        if raw.get("new"):
            report.added.append(label)
        if raw.get("is_active") is False:
            report.deleted.append(label)

    booth_entries: list[dict[str, Any]] = []
    for raw in payload.get("booths") or []:
        name = (raw.get("name") or "").strip()
        if not name:
            report.skipped.append("booth: missing name")
            continue
        booth_entries.append({k: v for k, v in raw.items() if k in _BOOTH_KEYS})
        report.booths.append(name)
        if raw.get("new"):
            report.added.append(name)
        if raw.get("is_active") is False:
            report.deleted.append(name)

    if not dry_run:
        if item_entries:
            merge_menu_item_overrides(items_path, item_entries, overwrite=True)
        if booth_entries:
            merge_booth_overrides(booths_path, booth_entries, overwrite=True)

    return report
