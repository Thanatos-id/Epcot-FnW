"""Exports the current database into epcot_db_snapshot.json, the input for
fetch_images.py and build_artifact.py. Run from anywhere; paths below are
resolved relative to this file, and epcot_fw is imported from ../../src.

    python tools/data_ledger/export_snapshot.py
    python tools/data_ledger/fetch_images.py
    python tools/data_ledger/build_artifact.py
"""

import datetime
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from epcot_fw.db.base import SessionLocal  # noqa: E402
from epcot_fw.db.models import Booth, CrawlRun, Festival, MenuItem, MergeConflict, Source  # noqa: E402

OUT_PATH = Path(__file__).parent / "epcot_db_snapshot.json"


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

        booth_data = []
        for b in booths:
            items = session.query(MenuItem).filter_by(booth_id=b.id, is_active=True).all()
            booth_data.append(
                {
                    "name": b.canonical_name,
                    "category": b.category,
                    "image_url": b.image_url,
                    # Carried so build_survey.py can show what is already
                    # placed and what still needs walking to.
                    "latitude": b.latitude,
                    "longitude": b.longitude,
                    "location_precision": b.location_precision,
                    "location_description": b.location_description,
                    "items": [
                        {
                            "name": it.canonical_name,
                            "description": it.description,
                            "category": it.category,
                            "price": it.price_usd,
                            "image_url": it.image_url,
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


if __name__ == "__main__":
    export()
