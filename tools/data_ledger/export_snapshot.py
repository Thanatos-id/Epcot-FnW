"""Exports the current database, twice, for two different readers.

    python tools/data_ledger/export_snapshot.py
    python tools/data_ledger/fetch_images.py
    python tools/data_ledger/build_artifact.py

`epcot_db_snapshot.json` is the ledger's input - nested, local, gitignored,
and shaped for rendering pages.

`docs/v1/snapshot.json` is the client contract: what a phone downloads. It is
built by the API's own `build_snapshot`, so the published file and a live
`/api/v1/snapshot` response are the same bytes for the same data and an app
can move between them without touching its decoder.

Both come out of one session, so the ledger and the app can never disagree
about what is in the database. Run from anywhere; paths resolve relative to
this file, and epcot_fw is imported from ../../src.
"""

import datetime
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from epcot_fw.api.routers.snapshot import build_snapshot  # noqa: E402
from epcot_fw.db.base import SessionLocal  # noqa: E402
from epcot_fw.db.models import (  # noqa: E402
    Booth,
    CrawlRun,
    Festival,
    MenuItem,
    MergeConflict,
    Source,
)
from epcot_fw.pipeline.photo_source import image_sources  # noqa: E402

OUT_PATH = Path(__file__).parent / "epcot_db_snapshot.json"

# Versioned in the path, not in a query string: a v2 with an incompatible
# shape gets published beside this one rather than replacing it, so builds
# already on people's phones keep reading something they understand.
CLIENT_DIR = Path(__file__).parent.parent.parent / "docs" / "v1"
CLIENT_PATH = CLIENT_DIR / "snapshot.json"


def _default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    return str(o)


def export() -> None:
    with SessionLocal() as session:
        festival = session.query(Festival).first()
        # Mirror what the API serves - retired booths/dishes are no longer
        # part of this festival, so the ledger should not count them.
        booths = (
            session.query(Booth)
            .filter_by(is_active=True)
            .order_by(Booth.canonical_name)
            .all()
        )

        # Every photo here was taken by somebody else. Resolved once for the
        # whole menu rather than per dish, which would be a few hundred round
        # trips for one page build.
        credits = image_sources(
            session,
            [
                row.id
                for row in session.query(MenuItem.id)
                .filter(MenuItem.booth_id.in_([b.id for b in booths]), MenuItem.is_active.is_(True))
                .all()
            ],
        )

        booth_data = []
        for b in booths:
            items = session.query(MenuItem).filter_by(booth_id=b.id, is_active=True).all()
            booth_data.append(
                {
                    "name": b.canonical_name,
                    # The one identifier stable across a rename and a full
                    # re-resolution. docs/studio.html names an attached photo
                    # file by it, the same way `epcot-fw images export` does.
                    "public_id": str(b.public_id),
                    "category": b.category,
                    "image_url": b.image_url,
                    "origin": b.origin,
                    # Carried so build_survey.py can show what is already
                    # placed and what still needs walking to.
                    "latitude": b.latitude,
                    "longitude": b.longitude,
                    "location_precision": b.location_precision,
                    "location_description": b.location_description,
                    "items": [
                        {
                            "name": it.canonical_name,
                            "public_id": str(it.public_id),
                            "origin": it.origin,
                            "description": it.description,
                            "category": it.category,
                            "price": it.price_usd,
                            "image_url": it.image_url,
                            # Who took the photo, when, and the post it ran in
                            # where that was captured - see pipeline/photo_source.py.
                            "image_source": credits.get(it.id),
                            "tags": [t.code for t in it.dietary_tags],
                        }
                        for it in items
                    ],
                }
            )

        sources = [
            {"key": s.key, "name": s.display_name, "url": s.base_url, "priority": s.priority_rank, "enabled": s.enabled}
            for s in session.query(Source).order_by(Source.priority_rank).all()
        ]
        conflicts = [
            {"entity_type": c.entity_type, "field": c.field_name, "values": c.candidate_values}
            for c in session.query(MergeConflict).filter_by(status="open").all()
        ]
        runs = [
            {"type": r.run_type, "status": r.status, "started_at": r.started_at, "stats": r.stats}
            for r in session.query(CrawlRun).order_by(CrawlRun.started_at.desc()).all()
        ]

        out = {
            "festival": {
                "name": festival.name,
                "start": festival.start_date,
                "end": festival.end_date,
                "status": festival.status,
            },
            "booths": booth_data,
            "sources": sources,
            "conflicts": conflicts,
            "runs": runs,
        }

        OUT_PATH.write_text(json.dumps(out, default=_default))
        print(f"wrote {OUT_PATH} ({len(booth_data)} booths, {sum(len(b['items']) for b in booth_data)} items)")

        # Compact separators, sorted keys: the file is machine-read, and a
        # stable key order means an unchanged database produces an identical
        # file - so git sees no diff and GitHub Pages keeps serving the same
        # ETag, which is what lets a returning phone download nothing.
        client = build_snapshot(session, festival)
        CLIENT_DIR.mkdir(parents=True, exist_ok=True)
        CLIENT_PATH.write_text(
            json.dumps(client, default=_default, sort_keys=True, separators=(",", ":")) + "\n"
        )
        size_kb = CLIENT_PATH.stat().st_size / 1024
        print(
            f"wrote {CLIENT_PATH} ({len(client['booths'])} booths, "
            f"{len(client['menu_items'])} items, {size_kb:.0f} KB, "
            f"schema v{client['schema_version']})"
        )


if __name__ == "__main__":
    export()
