"""Retires booths and dishes that the sources have stopped listing.

Nothing used to clear `is_active`, so every entity ever seen stayed live
forever. That was harmless while the festival lineup was static, and stops
being harmless the moment a new season's menus land: last year's booths and
dishes would sit alongside this year's, indistinguishable, and an app built
on this data would send someone to a booth that no longer exists.

The signal is `raw_pages.superseded_by_id`. Each canonical entity traces back
through canonical_links -> extracted_records -> raw_pages, and
fetch/cache.py marks a page superseded only when its *content actually
changed*. That distinction is what makes this safe to run on every crawl:

  * page refetched and unchanged -> same raw_page, not superseded -> its
    entities stay supported. A quiet week deactivates nothing.
  * page content changed        -> old raw_page superseded, new one parsed.
    Entities the new content still mentions get fresh links; the ones it
    dropped are left supported only by superseded pages, and retire.
  * source not crawled at all   -> its pages aren't superseded, so its
    entities keep their support. A skipped or failing source cannot retire
    anything.

The `manual` source is deliberately excluded from the support calculation.
Curated data says *where a booth is*, not *that it is running this year* - a
coordinate surveyed last season must not be what keeps a defunct booth alive.

That exclusion is right for a curated *correction* to a crawled row and
wrong for a row that only ever existed because somebody typed it into
docs/studio.html. Those carry `origin = 'curated'` and are skipped entirely:
no crawled page will ever vouch for a dish the sources have not noticed, so
letting this pass judge them would retire every one of them on the next
crawl. Their `is_active` comes from the curated file instead, which is how
deleting a hand-added dish works.

Reactivation is handled by the same pass: support is recomputed from scratch
each run, so a booth that returns next season comes back on its own.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import Booth, CanonicalLink, ExtractedRecord, MenuItem, RawPage, Source

logger = logging.getLogger(__name__)

MANUAL_SOURCE_KEY = "manual"

# Rows a person added by hand rather than any source listing them.
CURATED_ORIGIN = "curated"

# Booths are pavilion-anchored and largely stable season to season, so losing
# most of them at once means a broken selector rather than a real lineup
# change. Refuse past this share so the failure reports itself instead of
# silently emptying the festival.
MAX_DEACTIVATION_RATIO = 0.6

# Deliberately NOT applied to menu items. Dishes turn over almost completely
# between seasons - a fresh menu drop legitimately retires most of the
# previous year's items, and a ratio guard tuned for booths would read that
# as a failure and block the whole pass (including the booths). For items the
# meaningful signal is whether the sources produced *any* supporting records
# at all: zero means nothing parsed, which is the failure worth catching.


@dataclass
class ReconcileStats:
    booths_deactivated: int = 0
    booths_reactivated: int = 0
    items_deactivated: int = 0
    items_reactivated: int = 0
    # Set when a guard refused to apply the pass; the reason is surfaced in
    # the crawl stats rather than only in the log.
    skipped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        out = {
            "booths_deactivated": self.booths_deactivated,
            "booths_reactivated": self.booths_reactivated,
            "items_deactivated": self.items_deactivated,
            "items_reactivated": self.items_reactivated,
        }
        if self.skipped:
            out["reconcile_skipped"] = ", ".join(self.skipped)
        return out


def _supported_ids(
    session: Session, entity_type: str, excluded_source_ids: list[int]
) -> set[int]:
    """Canonical ids still vouched for by at least one live (non-superseded)
    page from a source other than the excluded ones."""
    stmt = (
        select(CanonicalLink.canonical_id)
        .join(ExtractedRecord, CanonicalLink.extracted_record_id == ExtractedRecord.id)
        .join(RawPage, ExtractedRecord.raw_page_id == RawPage.id)
        .where(
            CanonicalLink.entity_type == entity_type,
            RawPage.superseded_by_id.is_(None),
        )
    )
    if excluded_source_ids:
        stmt = stmt.where(CanonicalLink.source_id.not_in(excluded_source_ids))
    return set(session.scalars(stmt).all())


def _guard(
    label: str, active_count: int, losing_count: int, force: bool, *, ratio_guard: bool
) -> str | None:
    """Reason to refuse, or None to proceed."""
    if active_count == 0 or losing_count == 0:
        return None
    if losing_count == active_count:
        return f"{label}: every active row lost support - treating as a parse failure"
    if not ratio_guard:
        return None
    ratio = losing_count / active_count
    if ratio > MAX_DEACTIVATION_RATIO and not force:
        return (
            f"{label}: {losing_count}/{active_count} ({ratio:.0%}) would retire, "
            f"above the {MAX_DEACTIVATION_RATIO:.0%} guard"
        )
    return None


def run_reconciliation(
    session: Session, *, festival_id: int, force: bool = False
) -> ReconcileStats:
    """Align `is_active` on this festival's booths and menu items with what
    the sources currently say. Safe to run after every crawl."""
    stats = ReconcileStats()

    manual_source_ids = [
        s.id for s in session.scalars(select(Source).where(Source.key == MANUAL_SOURCE_KEY)).all()
    ]

    all_booths = session.scalars(select(Booth).where(Booth.festival_id == festival_id)).all()
    if not all_booths:
        return stats
    all_booth_ids = {b.id for b in all_booths}
    all_items = session.scalars(select(MenuItem).where(MenuItem.booth_id.in_(all_booth_ids))).all()

    # Hand-added rows are not up for judgement here - not for retirement, and
    # not as part of the totals the guards below are measured against, where
    # they would only dilute the ratio that is meant to catch a broken parse.
    booths = [b for b in all_booths if b.origin != CURATED_ORIGIN]
    items = [i for i in all_items if i.origin != CURATED_ORIGIN]
    booth_ids = {b.id for b in booths}

    supported_booths = _supported_ids(session, "booth", manual_source_ids) & booth_ids
    supported_items = _supported_ids(session, "menu_item", manual_source_ids) & {i.id for i in items}

    # A dish cannot outlive the booth that serves it, even if some page still
    # mentions it in isolation.
    curated_booth_ids = {b.id for b in all_booths if b.origin == CURATED_ORIGIN and b.is_active}
    supported_items = {
        i.id
        for i in items
        if i.id in supported_items and i.booth_id in (supported_booths | curated_booth_ids)
    }

    booth_reason = _guard(
        "booths",
        sum(1 for b in booths if b.is_active),
        sum(1 for b in booths if b.is_active and b.id not in supported_booths),
        force,
        ratio_guard=True,
    )
    item_reason = _guard(
        "menu items",
        sum(1 for i in items if i.is_active),
        sum(1 for i in items if i.is_active and i.id not in supported_items),
        force,
        ratio_guard=False,
    )
    # Retiring booths without their dishes (or vice versa) would leave the
    # data self-inconsistent, so either both halves apply or neither does.
    reason = booth_reason or item_reason
    if reason:
        logger.warning("reconciliation skipped - %s (re-run with force to override)", reason)
        stats.skipped.append(reason)
        return stats

    for booth in booths:
        should_be_active = booth.id in supported_booths
        if booth.is_active != should_be_active:
            booth.is_active = should_be_active
            if should_be_active:
                stats.booths_reactivated += 1
            else:
                stats.booths_deactivated += 1

    for item in items:
        should_be_active = item.id in supported_items
        if item.is_active != should_be_active:
            item.is_active = should_be_active
            if should_be_active:
                stats.items_reactivated += 1
            else:
                stats.items_deactivated += 1

    session.flush()

    if stats.booths_deactivated or stats.items_deactivated:
        logger.info(
            "retired %d booth(s) and %d menu item(s) no longer listed by any source",
            stats.booths_deactivated,
            stats.items_deactivated,
        )
    return stats
