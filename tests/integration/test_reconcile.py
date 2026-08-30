"""Retiring entities the sources stopped listing.

The interesting cases are all about *not* retiring things: an unchanged page,
a source that wasn't crawled, a parse regression that drops everything. Those
are what separate a useful reconciliation pass from one that empties the
festival the first time a selector breaks.
"""

import datetime
import json

from sqlalchemy import select

from epcot_fw.db.models import Booth, ExtractedRecord, MenuItem, RawPage, Source
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.pipeline.reconcile import (
    MAX_DEACTIVATION_RATIO,
    run_reconciliation,
)
from epcot_fw.resolve.merge import resolve_extracted_record


def _booth_dto(name):
    return ExtractedRecordDTO(
        entity_type="booth",
        natural_key_hint=name.lower(),
        payload={"name": name, "category": "global_marketplace"},
    )


def _item_dto(booth_name, name):
    return ExtractedRecordDTO(
        entity_type="menu_item",
        natural_key_hint=name.lower(),
        payload={"booth_name": booth_name, "name": name, "category": "food"},
    )


def _publish(db_session, festival_id, source_key, url, dtos, *, supersede=True):
    """Stage `dtos` as a fetch of `url`, superseding any previous version of
    that page the way fetch/cache.py does when content changes."""
    source = db_session.scalars(select(Source).where(Source.key == source_key)).one()
    now = datetime.datetime.now(datetime.UTC)

    prior = db_session.scalars(
        select(RawPage).where(RawPage.url == url, RawPage.superseded_by_id.is_(None))
    ).first()

    page = RawPage(
        source_id=source.id,
        url=url,
        page_kind="booth_list",
        fetched_at=now,
        http_status=200,
        content_hash=f"{url}-{len(dtos)}-{now.timestamp()}",
        raw_html="<html></html>",
        first_seen_at=now,
    )
    db_session.add(page)
    db_session.flush()
    if prior is not None and supersede:
        prior.superseded_by_id = page.id
        db_session.flush()

    for entity_type in ("booth", "menu_item"):
        for dto in dtos:
            if dto.entity_type != entity_type:
                continue
            record = ExtractedRecord(
                raw_page_id=page.id,
                source_id=source.id,
                entity_type=dto.entity_type,
                extracted_at=now,
                extractor_version="test",
                payload=dto.payload,
                natural_key_hint=dto.natural_key_hint,
            )
            db_session.add(record)
            db_session.flush()
            resolve_extracted_record(db_session, record, source, festival_id=festival_id)
    db_session.flush()


def _names(db_session, active):
    return {
        b.canonical_name
        for b in db_session.scalars(select(Booth).where(Booth.is_active.is_(active))).all()
    }


HUB = "https://example.test/hub"

# Distinct after normalize_name(), which strips words like "booth" and
# "marketplace" - naming test fixtures "Booth 1..N" collapses them to bare
# digits that no longer match.
COUNTRIES = [
    "Norway", "Italy", "Japan", "Morocco", "France",
    "Canada", "China", "Mexico", "Germany", "Brazil",
]

# Two menus with no shared vocabulary. Near-identical names ("Old Dish 1"
# vs "New Dish 1") fuzzy-merge into each other instead of replacing, which
# is right for a renamed dish but useless for testing turnover.
OLD_DISHES = [
    "Warm Raclette Swiss Cheese", "Kirschwasser Torte", "Frozen Rose",
    "Stiegl Radler", "Alpine Ham Board",
]
NEW_DISHES = [
    "Grilled Bushberry Shrimp Skewer", "Lamington Cake", "Pavlova Cup",
    "Yalumba Viognier", "Barramundi Fillet",
]


def test_a_booth_dropped_from_the_new_lineup_is_retired(db_session):
    festival_id = db_session.info["festival_id"]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("The Alps"), _booth_dto("Retired Pavilion")])
    assert _names(db_session, True) == {"The Alps", "Retired Pavilion"}

    # New season's page: "Retired Pavilion" is gone, a new one appears.
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("The Alps"), _booth_dto("Brand New Pavilion")])
    stats = run_reconciliation(db_session, festival_id=festival_id)

    assert stats.booths_deactivated == 1
    assert _names(db_session, True) == {"The Alps", "Brand New Pavilion"}
    assert _names(db_session, False) == {"Retired Pavilion"}


def test_dishes_of_a_retired_booth_are_retired_with_it(db_session):
    festival_id = db_session.info["festival_id"]
    _publish(
        db_session, festival_id, "allears", HUB,
        [_booth_dto("Gone Pavilion"), _item_dto("Gone Pavilion", "Doomed Dish"),
         _booth_dto("Staying"), _item_dto("Staying", "Safe Dish")],
    )
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("Staying"), _item_dto("Staying", "Safe Dish")])

    run_reconciliation(db_session, festival_id=festival_id)

    active = {i.canonical_name for i in db_session.scalars(select(MenuItem).where(MenuItem.is_active.is_(True))).all()}
    assert active == {"Safe Dish"}


def test_an_unchanged_page_retires_nothing(db_session):
    """The common case - a quiet week. The page is refetched, the content
    hash matches, no new raw_page is created, and nothing must be retired."""
    festival_id = db_session.info["festival_id"]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("A"), _booth_dto("B")])

    stats = run_reconciliation(db_session, festival_id=festival_id)

    assert (stats.booths_deactivated, stats.items_deactivated) == (0, 0)
    assert _names(db_session, True) == {"A", "B"}


def test_a_source_that_was_not_crawled_retires_nothing(db_session):
    """A skipped or failing source leaves its pages un-superseded, so the
    booths only it knows about must survive."""
    festival_id = db_session.info["festival_id"]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("Norway")])
    _publish(db_session, festival_id, "disney_food_blog", "https://example.test/dfb",
             [_booth_dto("Morocco")])

    # Only AllEars publishes a new page this run.
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("Norway")])
    run_reconciliation(db_session, festival_id=festival_id)

    assert "Morocco" in _names(db_session, True)


def test_a_returning_booth_is_reactivated(db_session):
    festival_id = db_session.info["festival_id"]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("Seasonal"), _booth_dto("Anchor")])
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("Anchor")])
    run_reconciliation(db_session, festival_id=festival_id)
    assert _names(db_session, False) == {"Seasonal"}

    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("Seasonal"), _booth_dto("Anchor")])
    stats = run_reconciliation(db_session, festival_id=festival_id)

    assert stats.booths_reactivated == 1
    assert _names(db_session, False) == set()


def test_a_parse_regression_that_drops_everything_is_refused(db_session):
    """The failure this guard exists for: a broken selector yields no records,
    the page still counts as changed, and every booth loses support at once."""
    festival_id = db_session.info["festival_id"]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("A"), _booth_dto("B"), _booth_dto("C")])

    _publish(db_session, festival_id, "allears", HUB, [])  # parsed nothing
    stats = run_reconciliation(db_session, festival_id=festival_id)

    assert stats.booths_deactivated == 0
    assert stats.skipped, "a total wipe must be refused, not applied"
    assert _names(db_session, True) == {"A", "B", "C"}


def test_a_mass_deactivation_beyond_the_guard_is_refused(db_session):
    festival_id = db_session.info["festival_id"]
    names = COUNTRIES
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto(n) for n in names])

    # Only 2 of 10 survive - an 80% drop, past the guard.
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto(n) for n in names[:2]])
    stats = run_reconciliation(db_session, festival_id=festival_id)

    assert stats.booths_deactivated == 0
    assert stats.skipped
    assert len(_names(db_session, True)) == 10


def test_a_mass_deactivation_can_be_forced(db_session):
    festival_id = db_session.info["festival_id"]
    names = COUNTRIES
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto(n) for n in names])
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto(n) for n in names[:2]])

    stats = run_reconciliation(db_session, festival_id=festival_id, force=True)

    assert stats.booths_deactivated == 8
    assert not stats.skipped


def test_a_turnover_within_the_guard_is_applied(db_session):
    festival_id = db_session.info["festival_id"]
    names = COUNTRIES
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto(n) for n in names])

    keep = names[:6]  # 40% retired, inside the guard
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto(n) for n in keep])
    stats = run_reconciliation(db_session, festival_id=festival_id)

    assert stats.booths_deactivated == 4
    assert not stats.skipped
    assert 4 / 10 < MAX_DEACTIVATION_RATIO


def test_a_near_total_menu_refresh_is_applied_not_refused(db_session):
    """The real shape of a new season: the booths mostly stay, the dishes
    almost all change. A ratio guard tuned for booths would read that as a
    parse failure and block the whole pass, so menu items are guarded only on
    having produced no records at all."""
    festival_id = db_session.info["festival_id"]
    old_menu = [_item_dto("Norway", n) for n in OLD_DISHES]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("Norway"), *old_menu])

    new_menu = [_item_dto("Norway", n) for n in NEW_DISHES]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("Norway"), *new_menu])
    stats = run_reconciliation(db_session, festival_id=festival_id)

    assert not stats.skipped, "a 100% menu turnover with a stable booth must apply"
    assert stats.items_deactivated == len(OLD_DISHES)
    assert stats.booths_deactivated == 0
    active = {
        i.canonical_name
        for i in db_session.scalars(select(MenuItem).where(MenuItem.is_active.is_(True))).all()
    }
    assert active == set(NEW_DISHES)


def test_menu_items_are_still_protected_when_nothing_parses(db_session):
    festival_id = db_session.info["festival_id"]
    menu = [_item_dto("Norway", f"Dish {i}") for i in range(5)]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("Norway"), *menu])

    # Booth still parses, menu section doesn't - a partial selector break.
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("Norway")])
    stats = run_reconciliation(db_session, festival_id=festival_id)

    assert stats.skipped, "losing every dish at once is a parse failure"
    assert stats.items_deactivated == 0


def test_curated_data_alone_does_not_keep_a_defunct_booth_alive(db_session, tmp_path):
    """Curation says where a booth is, not that it is running this season."""
    from epcot_fw.pipeline.manual import stage_manual_overrides
    from epcot_fw.pipeline.resolve_pipeline import run_resolve

    festival_id = db_session.info["festival_id"]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("The Alps"), _booth_dto("Anchor")])

    path = tmp_path / "manual.json"
    path.write_text('{"booths": [{"name": "The Alps", "latitude": 28.37, "longitude": -81.55}]}')
    # items_path points at a file that doesn't exist, isolating this from the
    # repo's real data/manual/menu_items.json - without it, staging that
    # file's real curated dishes here (which have no supporting raw_page,
    # same as anything curated) trips reconciliation's "every active item
    # lost support" parse-failure guard and the run is skipped wholesale.
    stage_manual_overrides(db_session, path=path, items_path=tmp_path / "no-menu-items.json")
    run_resolve(db_session, festival_id=festival_id)

    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("Anchor")])
    run_reconciliation(db_session, festival_id=festival_id)

    assert "The Alps" in _names(db_session, False), "manual support must not preserve it"


def _curate(db_session, festival_id, tmp_path, payload):
    """Stage `payload` as the curated file and resolve it, the way
    `epcot-fw studio apply` does at the end of a studio session."""
    from epcot_fw.pipeline.manual import stage_manual_overrides
    from epcot_fw.pipeline.resolve_pipeline import run_resolve

    items_path = tmp_path / "menu_items.json"
    booths_path = tmp_path / "booth_locations.json"
    items_path.write_text(json.dumps({"menu_items": payload.get("menu_items", [])}))
    booths_path.write_text(json.dumps({"booths": payload.get("booths", [])}))
    stage_manual_overrides(db_session, path=booths_path, items_path=items_path)
    run_resolve(db_session, festival_id=festival_id)


def test_a_hand_added_dish_survives_the_crawl_that_never_mentions_it(db_session, tmp_path):
    """The whole reason `origin` exists.

    No crawled page will ever vouch for a dish the sources have not noticed,
    so the ordinary support calculation retires it on the first crawl after
    it lands - which would make adding one in the studio pointless."""
    festival_id = db_session.info["festival_id"]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("The Alps"), _item_dto("The Alps", "Frozen Rose")])
    _curate(db_session, festival_id, tmp_path, {
        "menu_items": [{"booth_name": "The Alps", "name": "Kirschwasser Torte", "new": True}]
    })

    added = db_session.scalars(
        select(MenuItem).where(MenuItem.canonical_name == "Kirschwasser Torte")
    ).one()
    assert added.origin == "curated"

    # A later crawl of the same booth that still does not list it.
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("The Alps"), _item_dto("The Alps", "Frozen Rose")])
    run_reconciliation(db_session, festival_id=festival_id)

    db_session.refresh(added)
    assert added.is_active, "a hand-added dish must not be retired for having no crawled page"


def test_a_hand_added_booth_and_its_dishes_survive(db_session, tmp_path):
    festival_id = db_session.info["festival_id"]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("The Alps")])
    _curate(db_session, festival_id, tmp_path, {
        "booths": [{"name": "Brew-Wing Lab", "new": True, "latitude": 28.37, "longitude": -81.55}],
    })
    booth = db_session.scalars(select(Booth).where(Booth.canonical_name == "Brew-Wing Lab")).one()
    assert booth.origin == "curated"

    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("The Alps")])
    run_reconciliation(db_session, festival_id=festival_id)

    db_session.refresh(booth)
    assert booth.is_active


def test_curated_rows_do_not_count_toward_the_deactivation_guard(db_session, tmp_path):
    """A pile of hand-added booths would dilute the ratio the guard measures,
    so a genuinely broken parse could slip under it."""
    festival_id = db_session.info["festival_id"]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto(name) for name in COUNTRIES])
    _curate(db_session, festival_id, tmp_path, {
        "booths": [{"name": "Hand Added " + str(i), "new": True} for i in range(20)],
    })

    # Every crawled booth vanishes: a parse failure, and it must still be
    # caught even though curated rows now outnumber the crawled ones.
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("Norway")])
    stats = run_reconciliation(db_session, festival_id=festival_id)

    assert stats.skipped, "the guard must still see 9 of 10 crawled booths losing support"
    assert stats.booths_deactivated == 0


def test_a_curated_dish_marked_inactive_stays_retired(db_session, tmp_path):
    """Deleting a hand-added dish in the studio is a curated is_active."""
    festival_id = db_session.info["festival_id"]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("The Alps")])
    _curate(db_session, festival_id, tmp_path, {
        "menu_items": [{"booth_name": "The Alps", "name": "Regretted Dish", "new": True}]
    })
    dish = db_session.scalars(select(MenuItem).where(MenuItem.canonical_name == "Regretted Dish")).one()
    assert dish.is_active

    _curate(db_session, festival_id, tmp_path, {
        "menu_items": [{"booth_name": "The Alps", "name": "Regretted Dish", "is_active": False}]
    })
    db_session.refresh(dish)
    assert not dish.is_active

    run_reconciliation(db_session, festival_id=festival_id)
    db_session.refresh(dish)
    assert not dish.is_active, "reconciliation must not resurrect what curation retired"


def test_reconciliation_on_an_empty_festival_is_a_no_op(db_session):
    stats = run_reconciliation(db_session, festival_id=db_session.info["festival_id"])
    assert (stats.booths_deactivated, stats.items_deactivated) == (0, 0)
    assert not stats.skipped


def test_running_twice_changes_nothing_the_second_time(db_session):
    festival_id = db_session.info["festival_id"]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("A"), _booth_dto("B")])
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("A")])

    first = run_reconciliation(db_session, festival_id=festival_id)
    second = run_reconciliation(db_session, festival_id=festival_id)

    assert first.booths_deactivated == 1
    assert (second.booths_deactivated, second.booths_reactivated) == (0, 0)


def test_stats_reach_the_crawl_record(db_session):
    festival_id = db_session.info["festival_id"]
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("A"), _booth_dto("B")])
    _publish(db_session, festival_id, "allears", HUB, [_booth_dto("A")])

    stats = run_reconciliation(db_session, festival_id=festival_id).as_dict()
    assert stats["booths_deactivated"] == 1
    assert "reconcile_skipped" not in stats
