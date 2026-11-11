"""The multi-festival client feed: one snapshot per festival, and an index.

`docs/v1/snapshot.json` is one festival - whichever the database calls
current - and every installed build reads it. It stays exactly as it is.

Beside it, for builds that can show more than one festival:

    docs/v1/festivals.json                    - the index
    docs/v1/festivals/<key>/snapshot.json     - one per festival

Each per-festival file is the same contract as `snapshot.json` (the app
decodes both with one decoder), with three things added to its `festival`
object: `key`, `short_name` and `menu_season`.

Where each festival comes from:

- Food & Wine is the database festival, so its file is the already
  published `snapshot.json` with those three fields added. Reading the
  published file rather than the database means this needs no database, and
  the two can never describe different data.
- The others live in `data/festivals/<key>/` (see epcot_fw.festival_files)
  and are converted here from those files into the client shape.

`menu_season` is the year the menus actually come from. A festival whose
next edition has dates but no published menus carries last year's menus, and
`menu_season` is how a client says so ("Showing 2025 menus"). Bump it in
`festival.json` when the new menus go in.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

from epcot_fw import festival_files
from epcot_fw.db.seed import DIETARY_TAGS
from epcot_fw.festival import festival_status
from epcot_fw.resolve.merge import slugify

SCHEMA_VERSION = 1

# Calendar order, which is the order a client lists them in.
FESTIVAL_ORDER = (
    "festival-of-the-arts",
    "flower-and-garden",
    festival_files.DATABASE_FESTIVAL_KEY,
    "festival-of-the-holidays",
)

# What the database festival would keep in a festival.json if it had one.
DATABASE_FESTIVAL_META = {
    "short_name": "Food & Wine",
    "typical_dates": "Late August to late November",
}

# Synthetic `festival.id`s for the file-backed festivals, well clear of the
# database's autoincrement. Nothing may be saved against them - see
# `public_id` in docs/CLIENT_API.md - but the contract requires an integer.
_FILE_FESTIVAL_IDS = {
    "festival-of-the-arts": 1001,
    "flower-and-garden": 1002,
    "festival-of-the-holidays": 1003,
}

_TAGS = {code: (label, kind) for code, label, kind in DIETARY_TAGS}
_TRAILING_YEAR_RE = re.compile(r"\s+\d{4}\Z")


def _tag(code: str) -> dict[str, str]:
    label, kind = _TAGS.get(code, (code.replace("_", " ").title(), "dietary"))
    return {"code": code, "label": label, "kind": kind}


def _decimal_string(value: Any, places: int | None = None) -> str | None:
    """Numbers travel as strings in the client contract, as the API's Decimals do."""
    if value is None or value == "":
        return None
    return f"{float(value):.{places}f}" if places is not None else str(value)


def _image_source(source: dict[str, Any] | None) -> dict[str, Any] | None:
    """{credit, site, season, page_url} -> the contract's {name, url, site, season}."""
    if not source:
        return None
    site = source.get("site")
    return {
        "name": source.get("credit"),
        # Always a working link when there is a credit - see CLIENT_API.md.
        "url": source.get("page_url") or (f"https://{site}" if site else None),
        "site": site,
        "season": source.get("season"),
    }


def build_file_snapshot(key: str, root: Path = festival_files.FESTIVALS_DIR) -> dict[str, Any]:
    """A file-backed festival in the client contract, without `data_updated_at`.

    Integer ids are positions in the files and mean nothing outside this one
    payload; `public_id` is the identity, exactly as for the database
    festival. Retired rows are left out, and a retired booth takes its
    dishes with it.
    """
    directory = festival_files.festival_dir(key, root)
    meta = festival_files.load_meta(key, root)
    _, booth_entries = festival_files._read(directory / "booths.json", "booths")
    _, item_entries = festival_files._read(directory / "menu_items.json", "menu_items")
    festival_id = _FILE_FESTIVAL_IDS[key]
    year = meta.get("year")

    booths: list[dict[str, Any]] = []
    booth_ids: dict[str, int] = {}
    for position, entry in enumerate(booth_entries, start=1):
        name = (entry.get("name") or "").strip()
        if not name or entry.get("is_active") is False or name in booth_ids:
            continue
        booth_ids[name] = position
        booths.append(
            {
                "id": position,
                "public_id": entry.get("public_id"),
                "festival_id": festival_id,
                "canonical_name": name,
                "slug": slugify(name),
                "category": entry.get("category"),
                "region_theme": entry.get("region_theme"),
                "description": entry.get("description"),
                "location_description": entry.get("location_description"),
                "opens_at": entry.get("opens_at"),
                "latitude": _decimal_string(entry.get("latitude")),
                "longitude": _decimal_string(entry.get("longitude")),
                "location_precision": entry.get("location_precision"),
                "image_url": entry.get("image_url"),
                "origin": entry.get("origin") or "researched",
                "is_active": True,
            }
        )

    menu_items: list[dict[str, Any]] = []
    for position, entry in enumerate(item_entries, start=1):
        name = (entry.get("name") or "").strip()
        booth_id = booth_ids.get((entry.get("booth_name") or "").strip())
        if not name or booth_id is None or entry.get("is_active") is False:
            continue
        menu_items.append(
            {
                "id": position,
                "public_id": entry.get("public_id"),
                "booth_id": booth_id,
                "canonical_name": name,
                "description": entry.get("description"),
                "category": entry.get("category") or "food",
                "price_usd": _decimal_string(entry.get("price_usd"), places=2),
                "image_url": entry.get("image_url"),
                "image_source": _image_source(entry.get("image_source")) if entry.get("image_url") else None,
                "origin": entry.get("origin") or "researched",
                "is_new_this_year": bool(entry.get("is_new_this_year")),
                "alcohol_kind": entry.get("alcohol_kind"),
                "is_active": True,
                "dietary_tags": [_tag(code) for code in sorted(entry.get("dietary_tags") or [])],
                "flavor_tags": [_tag(code) for code in sorted(entry.get("flavor_tags") or [])],
            }
        )

    booths.sort(key=lambda b: b["canonical_name"])
    menu_items.sort(key=lambda i: i["canonical_name"])

    start, end = meta.get("start"), meta.get("end")
    return {
        "schema_version": SCHEMA_VERSION,
        "min_app_version": None,
        "festival": {
            "id": festival_id,
            "key": key,
            "year": year,
            "name": _TRAILING_YEAR_RE.sub("", meta.get("name") or key),
            "short_name": meta.get("short_name") or key,
            "slug": f"{key}-{year}",
            "start_date": start,
            "end_date": end,
            "status": _status(start, end),
            "official_url": meta.get("official_url"),
            "typical_dates": meta.get("typical_dates"),
            "menu_season": meta.get("menu_season") or year,
        },
        "booths": booths,
        "menu_items": menu_items,
        "events": [],
        "seminars": [],
    }


def _status(start: str | None, end: str | None) -> str:
    derived = festival_status(
        datetime.date.fromisoformat(start) if start else None,
        datetime.date.fromisoformat(end) if end else None,
    )
    # An unknown status reads as running client-side rather than hiding a menu.
    return derived or "upcoming"


def tag_database_snapshot(published: dict[str, Any]) -> dict[str, Any]:
    """The published single-festival snapshot, as that festival's own file."""
    festival = dict(published["festival"])
    festival["key"] = festival_files.DATABASE_FESTIVAL_KEY
    festival.update(DATABASE_FESTIVAL_META)
    # The database festival is crawled for its own year, so it is always current.
    festival["menu_season"] = festival.get("year")
    return {**published, "festival": festival}


def _stamped(payload: dict[str, Any], path: Path, now: datetime.datetime) -> dict[str, Any]:
    """Give a file-backed payload its `data_updated_at`.

    When the data last changed, not when this ran: an unchanged festival
    keeps the stamp already published, so the file is byte-identical and a
    returning phone downloads nothing.
    """
    if path.exists():
        previous = json.loads(path.read_text())
        stamp = previous.pop("data_updated_at", None)
        if stamp and previous == payload:
            return {**payload, "data_updated_at": stamp}
    return {**payload, "data_updated_at": now.isoformat()}


def index_entry(payload: dict[str, Any]) -> dict[str, Any]:
    festival = payload["festival"]
    key = festival["key"]
    return {
        "key": key,
        "name": festival["name"],
        "short_name": festival["short_name"],
        "year": festival["year"],
        "start_date": festival["start_date"],
        "end_date": festival["end_date"],
        "status": festival["status"],
        "typical_dates": festival["typical_dates"],
        "menu_season": festival["menu_season"],
        "data_updated_at": payload["data_updated_at"],
        "snapshot": f"festivals/{key}/snapshot.json",
    }


def _dump(payload: dict[str, Any]) -> str:
    # Same serialisation as export_snapshot.py: compact and key-sorted, so
    # unchanged data is an unchanged file.
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) + "\n"


def write_feed(
    client_dir: Path,
    root: Path = festival_files.FESTIVALS_DIR,
    now: datetime.datetime | None = None,
) -> list[dict[str, Any]]:
    """Write every per-festival snapshot and the index. Returns the index rows.

    Reads `client_dir/snapshot.json` for the database festival, so run it
    after `export_snapshot.py` has written that file (which it does itself).
    """
    now = now or datetime.datetime.now(datetime.UTC)
    available = set(festival_files.available(root))
    entries: list[dict[str, Any]] = []

    for key in FESTIVAL_ORDER:
        path = client_dir / "festivals" / key / "snapshot.json"
        if key == festival_files.DATABASE_FESTIVAL_KEY:
            published = client_dir / "snapshot.json"
            if not published.exists():
                continue
            payload = tag_database_snapshot(json.loads(published.read_text()))
        elif key in available:
            payload = _stamped(build_file_snapshot(key, root), path, now)
        else:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_dump(payload))
        entries.append(index_entry(payload))

    index = {"schema_version": SCHEMA_VERSION, "min_app_version": None, "festivals": entries}
    (client_dir / "festivals.json").write_text(_dump(index))
    return entries
