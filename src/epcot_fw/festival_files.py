"""Festivals that live in files until the pipeline can crawl them.

The database holds one festival at a time on purpose - see epcot_fw.festival.
`current_festival` picks the running festival, else the soonest one still to
come, and every crawl, resolve and export follows it. A row for Festival of
the Holidays seeded today would therefore take over the daily refresh the
morning after Food & Wine closes, and point seven Food & Wine source adapters
at it. Nothing about that is ready.

So a festival the crawl cannot reach yet is researched by hand into
`data/festivals/<key>/` instead:

    festival.json    - name, dates, and the sources the research came from
    booths.json      - the booths, in the shape of data/manual/booth_locations.json
    menu_items.json  - the dishes, in the shape of data/manual/menu_items.json

Those files *are* the data, not overrides on top of some crawled record, so
two things differ from the database festival:

- docs/studio.html shows them as a festival of their own, editable, with its
  edits kept apart from the database festival's in the browser;
- `epcot-fw studio apply` writes a changeset from that festival straight back
  into these files (`apply_entries` below) rather than into data/manual/,
  and resolves nothing, because there is no database row to resolve into.

Nothing here touches the database, the published feed (docs/v1/), or the
curated files under data/manual/. The day this festival is crawled, these
files become what they were all along - research to check the crawl against.

Standard library only, so the page build can use it without a database.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

FESTIVALS_DIR = Path(__file__).resolve().parents[2] / "data" / "festivals"

# The festival the database and data/manual/ describe. A changeset that
# names it - or names nothing, which is every changeset older builds wrote -
# goes down the ordinary path.
DATABASE_FESTIVAL_KEY = "food-and-wine"

# Festivals whose data lives in data/festivals/<key>/. Keys match the
# Studio's festival catalog (tools/data_ledger/build_studio.py: FESTIVALS).
FILE_BACKED = ("festival-of-the-arts", "flower-and-garden", "festival-of-the-holidays")

MENU_ITEM_CATEGORIES = frozenset({"food", "alcoholic_beverage", "non_alcoholic_beverage"})

# How sure the research is that a dish is on the coming festival's menu, as
# the Studio labels it: `<year>-menu` (it was on that year's menu, and this
# year's is not out yet), `likely-<year>`, `confirmed-<year>`. Absent on a
# dish added by hand: a person typed it in from the menu board, which is the
# strongest evidence there is.
_STATUS_RE = re.compile(r"\A(?:(?P<menu>\d{4})-menu|likely-(?P<likely>\d{4})|confirmed-(?P<confirmed>\d{4}))\Z")


def status_label(status: str | None) -> str | None:
    """'2025-menu' -> '2025 menu', 'confirmed-2026' -> 'Confirmed 2026'; None if not a status."""
    match = _STATUS_RE.match(status or "")
    if not match:
        return None
    if match["menu"]:
        return f"{match['menu']} menu"
    if match["likely"]:
        return f"Likely {match['likely']}"
    return f"Confirmed {match['confirmed']}"

_ITEM_FIELDS = (
    "description", "price_usd", "category", "dietary_tags", "flavor_tags",
    "alcohol_kind", "is_new_this_year", "image_url", "is_active",
)
_BOOTH_FIELDS = (
    "latitude", "longitude", "location_precision", "location_description",
    "region_theme", "category", "opens_at", "is_active",
)


class FestivalDataError(ValueError):
    """The festival key or one of its files is not something this can use."""


def festival_dir(key: str, root: Path = FESTIVALS_DIR) -> Path:
    if key not in FILE_BACKED:
        raise FestivalDataError(
            f"{key!r} is not a file-backed festival (known: {', '.join(FILE_BACKED)})"
        )
    return root / key


def _read(path: Path, list_key: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not path.exists():
        return {}, []
    payload = json.loads(path.read_text())
    return payload, list(payload.get(list_key) or [])


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def load_meta(key: str, root: Path = FESTIVALS_DIR) -> dict[str, Any]:
    path = festival_dir(key, root) / "festival.json"
    return json.loads(path.read_text()) if path.exists() else {"key": key}


def available(root: Path = FESTIVALS_DIR) -> list[str]:
    """The file-backed festivals that actually have a booth file on disk."""
    return [key for key in FILE_BACKED if (root / key / "booths.json").exists()]


def _badges(entry: dict[str, Any], stroll_label: str) -> list[str]:
    badges = []
    label = status_label(entry.get("status"))
    if label:
        badges.append(label)
    # Each festival's food stroll has its own name - Cookie Stroll, Garden
    # Graze, Wonderful Walk - kept once in festival.json.
    if entry.get("stroll") or entry.get("cookie_stroll"):
        badges.append(stroll_label)
    return badges


def build_snapshot(key: str, root: Path = FESTIVALS_DIR) -> dict[str, Any]:
    """The festival's files read into the shape export_snapshot.py writes.

    Same keys per booth and per dish as the database snapshot, so
    tools/data_ledger/snapshot_rows.py and the Studio need no second reading
    of it. Retired rows (`is_active: false`) are left out, exactly as the
    export leaves out retired database rows - and a retired booth takes its
    dishes with it.
    """
    directory = festival_dir(key, root)
    meta = load_meta(key, root)
    _, booth_entries = _read(directory / "booths.json", "booths")
    _, item_entries = _read(directory / "menu_items.json", "menu_items")

    booths: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for entry in booth_entries:
        name = (entry.get("name") or "").strip()
        if not name or entry.get("is_active") is False or name in by_name:
            continue
        booth = {
            "name": name,
            "public_id": entry.get("public_id"),
            "category": entry.get("category"),
            "image_url": entry.get("image_url"),
            "origin": entry.get("origin") or "researched",
            "latitude": entry.get("latitude"),
            "longitude": entry.get("longitude"),
            "location_precision": entry.get("location_precision"),
            "location_description": entry.get("location_description"),
            "opens_at": entry.get("opens_at"),
            "items": [],
        }
        booths.append(booth)
        by_name[name] = booth

    for entry in item_entries:
        name = (entry.get("name") or "").strip()
        booth = by_name.get((entry.get("booth_name") or "").strip())
        if not name or booth is None or entry.get("is_active") is False:
            continue
        item = {
            "name": name,
            "public_id": entry.get("public_id"),
            "origin": entry.get("origin") or "researched",
            "is_new_this_year": bool(entry.get("is_new_this_year")),
            "description": entry.get("description"),
            "category": entry.get("category") or "food",
            "price": entry.get("price_usd"),
            "image_url": entry.get("image_url"),
            # {credit, site, season, page_url, via}, as pipeline/photo_source.py
            # gives the database festival - see pipeline/festival_photos.py.
            "image_source": entry.get("image_source"),
            "tags": sorted(entry.get("dietary_tags") or []),
            "flavor_tags": sorted(entry.get("flavor_tags") or []),
            "alcohol_kind": entry.get("alcohol_kind"),
        }
        badges = _badges(entry, meta.get("stroll_label") or "Food stroll")
        if badges:
            item["badges"] = badges
        booth["items"].append(item)

    return {
        "festival": {
            "key": key,
            "name": meta.get("name") or key,
            "start": meta.get("start"),
            "end": meta.get("end"),
        },
        "meta": meta,
        "booths": booths,
    }


def apply_entries(
    directory: Path,
    menu_items: list[dict[str, Any]],
    booths: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> list[str]:
    """Merge one Studio changeset into a file-backed festival's files.

    `menu_items` and `booths` are changeset entries, already filtered to the
    keys pipeline/studio.py allows. Unlike the database path, where a
    changeset is an override resolved onto a crawled row, here the entry
    edits the row in place: a `rename_to` renames it, `new` appends one
    with its own public_id, `is_active: false` retires it (kept in the file,
    left out of the page). Returns what could not be applied, one line each;
    nothing is guessed at.
    """
    skipped: list[str] = []
    items_path = directory / "menu_items.json"
    booths_path = directory / "booths.json"
    items_payload, item_rows = _read(items_path, "menu_items")
    booths_payload, booth_rows = _read(booths_path, "booths")

    booth_index = {row.get("name"): row for row in booth_rows if row.get("name")}
    for raw in booths:
        name = (raw.get("name") or "").strip()
        row = booth_index.get(name)
        if row is None:
            if not raw.get("new"):
                skipped.append(f"booth {name}: not in {booths_path.name}")
                continue
            row = {"name": name, "public_id": str(uuid.uuid4()), "origin": "curated"}
            booth_rows.append(row)
            booth_index[name] = row
        for field in _BOOTH_FIELDS:
            if field in raw:
                row[field] = raw[field]
        # A pin dropped in the Studio replaces the one borrowed from another
        # festival's booth, so the note saying where it came from goes too.
        if "latitude" in raw:
            row.pop("pinned_from", None)

    item_index = {
        (row.get("booth_name"), row.get("name")): row
        for row in item_rows
        if row.get("booth_name") and row.get("name")
    }
    for raw in menu_items:
        booth_name = (raw.get("booth_name") or "").strip()
        name = (raw.get("name") or "").strip()
        label = f"{booth_name} / {name}"
        category = raw.get("category")
        if category is not None and category not in MENU_ITEM_CATEGORIES:
            skipped.append(f"menu item {label}: category {category!r} is not one of "
                           f"{sorted(MENU_ITEM_CATEGORIES)}")
            continue
        if booth_name not in booth_index:
            skipped.append(f"menu item {label}: no booth {booth_name!r}")
            continue
        row = item_index.get((booth_name, name))
        if row is None:
            if not raw.get("new"):
                skipped.append(f"menu item {label}: not in {items_path.name}")
                continue
            row = {"booth_name": booth_name, "name": name, "public_id": str(uuid.uuid4()),
                   "origin": "curated"}
            item_rows.append(row)
            item_index[(booth_name, name)] = row
        for field in _ITEM_FIELDS:
            if field in raw:
                row[field] = raw[field]
        rename_to = (raw.get("rename_to") or "").strip()
        if rename_to and rename_to != name:
            if (booth_name, rename_to) in item_index:
                skipped.append(f"menu item {label}: rename to {rename_to!r} would duplicate a dish")
            else:
                del item_index[(booth_name, name)]
                row["name"] = rename_to
                item_index[(booth_name, rename_to)] = row

    if not dry_run:
        if booths:
            _write(booths_path, {**booths_payload, "booths": booth_rows})
        if menu_items:
            _write(items_path, {**items_payload, "menu_items": item_rows})
    return skipped
