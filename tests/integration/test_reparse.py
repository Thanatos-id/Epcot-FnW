"""pipeline/reparse.py: fixing already-cached data after a parser bug is
fixed in code, without refetching anything.

Uses the same savepoint_session/stub_registry pattern as
test_crawl_and_refresh_pipeline.py, since run_reparse() commits internally.
The stub adapter's parse() is swapped mid-test from a "buggy" version (name
carries the whole run-on line, no price) to a "fixed" one, mirroring exactly
what happened for real in af2d195/869f8f9: the site's HTML never changed,
only our extraction logic did.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from epcot_fw.db.models import Booth, CanonicalLink, Festival, MenuItem, Source
from epcot_fw.normalize.text import normalize_name
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.pipeline.crawl import run_full_crawl
from epcot_fw.pipeline.reparse import run_reparse
from epcot_fw.sources.base import SeedUrl, SourceAdapter


class BuggyThenFixedAdapter(SourceAdapter):
    """One booth, one dish, whose parse() the test flips mid-run - exactly
    the shape of a real parser bug fix landing after content was crawled."""

    key = "stub_dfb"
    priority_rank = 6

    mode = "buggy"

    def seed_urls(self, festival_year):
        return [SeedUrl(url="https://stub-dfb.test/germany-2026/", page_kind="booth_detail")]

    def parse(self, raw_html, url, page_kind):
        records = [
            ExtractedRecordDTO(
                entity_type="booth",
                natural_key_hint=normalize_name("Germany"),
                payload={"name": "Germany", "category": "global_marketplace"},
            )
        ]
        if self.mode == "buggy":
            name = "Kirschwasser Torte - Chocolate cherry torte with kirsch - $6.50"
            price = None
        else:
            name = "Kirschwasser Torte"
            price = "6.50"
        records.append(
            ExtractedRecordDTO(
                entity_type="menu_item",
                natural_key_hint=normalize_name(name),
                payload={"booth_name": "Germany", "name": name, "description": None, "price_usd": price},
            )
        )
        return records


@pytest.fixture()
def savepoint_session(engine):
    connection = engine.connect()
    trans = connection.begin()
    session = Session(
        bind=connection, future=True, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    session.add(
        Source(
            key="stub_dfb",
            display_name="Stub DFB",
            base_url="https://stub-dfb.test",
            priority_rank=6,
            enabled=True,
            crawl_delay_sec=0,
        )
    )
    festival = Festival(
        year=2026,
        name="EPCOT International Food & Wine Festival 2026",
        slug="epcot-food-wine-2026",
        status="upcoming",
    )
    session.add(festival)
    session.flush()
    session.info["festival_id"] = festival.id

    yield session

    session.close()
    trans.rollback()
    connection.close()


@pytest.fixture()
def stub_adapter():
    return BuggyThenFixedAdapter()


@pytest.fixture()
def stub_registry(monkeypatch, stub_adapter):
    import epcot_fw.pipeline.crawl as crawl_module
    import epcot_fw.pipeline.reparse as reparse_module

    registry = {"stub_dfb": stub_adapter}
    monkeypatch.setattr(crawl_module, "SOURCE_REGISTRY", registry)
    monkeypatch.setattr(reparse_module, "SOURCE_REGISTRY", registry)
    return registry


def _crawl_with_buggy_page(session, adapter, monkeypatch):
    import httpx
    import respx

    from epcot_fw.fetch import rate_limiter

    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)
    adapter.mode = "buggy"
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://stub-dfb.test/robots.txt").mock(return_value=httpx.Response(404))
        mock.get("https://stub-dfb.test/germany-2026/").mock(
            return_value=httpx.Response(200, text="<html>whatever DFB currently serves</html>")
        )
        return run_full_crawl(session, confirm_tos=True)


def test_reparse_fixes_a_stale_name_and_backfills_price_without_duplicating_the_dish(
    savepoint_session, stub_registry, stub_adapter, monkeypatch
):
    _crawl_with_buggy_page(savepoint_session, stub_adapter, monkeypatch)

    item = savepoint_session.scalars(select(MenuItem)).one()
    assert item.canonical_name.startswith("Kirschwasser Torte -")
    assert item.price_usd is None

    stub_adapter.mode = "fixed"
    totals = run_reparse(savepoint_session)

    assert savepoint_session.scalars(select(MenuItem)).all() == [item], (
        "must reconnect to the same row, not create a second dish"
    )
    refreshed = savepoint_session.get(MenuItem, item.id)
    assert refreshed.canonical_name == "Kirschwasser Torte"
    assert str(refreshed.price_usd) == "6.50"

    assert totals["pages_reparsed"] == 1
    assert totals["records_extracted"] == 2  # the booth + the dish
    assert totals["records_relinked"] == 2
    assert totals["errors"] == 0


def test_reparse_does_not_touch_the_network(savepoint_session, stub_registry, stub_adapter, monkeypatch):
    """No respx mock is installed at all here - if run_reparse tried to fetch
    anything, httpx would raise a connection error and fail the test."""
    _crawl_with_buggy_page(savepoint_session, stub_adapter, monkeypatch)

    stub_adapter.mode = "fixed"
    totals = run_reparse(savepoint_session)  # no respx.mock() context at all

    assert totals["pages_reparsed"] == 1


def test_reparse_with_nothing_cached_yet_is_a_harmless_no_op(savepoint_session, stub_registry):
    totals = run_reparse(savepoint_session)

    assert totals["pages_reparsed"] == 0
    assert totals["records_extracted"] == 0


def test_a_source_with_no_registered_adapter_is_skipped_not_crashed(savepoint_session, stub_registry):
    """`manual` is a real, enabled Source row with no crawlable adapter (it's
    staged from a file, never fetched) - reparse must skip it like crawl and
    refresh do, not raise."""
    savepoint_session.add(
        Source(
            key="manual",
            display_name="Manual curation",
            base_url="manual://curated",
            priority_rank=0,
            enabled=True,
            crawl_delay_sec=0,
        )
    )
    savepoint_session.flush()

    totals = run_reparse(savepoint_session)

    assert totals["pages_reparsed"] == 0


def test_reparse_raises_when_no_sources_enabled(savepoint_session, stub_registry):
    for source in savepoint_session.query(Source).all():
        source.enabled = False
    savepoint_session.flush()

    with pytest.raises(RuntimeError, match="No sources are enabled"):
        run_reparse(savepoint_session)


def test_a_page_that_fails_to_reparse_is_skipped_without_aborting_the_run(
    savepoint_session, stub_registry, stub_adapter, monkeypatch
):
    _crawl_with_buggy_page(savepoint_session, stub_adapter, monkeypatch)

    def _boom(raw_html, url, page_kind):
        raise ValueError("malformed page")

    monkeypatch.setattr(stub_adapter, "parse", _boom)

    totals = run_reparse(savepoint_session)

    assert totals["pages_reparsed"] == 1
    assert totals["errors"] == 1
    assert totals["records_extracted"] == 0


def test_a_genuinely_new_item_on_reparse_is_matched_fresh_not_dropped(
    savepoint_session, stub_registry, stub_adapter, monkeypatch
):
    """Positional pairing only covers what lined up with something already
    there - an item with no old counterpart at its position still reaches
    the canonical layer, through the ordinary fuzzy-match path."""
    _crawl_with_buggy_page(savepoint_session, stub_adapter, monkeypatch)
    assert savepoint_session.query(MenuItem).count() == 1

    def _two_items(raw_html, url, page_kind):
        return [
            ExtractedRecordDTO(
                entity_type="booth",
                natural_key_hint=normalize_name("Germany"),
                payload={"name": "Germany", "category": "global_marketplace"},
            ),
            ExtractedRecordDTO(
                entity_type="menu_item",
                natural_key_hint=normalize_name("Kirschwasser Torte"),
                payload={"booth_name": "Germany", "name": "Kirschwasser Torte", "price_usd": "6.50"},
            ),
            ExtractedRecordDTO(
                entity_type="menu_item",
                natural_key_hint=normalize_name("Bratwurst Platter"),
                payload={"booth_name": "Germany", "name": "Bratwurst Platter", "price_usd": "9.00"},
            ),
        ]

    monkeypatch.setattr(stub_adapter, "parse", _two_items)
    totals = run_reparse(savepoint_session)

    names = {i.canonical_name for i in savepoint_session.query(MenuItem).all()}
    assert names == {"Kirschwasser Torte", "Bratwurst Platter"}
    assert totals["records_relinked"] == 2  # booth + the dish that lined up
    assert totals["canonical_upserts"] == 1  # the new dish, resolved fresh


def test_booth_fields_are_reparsed_too_not_only_menu_items(
    savepoint_session, stub_registry, stub_adapter, monkeypatch
):
    """The positional-relink mechanism is generic to any entity_type, not
    special-cased to menu_item - prove it on the booth record in the same
    page."""
    _crawl_with_buggy_page(savepoint_session, stub_adapter, monkeypatch)
    booth = savepoint_session.scalars(select(Booth)).one()
    assert booth.region_theme is None

    def _renamed_region(raw_html, url, page_kind):
        return [
            ExtractedRecordDTO(
                entity_type="booth",
                natural_key_hint=normalize_name("Germany"),
                payload={"name": "Germany", "category": "global_marketplace", "region_theme": "Europe"},
            ),
            ExtractedRecordDTO(
                entity_type="menu_item",
                natural_key_hint=normalize_name("Kirschwasser Torte"),
                payload={"booth_name": "Germany", "name": "Kirschwasser Torte", "price_usd": "6.50"},
            ),
        ]

    monkeypatch.setattr(stub_adapter, "parse", _renamed_region)
    run_reparse(savepoint_session)

    assert savepoint_session.get(Booth, booth.id).region_theme == "Europe"
    assert savepoint_session.query(Booth).count() == 1


def test_reparse_is_idempotent(savepoint_session, stub_registry, stub_adapter, monkeypatch):
    _crawl_with_buggy_page(savepoint_session, stub_adapter, monkeypatch)
    stub_adapter.mode = "fixed"

    run_reparse(savepoint_session)
    item_after_first = savepoint_session.scalars(select(MenuItem)).one()

    second_totals = run_reparse(savepoint_session)
    item_after_second = savepoint_session.scalars(select(MenuItem)).one()

    assert item_after_first.id == item_after_second.id
    assert item_after_second.canonical_name == "Kirschwasser Torte"
    assert second_totals["pages_reparsed"] == 1


def test_relinked_records_get_their_own_canonical_link_row(
    savepoint_session, stub_registry, stub_adapter, monkeypatch
):
    """A reparse must not reuse the *old* extracted_record's link - each
    fresh extracted_record gets its own CanonicalLink row pointing at the
    same canonical_id, preserving one link per extracted_record."""
    _crawl_with_buggy_page(savepoint_session, stub_adapter, monkeypatch)
    before = savepoint_session.query(CanonicalLink).count()

    stub_adapter.mode = "fixed"
    run_reparse(savepoint_session)

    after = savepoint_session.query(CanonicalLink).count()
    assert after == before * 2  # a new link for the booth and for the dish

    links = savepoint_session.scalars(
        select(CanonicalLink).where(CanonicalLink.match_method == "reparse")
    ).all()
    assert len(links) == 2
