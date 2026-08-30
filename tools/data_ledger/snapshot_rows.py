"""Turns one exported snapshot into the row shapes the pages work from.

Both pages that let a person change something - docs/studio.html and
docs/survey.html - have to agree about what is in the database. They are
built from the same `epcot_db_snapshot.json` in the same run, but that only
guarantees the same *input*; it took shared functions to guarantee the same
reading of it. A survey page listing a booth the studio has never heard of
is a lap walked for nothing.

Both functions are pure - snapshot in, plain lists out - so what reaches a
page is testable without a browser or a database.
"""

from __future__ import annotations

from typing import Any

# A heading on the source pages covering dishes sold in several places at
# once, not somewhere a person can stand. Offering it for placement would be
# asking for a coordinate that is wrong by construction.
AGGREGATE_BOOTH_NAME = "Additional Festival Locations"


def studio_rows(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Flatten the snapshot into the two lists the studio edits.

    Menu items are flattened out of their booths and carry `booth` with them,
    because a dish is only identified by the pair - five booths sell
    something called "Beer Flight" - and that pair is what a curated record
    needs to find it again.

    `public_id` comes along for a different reason: it is the one identifier
    stable across a rename and a full re-resolution, so it is what an
    attached photo file gets named by, exactly as in
    pipeline/photo_workflow.py. A row without one is a row whose photo would
    be orphaned by the next rebuild.
    """
    booths, items = [], []
    for booth in snapshot.get("booths") or []:
        name = booth.get("name")
        if not name:
            continue
        booths.append(
            {
                "name": name,
                "public_id": booth.get("public_id"),
                "origin": booth.get("origin") or "crawled",
                "category": booth.get("category"),
                "location_description": booth.get("location_description"),
                "latitude": booth.get("latitude"),
                "longitude": booth.get("longitude"),
                "location_precision": booth.get("location_precision"),
                "item_count": len(booth.get("items") or []),
            }
        )
        for item in booth.get("items") or []:
            if not item.get("name"):
                continue
            items.append(
                {
                    "booth": name,
                    "name": item.get("name"),
                    "public_id": item.get("public_id"),
                    "origin": item.get("origin") or "crawled",
                    "description": item.get("description"),
                    "price": item.get("price"),
                    "category": item.get("category"),
                    "tags": sorted(item.get("tags") or []),
                    "image_url": item.get("image_url"),
                    # Inlined by fetch_images.py, so the page shows the photo
                    # it already has without a network round trip. Absent
                    # when the dish has no photo, or when the fetch failed -
                    # both render as the same empty state, which is honest:
                    # either way there is no picture to look at.
                    "image": item.get("image_data_uri"),
                }
            )
    return {"booths": booths, "items": items}


def survey_booths(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """The booth list a capture page works from, in capture order.

    Unplaced booths sort first: they are the ones the walk exists for, and a
    surveyor scrolling a phone one-handed should not have to hunt for them.
    Within a group, name order - it is the only order that stays stable
    between builds, which matters when someone is halfway down the list.
    """
    rank = {None: 0, "anchored": 1, "mapped": 2, "surveyed": 3}
    booths = [
        {
            "name": b.get("name"),
            "latitude": b.get("latitude"),
            "longitude": b.get("longitude"),
            "precision": b.get("location_precision"),
            "location_description": b.get("location_description"),
        }
        for b in (snapshot.get("booths") or [])
        if b.get("name") and b["name"] != AGGREGATE_BOOTH_NAME
    ]
    return sorted(booths, key=lambda b: (rank.get(b["precision"], 3), b["name"].lower()))
