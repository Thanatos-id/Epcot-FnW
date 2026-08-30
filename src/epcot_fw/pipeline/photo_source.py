"""Where each dish photo came from.

Every photo on this project's pages was taken by somebody else - almost all
of them by Disney Food Blog - and until now nothing recorded that next to
the picture. The database knows: a photo arrives as an extracted_record on a
raw_page, and both survive as provenance, so a served image_url can be
traced back to the source that offered it and often to the exact post it was
published in.

Attribution is matched on the value being served rather than on
`entity_field_provenance.is_selected`. That flag is not reliable - most
dishes here have a candidate row that carries exactly the URL on the dish
and is still flagged unselected - and the question being asked has an exact
answer anyway: of the candidates for this field, which one is the string the
dish is actually showing.

A page URL is only available for photos a crawl found. The ones staged by
`backfill-images` come in through the curated file, which records the image
and not the article it was on, so those carry a publisher and a season but
no link. That is a gap in what was captured, not an error here.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import EntityFieldProvenance, ExtractedRecord, MenuItem, RawPage

FIELD = "image_url"

# WordPress files uploads under /wp-content/uploads/YYYY/MM/, which is what
# dates a photo to a season. A URL with no such stamp is undated, not current.
_UPLOAD_YEAR_RE = re.compile(r"/uploads/(?P<year>20\d{2})/")

# Photos this project published itself, from docs/studio.html. Matched on the
# path rather than the host so a fork's Pages domain works too.
_OWN_PHOTO_PATH = "/dish-photos/"

# Who to credit, by the host actually serving the image.
PUBLISHERS = {
    "disneyfoodblog.com": "Disney Food Blog",
    "allears.net": "AllEars.Net",
    "disneyparksblog.com": "Disney Parks Blog",
    "touringplans.com": "TouringPlans",
    "wdwmagic.com": "WDWMagic",
    "wdwprepschool.com": "WDW Prep School",
    "disneyworld.disney.go.com": "Walt Disney World",
}

OWN_CREDIT = "Added by hand"


def photo_season(image_url: str | None) -> int | None:
    """The festival year a photo URL dates itself to, if it says."""
    if not image_url:
        return None
    match = _UPLOAD_YEAR_RE.search(image_url)
    return int(match.group("year")) if match else None


def is_hand_published(image_url: str | None) -> bool:
    return bool(image_url) and _OWN_PHOTO_PATH in image_url


def photo_credit(image_url: str | None) -> str | None:
    """Who to credit for this photo, from the host serving it."""
    if not image_url:
        return None
    if is_hand_published(image_url):
        return OWN_CREDIT
    host = urlparse(image_url).netloc.lower().removeprefix("www.")
    # The host itself when it is not one we know: better an honest domain
    # than a blank credit or a guess at a publisher's name.
    return PUBLISHERS.get(host, host or None)


def image_sources(session: Session, item_ids: list[int]) -> dict[int, dict[str, Any]]:
    """{menu_item_id: attribution} for the photo each dish is serving.

    Batched rather than per dish: the ledger export asks about every item on
    the menu at once, and a per-item query would be a few hundred round trips
    for a page build.
    """
    if not item_ids:
        return {}

    items = {
        i.id: i
        for i in session.scalars(select(MenuItem).where(MenuItem.id.in_(item_ids))).all()
        if i.image_url
    }
    if not items:
        return {}

    rows = session.scalars(
        select(EntityFieldProvenance).where(
            EntityFieldProvenance.entity_type == "menu_item",
            EntityFieldProvenance.field_name == FIELD,
            EntityFieldProvenance.canonical_id.in_(list(items)),
        )
    ).all()

    # The candidate carrying exactly what the dish is showing.
    winner: dict[int, EntityFieldProvenance] = {}
    for row in rows:
        item = items.get(row.canonical_id)
        if item is not None and str(row.value) == item.image_url:
            winner.setdefault(row.canonical_id, row)

    record_ids = [r.extracted_record_id for r in winner.values() if r.extracted_record_id]
    pages: dict[int, str] = {}
    if record_ids:
        for record_id, url in session.execute(
            select(ExtractedRecord.id, RawPage.url)
            .join(RawPage, RawPage.id == ExtractedRecord.raw_page_id)
            .where(ExtractedRecord.id.in_(record_ids))
        ).all():
            # manual:// staging URLs address a curated file, not an article.
            if url and url.startswith("http"):
                pages[record_id] = url

    out: dict[int, dict[str, Any]] = {}
    for item_id, item in items.items():
        row = winner.get(item_id)
        out[item_id] = {
            "credit": photo_credit(item.image_url),
            "site": urlparse(item.image_url).netloc or None,
            "season": photo_season(item.image_url),
            "page_url": pages.get(row.extracted_record_id) if row else None,
            "via": row.source.key if row else None,
        }
    return out
